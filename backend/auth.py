"""
Authentication for the public multi-user app.

A single Google "Sign in with Google" flow doubles as both the login AND the
Gmail authorization: the same consent grants `gmail.readonly`, so the signed-in
identity IS the mailbox we scan.

Responsibilities:
  - Google OAuth 2.0 **web** flow (built from env vars, not credentials.json)
  - User storage in Supabase (`users` table), with the Google refresh token
    stored Fernet-encrypted at rest
  - Stateless sessions via a signed httpOnly JWT cookie
  - `get_current_user` FastAPI dependency that gates every data endpoint
"""

import os
import json
import time
import secrets
import logging
from typing import Optional, Dict, Any, List

import jwt
from fastapi import APIRouter, Request, Response, HTTPException, Depends
from fastapi.responses import RedirectResponse

# OAuth scopes — login identity (openid/email/profile) + read-only Gmail access.
# gmail.send / spreadsheets are intentionally dropped for the public build.
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.readonly",
]

GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"

SESSION_COOKIE = "session"
STATE_COOKIE = "oauth_state"
SESSION_TTL_SECONDS = 30 * 24 * 3600  # 30 days

# Google returns openid scopes in a different order / adds scopes — relax so the
# oauthlib token exchange doesn't raise on the scope mismatch.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")


# --- Environment helpers -----------------------------------------------------

def _redirect_uri() -> str:
    uri = os.environ.get("OAUTH_REDIRECT_URI", "http://localhost:8000/api/auth/callback")
    # Allow http only for localhost development (Google permits localhost over http).
    if uri.startswith("http://"):
        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
    return uri


def _is_secure_cookie() -> bool:
    return _redirect_uri().startswith("https://")


def _session_secret() -> str:
    secret = os.environ.get("SESSION_SECRET")
    if not secret:
        raise RuntimeError("SESSION_SECRET env var is required to sign session cookies.")
    return secret


# --- Refresh-token encryption (Fernet) ---------------------------------------

def _fernet():
    from cryptography.fernet import Fernet
    key = os.environ.get("TOKEN_ENC_KEY")
    if not key:
        raise RuntimeError(
            "TOKEN_ENC_KEY env var is required to encrypt refresh tokens. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def _encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def _decrypt(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()


# --- Supabase user storage ---------------------------------------------------

def _get_supabase():
    """Returns an authenticated Supabase client, or None if not configured."""
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key or key == "YOUR_SERVICE_ROLE_KEY_HERE":
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception as e:
        logging.warning(f"Could not create Supabase client: {e}")
        return None


def upsert_user(email: str, name: str, picture: str, refresh_token: Optional[str]) -> None:
    """
    Creates or updates a user row. The refresh token is stored encrypted. When
    Google omits a refresh token on re-consent, we keep the previously stored one.
    """
    sb = _get_supabase()
    if not sb:
        raise RuntimeError("Supabase is not configured; cannot persist users.")

    row: Dict[str, Any] = {
        "email": email,
        "name": name,
        "picture": picture,
        "last_login": _now_iso(),
    }
    if refresh_token:
        row["refresh_token"] = _encrypt(refresh_token)
    sb.table("users").upsert(row, on_conflict="email").execute()


def get_user(email: str) -> Optional[Dict[str, Any]]:
    sb = _get_supabase()
    if not sb:
        return None
    resp = sb.table("users").select("*").eq("email", email).limit(1).execute()
    rows = resp.data or []
    return rows[0] if rows else None


def get_user_refresh_token(email: str) -> Optional[str]:
    """Returns the decrypted Google refresh token for a user, or None."""
    user = get_user(email)
    if not user or not user.get("refresh_token"):
        return None
    try:
        return _decrypt(user["refresh_token"])
    except Exception as e:
        logging.error(f"Failed to decrypt refresh token for {email}: {e}")
        return None


def list_user_emails() -> List[str]:
    """All registered user emails — used by the scheduler to scan every mailbox."""
    sb = _get_supabase()
    if not sb:
        return []
    resp = sb.table("users").select("email").execute()
    return [r["email"] for r in (resp.data or []) if r.get("email")]


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# --- Google OAuth flow -------------------------------------------------------

def _build_flow():
    from google_auth_oauthlib.flow import Flow

    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET env vars are required.")

    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": GOOGLE_AUTH_URI,
            "token_uri": GOOGLE_TOKEN_URI,
            "redirect_uris": [_redirect_uri()],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=SCOPES)
    flow.redirect_uri = _redirect_uri()
    return flow


