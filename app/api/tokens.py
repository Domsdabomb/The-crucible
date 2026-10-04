"""
API token helpers — opaque bearer tokens for /api/v1.

Only the SHA-256 hash of a token is ever stored (api_tokens.token_hash);
the raw token is returned to the caller exactly once, at issue time, and
never again. Tokens carry an account_type ('staff' -> admins row,
'customer' -> customers row) because the two login systems are separate.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timezone

from app.db import get_db


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_token(account_type: str, account_id: int,
                name: str | None = None) -> str:
    """Create a token row and return the raw token (shown once)."""
    if account_type not in ("staff", "customer"):
        raise ValueError(f"Invalid account_type: {account_type!r}")
    token = secrets.token_urlsafe(32)
    db = get_db()
    db.execute(
        """
        INSERT INTO api_tokens (account_type, account_id, name, token_hash)
        VALUES (?, ?, ?, ?)
        """,
        (account_type, account_id, name, _hash_token(token)),
    )
    db.commit()
    return token


def revoke_token(token: str) -> bool:
    """Revoke a token. Returns True if a live token was revoked."""
    db = get_db()
    cur = db.execute(
        "UPDATE api_tokens SET revoked = 1 "
        "WHERE token_hash = ? AND revoked = 0",
        (_hash_token(token),),
    )
    db.commit()
    return cur.rowcount > 0


def verify_token(token: str):
    """Return the live token row for a presented token, or None.

    The lookup is by hash; the constant-time compare is defense-in-depth
    against hash-comparison timing oracles.
    """
    if not token:
        return None
    presented_hash = _hash_token(token)
    row = get_db().execute(
        "SELECT * FROM api_tokens WHERE token_hash = ? AND revoked = 0",
        (presented_hash,),
    ).fetchone()
    if row is None:
        return None
    if not hmac.compare_digest(row["token_hash"], presented_hash):
        return None
    return row


def touch_token(token_id: int) -> None:
    db = get_db()
    db.execute(
        "UPDATE api_tokens SET last_used_at = ? WHERE id = ?",
        (_now_iso(), token_id),
    )
    db.commit()
