"""
Customer portal — public sign-up/login plus an authenticated area where
customers can view their repair history, Crucible Coin balance, and submit
new repair requests online.

Kept entirely separate from app/auth (admin/technician staff login): separate
session key (session["customer_id"]), separate password column
(customers.password_hash), separate decorator. A customer session can never
grant admin access and vice versa.
"""

import re
from datetime import datetime, timezone

from flask import flash, redirect, render_template, request, session, url_for

from app.db import get_db
from app.services.crypto import encrypt_passcode
from app.services.customer_auth import (
    LOCKOUT_MINUTES,
    customer_login_required,
    get_customer_by_id,
    get_customer_by_phone,
    hash_password,
    is_locked,
    register_failed_login,
    register_successful_login,
    verify_password,
)
from app.services.rate_limit import rate_limit
from app.services.sms_service import sms_intake
from app.services.wallet import COIN_VALUE_CENTS, get_or_create_wallet
from . import portal_bp

E164_RE = re.compile(r"^\+1[2-9]\d{9}$")  # Canadian numbers only, matches app/admin/routes.py


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _validate_phone(phone: str) -> str:
    phone = phone.strip()
    if not E164_RE.match(phone):
        raise ValueError(
            f"Phone must be a Canadian E.164 number (e.g. +12505550100), got: {phone!r}"
        )
    return phone


def _start_session(customer) -> None:
    session["customer_id"] = customer["id"]
    session["customer_name"] = customer["name"]


# ─────────────────────────────────────────────────────────────────────────────
# GET/POST /portal/signup
# ─────────────────────────────────────────────────────────────────────────────

@portal_bp.route("/signup", methods=["GET", "POST"])
@rate_limit(max_requests=10, window_seconds=60)
def signup():
    if "customer_id" in session:
        return redirect(url_for("portal.dashboard"))

    if request.method == "GET":
        return render_template("portal/signup.html", errors=[], form={})

    db = get_db()
    errors: list[str] = []

    name = (request.form.get("name") or "").strip()
    phone_raw = (request.form.get("phone") or "").strip()
    email = (request.form.get("email") or "").strip() or None
    password = request.form.get("password", "")
    confirm = request.form.get("confirm", "")
    ticket_raw = (request.form.get("ticket") or "").strip().lstrip("#")

    phone = phone_raw
    try:
        phone = _validate_phone(phone_raw)
    except ValueError as e:
        errors.append(str(e))

    if len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    if password != confirm:
        errors.append("Passwords do not match.")

    existing = None
    if not errors:
        existing = get_customer_by_phone(phone)
        if existing and existing["password_hash"]:
            errors.append(
                "An account already exists for this phone number. Log in instead."
            )
        elif existing:
            # Claiming a record staff already created at intake — require proof
            # of ownership via a real ticket number, the same two-factor bar
            # /track uses. A phone number alone isn't secret enough to hand
            # over someone else's repair history and coin balance.
            if not ticket_raw.isdigit():
                errors.append(
                    "This phone number already has repair history on file. "
                    "Enter one of your ticket numbers (from your receipt) to verify it's you."
                )
            else:
                job = db.execute(
                    "SELECT id FROM repair_jobs WHERE id = ? AND customer_id = ?",
                    (int(ticket_raw), existing["id"]),
                ).fetchone()
                if job is None:
                    errors.append(
                        "That ticket number doesn't match this phone number's repair history."
                    )
        elif not name:
            errors.append("Name is required.")

    if errors:
        return render_template("portal/signup.html", errors=errors, form=request.form), 400

    if existing:
        db.execute(
            "UPDATE customers SET password_hash = ? WHERE id = ?",
            (hash_password(password), existing["id"]),
        )
        db.commit()
        customer = get_customer_by_id(existing["id"])
    else:
        cur = db.execute(
            "INSERT INTO customers (name, phone, email, password_hash) VALUES (?, ?, ?, ?)",
            (name, phone, email, hash_password(password)),
        )
        db.commit()
        customer = get_customer_by_id(cur.lastrowid)

    _start_session(customer)
    flash(f"Welcome, {customer['name']}! Your account is ready.", "success")
    return redirect(url_for("portal.dashboard"))


# ─────────────────────────────────────────────────────────────────────────────
# GET/POST /portal/login
# ─────────────────────────────────────────────────────────────────────────────

