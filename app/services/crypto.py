"""
Symmetric encryption for sensitive at-rest fields (currently: device passcodes).

Key resolution order:
  1. PASSCODE_ENCRYPTION_KEY env var — a urlsafe-base64 32-byte Fernet key.
     Required in production; generate one with:
         python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  2. instance/passcode.key — auto-generated on first use if the env var isn't
     set, so local dev works with zero setup. This file lives in the
     gitignored instance/ folder; losing it means existing encrypted
     passcodes become unrecoverable, which is fine for dev but not for prod.
"""

import os

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


def _load_or_create_key() -> bytes:
    env_key = os.environ.get("PASSCODE_ENCRYPTION_KEY")
    if env_key:
        return env_key.encode()

    key_path = os.path.join(current_app.instance_path, "passcode.key")
    if os.path.exists(key_path):
        with open(key_path, "rb") as f:
            return f.read().strip()

    os.makedirs(current_app.instance_path, exist_ok=True)
    key = Fernet.generate_key()
    try:
        # O_EXCL makes creation atomic across processes: only one worker can
        # win this race, so multiple gunicorn workers can't each generate and
        # write a different key on first request.
        fd = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        with open(key_path, "rb") as f:
            return f.read().strip()
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key


def _fernet() -> Fernet:
    if "_fernet" not in current_app.extensions:
        current_app.extensions["_fernet"] = Fernet(_load_or_create_key())
    return current_app.extensions["_fernet"]


def encrypt_passcode(plaintext: str | None) -> str | None:
    if not plaintext:
        return None
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_passcode(ciphertext: str | None) -> str | None:
    """Decrypt a stored passcode. Falls back to returning the raw value if it
    isn't a valid Fernet token (e.g. plaintext left over from before this was
    added), rather than erroring out the whole page."""
    if not ciphertext:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError):
        return ciphertext
