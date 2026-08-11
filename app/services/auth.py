"""
Auth helpers — password hashing and the login_required decorator.
"""

import functools

from flask import session, redirect, url_for, flash, request
from werkzeug.security import generate_password_hash, check_password_hash

from app.db import get_db


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


def create_admin(username: str, password: str) -> None:
    db = get_db()
    db.execute(
        "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
        (username, hash_password(password)),
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