@portal_bp.route("/login", methods=["GET", "POST"])
@rate_limit(max_requests=10, window_seconds=60)
def login():
    if "customer_id" in session:
        return redirect(url_for("portal.dashboard"))

    if request.method == "POST":
        phone = (request.form.get("phone") or "").strip()
        password = request.form.get("password", "")
        customer = get_customer_by_phone(phone)
        has_account = bool(customer and customer["password_hash"])

        if has_account and is_locked(customer):
            flash(
                f"Too many failed login attempts. This account is locked "
                f"for {LOCKOUT_MINUTES} minutes.",
                "error",
            )
        elif has_account and verify_password(password, customer["password_hash"]):
            register_successful_login(customer["id"])
            _start_session(customer)
            flash(f"Welcome back, {customer['name']}.", "success")
            return redirect(request.args.get("next") or url_for("portal.dashboard"))
        else:
            if has_account:
                register_failed_login(customer["id"])
            flash("Invalid phone number or password.", "error")

    return render_template("portal/login.html")


@portal_bp.route("/logout")
def logout():
    session.pop("customer_id", None)
    session.pop("customer_name", None)
    flash("Logged out.", "success")
    return redirect(url_for("portal.login"))


# ─────────────────────────────────────────────────────────────────────────────
# GET /portal/  — Dashboard: repair history + wallet balance
# ─────────────────────────────────────────────────────────────────────────────

@portal_bp.route("/")
@customer_login_required
def dashboard():
    db = get_db()
    customer = get_customer_by_id(session["customer_id"])

    wallet = get_or_create_wallet(db, customer["id"])
    db.commit()  # persist wallet if this just created it

    jobs = db.execute(
        """
        SELECT rj.id, rj.status, rj.promised_date, rj.created_at, d.make, d.model
        FROM   repair_jobs rj
        JOIN   devices     d ON d.id = rj.device_id
        WHERE  rj.customer_id = ?
        ORDER  BY rj.created_at DESC
        """,
        (customer["id"],),
    ).fetchall()

    return render_template(
        "portal/dashboard.html",
        customer=dict(customer),
        wallet=wallet,
        jobs=[dict(j) for j in jobs],
        COIN_VALUE_CENTS=COIN_VALUE_CENTS,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET/POST /portal/jobs/new  — Customer-initiated repair request
# ─────────────────────────────────────────────────────────────────────────────

@portal_bp.route("/jobs/new", methods=["GET", "POST"])
@customer_login_required
def job_new():
    if request.method == "GET":
        return render_template("portal/job_new.html", errors=[], form={})

    db = get_db()
    customer = get_customer_by_id(session["customer_id"])
    errors: list[str] = []

    device_make = (request.form.get("device_make") or "").strip()
    device_model = (request.form.get("device_model") or "").strip()
    device_serial = (request.form.get("device_serial") or "").strip() or None
    device_passcode = (request.form.get("device_passcode") or "").strip() or None
    device_condition = (request.form.get("device_condition") or "").strip() or None
    description = (request.form.get("description") or "").strip() or None

    if not device_make:
        errors.append("Device make is required.")
    if not device_model:
        errors.append("Device model is required.")

    if errors:
        return render_template("portal/job_new.html", errors=errors, form=request.form), 400

    # customer_id/phone come from the session, never the form — a logged-in
    # customer can only ever create jobs against their own record.
    try:
        db.execute("BEGIN")

        cur = db.execute(
            """
            INSERT INTO devices
                (customer_id, make, model, serial_imei, passcode, condition_notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (customer["id"], device_make, device_model, device_serial,
             encrypt_passcode(device_passcode), device_condition),
        )
        device_id = cur.lastrowid

        cur = db.execute(
            """
            INSERT INTO repair_jobs (device_id, customer_id, status, priority, description)
            VALUES (?, ?, 'received', 'normal', ?)
            """,
            (device_id, customer["id"], description),
        )
        job_id = cur.lastrowid

        db.execute(
            """
            INSERT INTO job_status_history
                (job_id, old_status, new_status, changed_by, note, changed_at)
            VALUES (?, NULL, 'received', ?, ?, ?)
            """,
            (job_id, "customer portal", "Submitted via online portal.", _now_iso()),
        )

        db.commit()

        sms_intake(
            phone=customer["phone"],
            customer_name=customer["name"],
            job_id=job_id,
            customer_id=customer["id"],
        )
    except Exception:
        db.execute("ROLLBACK")
        raise

    flash("Repair request submitted! We'll be in touch shortly.", "success")
    return redirect(url_for("portal.dashboard"))