# --- Session JWT -------------------------------------------------------------

def create_session_token(email: str, name: str, picture: str) -> str:
    now = int(time.time())
    payload = {
        "sub": email,
        "name": name,
        "picture": picture,
        "iat": now,
        "exp": now + SESSION_TTL_SECONDS,
    }
    return jwt.encode(payload, _session_secret(), algorithm="HS256")


def _decode_session(token: str) -> Optional[Dict[str, Any]]:
    try:
        return jwt.decode(token, _session_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


# --- FastAPI dependency ------------------------------------------------------

def get_current_user(request: Request) -> Dict[str, Any]:
    """
    Reads + verifies the session cookie. Returns {email, name, picture}.
    Raises 401 when missing/invalid — the gate on every data endpoint.
    """
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    claims = _decode_session(token)
    if not claims:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return {
        "email": claims["sub"],
        "name": claims.get("name", ""),
        "picture": claims.get("picture", ""),
    }


# --- Routes ------------------------------------------------------------------

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/login")
def login():
    """Begin the Google OAuth flow — redirect the user's browser to Google."""
    flow = _build_flow()
    state = secrets.token_urlsafe(32)
    auth_url, _ = flow.authorization_url(
        access_type="offline",     # request a refresh token
        prompt="consent",          # force a refresh token on every consent
        include_granted_scopes="true",
        state=state,
    )
    resp = RedirectResponse(auth_url)
    # Short-lived CSRF cookie validated in the callback.
    resp.set_cookie(
        STATE_COOKIE, state, max_age=600, httponly=True,
        secure=_is_secure_cookie(), samesite="lax",
    )
    return resp


@router.get("/callback")
def callback(request: Request, code: str = "", state: str = "", error: str = ""):
    """Exchange the authorization code, persist the user, set the session cookie."""
    if error:
        raise HTTPException(status_code=400, detail=f"Google OAuth error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    expected_state = request.cookies.get(STATE_COOKIE)
    if not expected_state or state != expected_state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state (possible CSRF)")

    flow = _build_flow()
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        logging.error(f"Token exchange failed: {e}")
        raise HTTPException(status_code=400, detail="Failed to exchange authorization code")

    creds = flow.credentials
    profile = _fetch_userinfo(creds)
    email = profile.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Could not read email from Google profile")

    upsert_user(
        email=email,
        name=profile.get("name", ""),
        picture=profile.get("picture", ""),
        refresh_token=creds.refresh_token,
    )

    session_token = create_session_token(email, profile.get("name", ""), profile.get("picture", ""))
    resp = RedirectResponse("/")
    resp.set_cookie(
        SESSION_COOKIE, session_token, max_age=SESSION_TTL_SECONDS, httponly=True,
        secure=_is_secure_cookie(), samesite="lax",
    )
    resp.delete_cookie(STATE_COOKIE)
    return resp


@router.get("/me")
def me(user: Dict[str, Any] = Depends(get_current_user)):
    return user


@router.post("/logout")
def logout():
    resp = Response(content=json.dumps({"status": "success"}), media_type="application/json")
    resp.delete_cookie(SESSION_COOKIE)
    return resp


def _fetch_userinfo(creds) -> Dict[str, Any]:
    """Fetches the signed-in user's profile (email, name, picture) from Google."""
    from googleapiclient.discovery import build
    service = build("oauth2", "v2", credentials=creds)
    return service.userinfo().get().execute()
