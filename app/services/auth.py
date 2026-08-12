"""
Auth helpers — password hashing, login_required decorator, and
failed-login lockout tracking.
"""

import functools

from flask import session, redirect, url_for, flash, request
from datetime import datetime, timedelta, timezone

from flask import abort, session, redirect, url_for, flash, request
from werkzeug.security import generate_password_hash, check_password_hash

from app.db import get_db

MAX_FAILED_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def hash_password(password: str) -> str:
    """Return a salted PBKDF2-SHA256 hash (werkzeug's default method)."""
    return generate_password_hash(password)


def verify_password(password: str, stored: str) -> bool:
    return check_password_hash(stored, password)


def get_admin(username: str):
    return get_db().execute(
        "SELECT * FROM admins WHERE username = ?", (username,)
    ).fetchone()


def admin_exists() -> bool:
    return get_db().execute("SELECT COUNT(*) FROM admins").fetchone()[0] > 0


def create_admin(username: str, password: str, role: str = "admin",
                  technician_id: int | None = None) -> None:
    db = get_db()
    db.execute(
        "INSERT INTO admins (username, password_hash, role, technician_id) "
        "VALUES (?, ?, ?, ?)",
        (username, hash_password(password), role, technician_id),
    )
    db.commit()


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def is_locked(admin) -> bool:
    """True if this admin row is currently under a failed-login lockout.

    locked_until is an ISO-8601 UTC string, so it sorts the same
    lexicographically as it does chronologically — no parsing needed.
    """
    locked_until = admin["locked_until"]
    return bool(locked_until) and locked_until > _iso_now()


def register_failed_login(admin_id: int) -> None:
    """Increment the failed-attempt counter; lock the account once the
    threshold is hit."""
    db = get_db()
    db.execute("BEGIN")
    attempts = db.execute(
        "SELECT failed_attempts FROM admins WHERE id = ?", (admin_id,)
    ).fetchone()["failed_attempts"] + 1

    if attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
        locked_until = (
            datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)
        ).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        db.execute(
            "UPDATE admins SET failed_attempts = 0, locked_until = ? WHERE id = ?",
            (locked_until, admin_id),
        )
    else:
        db.execute(
            "UPDATE admins SET failed_attempts = ? WHERE id = ?",
            (attempts, admin_id),
        )
    db.commit()


def register_successful_login(admin_id: int) -> None:
    """Clear any lockout state on a successful login."""
    db = get_db()
    db.execute("BEGIN")
    db.execute(
        "UPDATE admins SET failed_attempts = 0, locked_until = NULL WHERE id = ?",
        (admin_id,),
    )
    db.commit()


def login_required(f):
    """Decorator: redirect to /login if no active session."""
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        if "admin_id" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)
    return wrapped


def admin_required(f):
    """Decorator: like login_required, but 403s technician-role accounts.

    Use on routes that touch customer financials, invoices, wallets, or
    other accounts — anything outside "view/update jobs assigned to me".
    """
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        if "admin_id" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("auth.login", next=request.path))
        if session.get("admin_role") != "admin":
            abort(403)
        return f(*args, **kwargs)
    return wrapped
