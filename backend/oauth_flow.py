"""Google OAuth 2.0 *Web Application* flow, configured entirely from env vars.

Replaces the old desktop `InstalledAppFlow` + `credentials.json` +
`run_local_server` approach, which cannot work inside a container. The OAuth
client is built from:

    GOOGLE_CLIENT_ID
    GOOGLE_CLIENT_SECRET
    OAUTH_REDIRECT_URI   (must exactly match an Authorized redirect URI in the
                          Google Cloud console, e.g. https://app/api/auth/callback)
"""

import os

from token_store import SCOPES

# google-auth-oauthlib raises if the scopes Google echoes back differ even
# cosmetically from what we requested. This relaxes only that client-side check;
# the scopes actually granted are still governed by Google and user consent.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")


def is_configured() -> bool:
    """True when the OAuth client env vars are present."""
    return all(
        os.environ.get(k, "").strip()
        for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "OAUTH_REDIRECT_URI")
    )


def _client_config() -> dict:
    return {
        "web": {
            "client_id": os.environ["GOOGLE_CLIENT_ID"].strip(),
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"].strip(),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [os.environ["OAUTH_REDIRECT_URI"].strip()],
        }
    }


def build_flow(state: str | None = None):
    """Builds a configured google_auth_oauthlib Flow bound to OAUTH_REDIRECT_URI."""
    from google_auth_oauthlib.flow import Flow

    return Flow.from_client_config(
        _client_config(),
        scopes=SCOPES,
        state=state,
        redirect_uri=os.environ["OAUTH_REDIRECT_URI"].strip(),
    )


def redirect_uri() -> str:
    return os.environ.get("OAUTH_REDIRECT_URI", "").strip()
