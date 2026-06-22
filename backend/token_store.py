"""Encrypted, Supabase-backed storage for per-account Gmail OAuth credentials.

This module replaces the old `token_*.json` files on local disk. OAuth refresh
tokens grant full mailbox access, so they are NEVER written to disk and NEVER
stored in plaintext:

  * At rest they live in the Supabase ``gmail_accounts`` table, encrypted with
    Fernet (AES-128-CBC + HMAC) using the key in the ``TOKEN_ENC_KEY`` env var.
  * Even a full database dump is useless without that key, which is supplied
    only as a runtime secret (k8s Secret / .env), never committed.

If Supabase or the encryption key are not configured the store raises a clear
error rather than silently falling back to an insecure on-disk file.
"""

import os
import json
import logging
from typing import List, Optional

# OAuth scopes the agent needs. Kept here so every credential path agrees.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/spreadsheets",
]

_TABLE = "gmail_accounts"


class TokenStoreNotConfigured(RuntimeError):
    """Raised when Supabase or TOKEN_ENC_KEY are missing — never falls back to disk."""


def _get_fernet():
    """Builds a Fernet cipher from TOKEN_ENC_KEY, or raises if it is missing/invalid."""
    from cryptography.fernet import Fernet

    key = os.environ.get("TOKEN_ENC_KEY", "").strip()
    if not key:
        raise TokenStoreNotConfigured(
            "TOKEN_ENC_KEY is not set. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"` "
            "and add it to the environment."
        )
    try:
        return Fernet(key.encode("utf-8"))
    except Exception as e:
        raise TokenStoreNotConfigured(f"TOKEN_ENC_KEY is not a valid Fernet key: {e}")


def _get_supabase():
    """Returns an authenticated Supabase client, or raises if not configured."""
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    if not url or not key or key == "YOUR_SERVICE_ROLE_KEY_HERE":
        raise TokenStoreNotConfigured(
            "Supabase is not configured (SUPABASE_URL / SUPABASE_SERVICE_KEY). "
            "Gmail account credentials require Supabase to be reachable."
        )
    from supabase import create_client

    return create_client(url, key)


def is_configured() -> bool:
    """True when both Supabase and the encryption key are usable. Never raises."""
    try:
        _get_fernet()
        _get_supabase()
        return True
    except Exception:
        return False


def _encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def _decrypt(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def list_accounts() -> List[str]:
    """Returns the connected Gmail addresses. Empty list if the store is unconfigured."""
    try:
        sb = _get_supabase()
        resp = sb.table(_TABLE).select("email").order("created_at").execute()
        return [row["email"] for row in (resp.data or []) if row.get("email")]
    except TokenStoreNotConfigured:
        return []
    except Exception as e:
        logging.error(f"token_store.list_accounts failed: {e}")
        return []


def save_credentials(email: str, creds) -> None:
    """Encrypts and upserts a google.oauth2 Credentials object for ``email``."""
    if not email:
        raise ValueError("email is required to save credentials")
    sb = _get_supabase()
    encrypted = _encrypt(creds.to_json())
    sb.table(_TABLE).upsert(
        {"email": email, "encrypted_token": encrypted},
        on_conflict="email",
    ).execute()
    # NOTE: never log `encrypted` or the raw token — only the account label.
    logging.info(f"Stored encrypted Gmail credentials for {email}.")


def get_credentials(email: str):
    """Loads, decrypts and (if needed) refreshes the Credentials for ``email``.

    Refreshed tokens are written back to Supabase. Returns None if the account is
    unknown or its stored token cannot be decrypted/parsed.
    """
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    sb = _get_supabase()
    resp = sb.table(_TABLE).select("encrypted_token").eq("email", email).limit(1).execute()
    rows = resp.data or []
    if not rows:
        return None

    try:
        info = json.loads(_decrypt(rows[0]["encrypted_token"]))
    except Exception as e:
        logging.error(f"Failed to decrypt/parse stored token for {email}: {e}")
        return None

    creds = Credentials.from_authorized_user_info(info, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            save_credentials(email, creds)  # persist the rotated access token
        except Exception as e:
            logging.error(f"Token refresh failed for {email}: {e}")
            return None
    return creds


def delete_account(email: str) -> bool:
    """Removes the stored credentials for ``email``. Returns True if a row existed."""
    try:
        sb = _get_supabase()
    except TokenStoreNotConfigured:
        return False
    resp = sb.table(_TABLE).delete().eq("email", email).execute()
    deleted = bool(resp.data)
    if deleted:
        logging.info(f"Deleted stored Gmail credentials for {email}.")
    return deleted
