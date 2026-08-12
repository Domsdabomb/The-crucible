"""
Customer portal auth — separate from app/services/auth.py (admin/technician
staff logins) on purpose. Customer sessions use session["customer_id"], never
session["admin_id"], so the two account systems can never be confused with
each other or grant each other's access.
"""

import functools
from datetime import datetime, timedelta, timezone

from flask import flash, redirect, request, session, url_for

from app.db import get_db
from app.services.auth import hash_password, verify_password  # noqa: F401 (re-exported)

MAX_FAILED_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def get_customer_by_phone(phone: str):
    return get_db().execute(
        "SELECT * FROM customers WHERE phone = ?", (phone,)
    ).fetchone()


def get_customer_by_id(customer_id: int):
    return get_db().execute(
        "SELECT * FROM customers WHERE id = ?", (customer_id,)
    ).fetchone()


def is_locked(customer) -> bool:
    locked_until = customer["locked_until"]
    return bool(locked_until) and locked_until > _iso_now()


def register_failed_login(customer_id: int) -> None:
    db = get_db()
    db.execute("BEGIN")
    attempts = db.execute(
        "SELECT failed_attempts FROM customers WHERE id = ?", (customer_id,)
    ).fetchone()["failed_attempts"] + 1

    if attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
        locked_until = (
            datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)
        ).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        db.execute(
            "UPDATE customers SET failed_attempts = 0, locked_until = ? WHERE id = ?",
            (locked_until, customer_id),
        )
    else:
        db.execute(
            "UPDATE customers SET failed_attempts = ? WHERE id = ?",
            (attempts, customer_id),
        )
    db.commit()


def register_successful_login(customer_id: int) -> None:
    db = get_db()
    db.execute("BEGIN")
    db.execute(
        "UPDATE customers SET failed_attempts = 0, locked_until = NULL WHERE id = ?",
        (customer_id,),
    )
    db.commit()


def customer_login_required(f):
    """Decorator: redirect to the portal login if no active customer session."""
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        if "customer_id" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("portal.login", next=request.path))
        return f(*args, **kwargs)
    return wrapped
