"""
JSON API v1 — The Crucible mobile backend.

Token-authenticated JSON endpoints under /api/v1 for the native mobile app.
Session/CSRF auth is NOT used here: every request (except /health and
/auth/login) carries `Authorization: Bearer <token>`.

Account model mirrors the two separate web login systems:
  - staff tokens  -> admins table (role admin|technician)
  - customer tokens -> customers table (portal accounts)

Role scoping mirrors the web UI exactly:
  - technicians see/update only jobs assigned to their own technicians row
  - invoices, customers, dashboard, and job intake are admin-only

All money is integer cents. Errors use one shape:
  {"error": {"code": "<machine_code>", "message": "<human message>"}}
"""

import functools
import sqlite3
from datetime import datetime, timezone

from flask import g, jsonify, request

from app.admin.routes import (
    ALLOWED_TRANSITIONS,
    VALID_PRIORITIES,
    VALID_STATUSES,
    _calc_tax,
    _job_filter_clause,
    _log_status_change,
    _validate_phone,
)
from app.api import api_bp
from app.api.tokens import issue_token, revoke_token, touch_token, verify_token
from app.db import get_db
from app.services.auth import (
    LOCKOUT_MINUTES,
    get_admin,
    is_locked as staff_is_locked,
    register_failed_login as staff_register_failed,
    register_successful_login as staff_register_success,
    verify_password,
)
from app.services.crypto import encrypt_passcode
from app.services.customer_auth import (
    get_customer_by_phone,
    is_locked as customer_is_locked,
    register_failed_login as customer_register_failed,
    register_successful_login as customer_register_success,
)
from app.services.rate_limit import rate_limit
from app.services.sms_service import sms_intake, sms_ready
from app.services.wallet import (
    calc_max_coins,
    get_or_create_wallet,
    reward_job_pickup,
    spend_coins,
)

API_VERSION = "1"


# ─────────────────────────────────────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────────────────────────────────────

def _api_error(code: str, message: str, status: int):
    """Every API error uses the same JSON shape."""
    return jsonify({"error": {"code": code, "message": message}}), status


@api_bp.errorhandler(404)
def _api_404(_e):
    return _api_error("not_found", "Not found.", 404)


@api_bp.errorhandler(405)
def _api_405(_e):
    return _api_error("method_not_allowed", "Method not allowed.", 405)


@api_bp.errorhandler(429)
def _api_429(_e):
    return _api_error(
        "rate_limited", "Too many requests. Please wait a bit and try again.", 429
    )


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────

def token_required(f):
    """Require a valid `Authorization: Bearer <token>` header.

    Sets g.api_account = {"type": "staff"|"customer", "id": ...} plus
    role/technician_id for staff or name/phone for customers.
    """
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return _api_error(
                "unauthorized",
                "Missing or invalid Authorization header. Use 'Bearer <token>'.",
                401,
            )
        row = verify_token(auth[7:].strip())
        if row is None:
            return _api_error("unauthorized", "Invalid or revoked token.", 401)

        db = get_db()
        touch_token(row["id"])

        account = {"type": row["account_type"], "id": row["account_id"]}
        if row["account_type"] == "staff":
            admin = db.execute(
                "SELECT id, username, role, technician_id FROM admins WHERE id = ?",
                (row["account_id"],),
            ).fetchone()
            if admin is None:
                return _api_error("unauthorized", "Account no longer exists.", 401)
            account.update(
                role=admin["role"],
                technician_id=admin["technician_id"],
                username=admin["username"],
            )
        else:
            customer = db.execute(
                "SELECT id, name, phone FROM customers WHERE id = ?",
                (row["account_id"],),
            ).fetchone()
            if customer is None:
                return _api_error("unauthorized", "Account no longer exists.", 401)
            account.update(name=customer["name"], phone=customer["phone"])

        g.api_account = account
        return f(*args, **kwargs)
    return wrapped


def _role_checked(kind: str):
    """Inner role gate — assumes token_required already ran."""
    def decorator(f):
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            acct = g.api_account
            if kind == "staff" and acct["type"] != "staff":
                return _api_error("forbidden", "Staff account required.", 403)
            if kind == "admin" and not (
                acct["type"] == "staff" and acct.get("role") == "admin"
            ):
                return _api_error("forbidden", "Admin account required.", 403)
            if kind == "customer" and acct["type"] != "customer":
                return _api_error("forbidden", "Customer account required.", 403)
            return f(*args, **kwargs)
        return token_required(wrapped)
    return decorator


def staff_required(f):
    """Any staff token (admin or technician)."""
    return _role_checked("staff")(f)


def admin_required_api(f):
    """Staff token with role=admin. Mirrors web @admin_required."""
    return _role_checked("admin")(f)


def customer_required(f):
    """Customer (portal) token only."""
    return _role_checked("customer")(f)


def _api_can_access_job(job_technician_id: int | None) -> bool:
    """Mirror of the web _can_access_job for token sessions."""
    acct = g.api_account
    if acct.get("role") == "admin":
        return True
    return (
        job_technician_id is not None
        and job_technician_id == acct.get("technician_id")
    )


def _scoped_tech_id_api(tech_id):
    """Technicians only ever see their own jobs — fail closed like the web."""
    if g.api_account.get("role") != "admin":
        return g.api_account.get("technician_id") or -1
    return tech_id


# ─────────────────────────────────────────────────────────────────────────────
# Serialization + pagination
# ─────────────────────────────────────────────────────────────────────────────

def _job_brief(row) -> dict:
    return {
        "id": row["id"],
        "status": row["status"],
        "priority": row["priority"],
        "created_at": row["created_at"],
        "promised_date": row["promised_date"],
        "total_cents": row["total_cents"],
        "customer": {
            "id": row["customer_id"],
            "name": row["customer_name"],
            "phone": row["customer_phone"],
        },
        "device": {"make": row["make"], "model": row["model"]},
        "technician": (
            {"id": row["technician_id"], "name": row["technician_name"]}
            if row["technician_id"] else None
        ),
    }


def _job_full(row, history: list) -> dict:
    d = _job_brief(row)
    d.update({
        "description": row["description"],
        "diagnosis_notes": row["diagnosis_notes"],
        "quoted_cents": row["quoted_cents"],
        "deposit_cents": row["deposit_cents"],
        "labour_cents": row["labour_cents"],
        "parts_cents": row["parts_cents"],
        "gst_cents": row["gst_cents"],
        "pst_cents": row["pst_cents"],
        "updated_at": row["updated_at"],
        "device": {
            "id": row["device_id"],
            "make": row["make"],
            "model": row["model"],
            "serial_imei": row["serial_imei"],
            "condition_notes": row["device_condition"],
        },
        "customer": {
            "id": row["customer_id"],
            "name": row["customer_name"],
            "phone": row["customer_phone"],
            "email": row["customer_email"],
        },
        "history": history,
    })
    return d


def _invoice_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "job_id": row["job_id"],
        "customer_id": row["customer_id"],
        "customer_name": row["customer_name"],
        "labour_cents": row["labour_cents"],
        "parts_cents": row["parts_cents"],
        "gst_cents": row["gst_cents"],
        "pst_cents": row["pst_cents"],
        "subtotal_cents": row["subtotal_cents"],
        "coins_applied": row["coins_applied"],
        "discount_cents": row["discount_cents"],
        "amount_due_cents": row["amount_due_cents"],
        "status": row["status"],
        "paid_at": row["paid_at"],
        "notes": row["notes"],
        "created_at": row["created_at"],
    }


def _customer_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "phone": row["phone"],
        "email": row["email"],
        "created_at": row["created_at"],
    }


def _pagination(default_per_page: int = 20):
    page = request.args.get("page", default=1, type=int) or 1
    per_page = request.args.get("per_page", default=default_per_page, type=int) or default_per_page
    page = max(1, page)
    per_page = max(1, min(per_page, 100))
    return page, per_page


def _paged(items: list, total: int, page: int, per_page: int):
    return jsonify({
        "data": items,
        "page": page,
        "per_page": per_page,
        "total": total,
    })


def _revenue_summary(db) -> dict:
    """Aggregate invoice revenue. Same query as the web admin dashboard."""
    row = db.execute(
        """
        SELECT
            SUM(CASE WHEN status = 'paid' THEN amount_due_cents ELSE 0 END)
                AS collected_cents,
            SUM(CASE WHEN status = 'paid'
                          AND paid_at >= strftime('%Y-%m-01T00:00:00.000Z', 'now')
                     THEN amount_due_cents ELSE 0 END)
                AS month_cents,
            SUM(CASE WHEN status = 'unpaid' THEN amount_due_cents ELSE 0 END)
                AS outstanding_cents,
            SUM(CASE WHEN status = 'unpaid' THEN 1 ELSE 0 END)
                AS unpaid_count
        FROM invoices
        """
    ).fetchone()
    return {k: (row[k] or 0) for k in row.keys()}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/health — no auth
# ─────────────────────────────────────────────────────────────────────────────

@api_bp.route("/health")
def health():
    return jsonify({"ok": True, "version": API_VERSION})


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/auth/login — staff (username) or customer (phone)
# ─────────────────────────────────────────────────────────────────────────────

@api_bp.route("/auth/login", methods=["POST"])
@rate_limit(max_requests=10, window_seconds=60)
def api_login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    phone = (data.get("phone") or "").strip()
    password = data.get("password") or ""
    device_name = (data.get("device_name") or "").strip() or None

    if username and not phone:
        # ── Staff login (mirrors /auth/login) ──────────────────────────────
        admin = get_admin(username)
        if admin and staff_is_locked(admin):
            return _api_error(
                "account_locked",
                f"Too many failed login attempts. Locked for {LOCKOUT_MINUTES} minutes.",
                423,
            )
        if admin and verify_password(password, admin["password_hash"]):
            staff_register_success(admin["id"])
            token = issue_token("staff", admin["id"], device_name)
            return jsonify({
                "token": token,
                "account_type": "staff",
                "role": admin["role"],
                "username": admin["username"],
            })
        if admin:
            staff_register_failed(admin["id"])
        return _api_error(
            "invalid_credentials", "Invalid username or password.", 401
        )

    if phone and not username:
        # ── Customer login (mirrors /portal/login) ─────────────────────────
        customer = get_customer_by_phone(phone)
        has_account = bool(customer and customer["password_hash"])
        if has_account and customer_is_locked(customer):
            return _api_error(
                "account_locked",
                f"Too many failed login attempts. Locked for {LOCKOUT_MINUTES} minutes.",
                423,
            )
        if has_account and verify_password(password, customer["password_hash"]):
            customer_register_success(customer["id"])
            token = issue_token("customer", customer["id"], device_name)
            return jsonify({
                "token": token,
                "account_type": "customer",
                "customer_id": customer["id"],
                "name": customer["name"],
            })
        if has_account:
            customer_register_failed(customer["id"])
        return _api_error(
            "invalid_credentials", "Invalid phone number or password.", 401
        )

    return _api_error(
        "validation_error",
        "Provide 'username' (staff) or 'phone' (customer), plus 'password'.",
        400,
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/auth/logout — revoke the current token
# ─────────────────────────────────────────────────────────────────────────────

@api_bp.route("/auth/logout", methods=["POST"])
@token_required
def api_logout():
    auth = request.headers.get("Authorization", "")
    revoke_token(auth[7:].strip())
    return jsonify({"success": True})


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/dashboard — admin only (mirrors web @admin_required)
# ─────────────────────────────────────────────────────────────────────────────

@api_bp.route("/dashboard")
@admin_required_api
def api_dashboard():
    db = get_db()

    status_counts = {
        row["status"]: row["cnt"]
        for row in db.execute(
            "SELECT status, COUNT(*) AS cnt FROM repair_jobs GROUP BY status"
        )
    }

    recent = db.execute(
        """
        SELECT rj.id, rj.status, rj.priority, rj.created_at, rj.promised_date,
               rj.total_cents, rj.customer_id, rj.technician_id,
               c.name AS customer_name, c.phone AS customer_phone,
               d.make, d.model, t.name AS technician_name
        FROM   repair_jobs rj
        JOIN   customers   c ON c.id = rj.customer_id
        JOIN   devices     d ON d.id = rj.device_id
        LEFT JOIN technicians t ON t.id = rj.technician_id
        ORDER  BY rj.created_at DESC
        LIMIT  10
        """
    ).fetchall()

    return jsonify({
        "revenue": _revenue_summary(db),
        "status_counts": status_counts,
        "recent_jobs": [_job_brief(r) for r in recent],
    })


# ─────────────────────────────────────────────────────────────────────────────
# Jobs — staff; technicians scoped to their own (mirrors web rules)
# ─────────────────────────────────────────────────────────────────────────────

_JOB_LIST_COLS = """
    rj.id, rj.status, rj.priority, rj.created_at, rj.promised_date,
    rj.total_cents, rj.customer_id, rj.technician_id,
    c.name AS customer_name, c.phone AS customer_phone,
    d.make, d.model, t.name AS technician_name
"""

_JOB_FROM = """
    FROM   repair_jobs rj
    JOIN   customers   c ON c.id = rj.customer_id
    JOIN   devices     d ON d.id = rj.device_id
    LEFT JOIN technicians t ON t.id = rj.technician_id
"""

_JOB_DETAIL_COLS = """
    rj.id, rj.status, rj.priority, rj.description, rj.diagnosis_notes,
    rj.quoted_cents, rj.deposit_cents, rj.labour_cents, rj.parts_cents,
    rj.gst_cents, rj.pst_cents, rj.total_cents,
    rj.created_at, rj.updated_at, rj.promised_date,
    rj.customer_id, rj.device_id, rj.technician_id,
    c.name AS customer_name, c.phone AS customer_phone, c.email AS customer_email,
    d.make, d.model, d.serial_imei, d.condition_notes AS device_condition,
    t.name AS technician_name
"""


def _get_job_or_error(job_id: int):
    """Fetch the full job row, or return (None, error_response)."""
    db = get_db()
    job = db.execute(
        f"SELECT {_JOB_DETAIL_COLS} {_JOB_FROM} WHERE rj.id = ?",
        (job_id,),
    ).fetchone()
    if job is None:
        return None, _api_error("not_found", f"Job {job_id} not found.", 404)
    if not _api_can_access_job(job["technician_id"]):
        return None, _api_error(
            "forbidden", "You can only access your own assigned jobs.", 403
        )
    return job, None


def _job_history(job_id: int) -> list:
    return [
        dict(h)
        for h in get_db().execute(
            "SELECT old_status, new_status, changed_by, note, changed_at "
            "FROM job_status_history WHERE job_id = ? ORDER BY changed_at",
            (job_id,),
        ).fetchall()
    ]


@api_bp.route("/jobs")
@staff_required
def api_job_list():
    db = get_db()
    page, per_page = _pagination()

    status = request.args.get("status")
    priority = request.args.get("priority")
    search = request.args.get("search", "").strip()
    tech_id = _scoped_tech_id_api(request.args.get("tech_id", type=int))
    where_clause, params = _job_filter_clause(
        status, priority, tech_id, None, None, search
    )

    total = db.execute(
        f"SELECT COUNT(*) AS cnt {_JOB_FROM} {where_clause}", params
    ).fetchone()["cnt"]

    rows = db.execute(
        f"SELECT {_JOB_LIST_COLS} {_JOB_FROM} {where_clause} "
        "ORDER BY rj.updated_at DESC LIMIT ? OFFSET ?",
        (*params, per_page, (page - 1) * per_page),
    ).fetchall()

    return _paged([_job_brief(r) for r in rows], total, page, per_page)


@api_bp.route("/jobs", methods=["POST"])
@admin_required_api
def api_job_create():
    """Intake — mirrors /admin/jobs/new. Upserts customer by phone, creates
    device + job in one transaction, seeds status history, fires intake SMS."""
    data = request.get_json(silent=True) or {}
    db = get_db()
    errors: list[str] = []

    customer_name = (data.get("customer_name") or "").strip()
    customer_phone = (data.get("customer_phone") or "").strip()
    customer_email = (data.get("customer_email") or "").strip() or None

    device_make = (data.get("device_make") or "").strip()
    device_model = (data.get("device_model") or "").strip()
    device_serial = (data.get("device_serial") or "").strip() or None
    device_passcode = (data.get("device_passcode") or "").strip() or None
    device_condition = (data.get("device_condition") or "").strip() or None

    description = (data.get("description") or "").strip() or None
    priority = (data.get("priority") or "normal").strip()
    technician_id = data.get("technician_id")
    promised_date = (data.get("promised_date") or "").strip() or None
    quoted_cents = data.get("quoted_cents", 0)

    if not customer_name:
        errors.append("customer_name is required.")
    try:
        customer_phone = _validate_phone(customer_phone)
    except ValueError as e:
        errors.append(str(e))
    if not device_make:
        errors.append("device_make is required.")
    if not device_model:
        errors.append("device_model is required.")
    if priority not in VALID_PRIORITIES:
        errors.append(f"Invalid priority: {priority!r}.")
    if not isinstance(quoted_cents, int) or quoted_cents < 0:
        errors.append("quoted_cents must be a non-negative integer.")
    if technician_id is not None:
        tech = db.execute(
            "SELECT id FROM technicians WHERE id = ?", (technician_id,)
        ).fetchone()
        if tech is None:
            errors.append(f"Technician {technician_id} not found.")

    if errors:
        return _api_error("validation_error", "; ".join(errors), 400)

    try:
        db.execute("BEGIN")

        existing = db.execute(
            "SELECT id FROM customers WHERE phone = ?", (customer_phone,)
        ).fetchone()
        if existing:
            customer_id = existing["id"]
            db.execute(
                "UPDATE customers SET name = ?, email = ? WHERE id = ?",
                (customer_name, customer_email, customer_id),
            )
        else:
            cur = db.execute(
                "INSERT INTO customers (name, phone, email) VALUES (?, ?, ?)",
                (customer_name, customer_phone, customer_email),
            )
            customer_id = cur.lastrowid

        cur = db.execute(
            """
            INSERT INTO devices
                (customer_id, make, model, serial_imei, passcode, condition_notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (customer_id, device_make, device_model, device_serial,
             encrypt_passcode(device_passcode), device_condition),
        )
        device_id = cur.lastrowid

        cur = db.execute(
            """
            INSERT INTO repair_jobs
                (device_id, customer_id, technician_id, status, priority,
                 description, quoted_cents, promised_date)
            VALUES (?, ?, ?, 'received', ?, ?, ?, ?)
            """,
            (device_id, customer_id, technician_id, priority,
             description, quoted_cents, promised_date),
        )
        job_id = cur.lastrowid

        _log_status_change(
            db, job_id, old_status=None, new_status="received",
            changed_by="intake", note="Job created via API.",
        )
        db.commit()

        sms_result = sms_intake(
            phone=customer_phone, customer_name=customer_name,
            job_id=job_id, customer_id=customer_id,
        )
    except sqlite3.IntegrityError as e:
        db.execute("ROLLBACK")
        return _api_error("conflict", f"Could not save job (data conflict): {e}", 409)
    except Exception:
        db.execute("ROLLBACK")
        raise

    job, err = _get_job_or_error(job_id)
    return jsonify({
        "job_id": job_id,
        "job": _job_full(job, _job_history(job_id)),
        "sms": sms_result,
    }), 201


@api_bp.route("/jobs/<int:job_id>")
@staff_required
def api_job_detail(job_id: int):
    job, err = _get_job_or_error(job_id)
    if err:
        return err
    return jsonify(_job_full(job, _job_history(job_id)))


@api_bp.route("/jobs/<int:job_id>", methods=["PATCH"])
@staff_required
def api_job_update(job_id: int):
    """Update a job. 'status' goes through the state machine (422 on illegal
    moves) and writes job_status_history; pricing fields recalc tax."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _api_error(
            "validation_error", "Request body must be a JSON object.", 400
        )

    job, err = _get_job_or_error(job_id)
    if err:
        return err

    db = get_db()
    is_admin = g.api_account.get("role") == "admin"
    errors: list[str] = []

    new_status = data.get("status")
    if new_status is not None:
        new_status = str(new_status).strip()
        if new_status not in VALID_STATUSES:
            errors.append(f"Invalid status: {new_status!r}.")
        elif new_status != job["status"] and new_status not in ALLOWED_TRANSITIONS.get(job["status"], set()):
            return _api_error(
                "invalid_transition",
                f"Transition '{job['status']}' → '{new_status}' is not permitted. "
                f"Allowed next states: {sorted(ALLOWED_TRANSITIONS.get(job['status'], set())) or 'none (terminal)'}.",
                422,
            )

    priority = data.get("priority")
    if priority is not None and priority not in VALID_PRIORITIES:
        errors.append(f"Invalid priority: {priority!r}.")

    technician_id = data.get("technician_id", "__unset__")
    if technician_id != "__unset__":
        if not is_admin:
            return _api_error(
                "forbidden", "Only admins can reassign technicians.", 403
            )
        if technician_id is not None and not db.execute(
            "SELECT id FROM technicians WHERE id = ?", (technician_id,)
        ).fetchone():
            errors.append(f"Technician {technician_id} not found.")

    money_fields = ("labour_cents", "parts_cents", "deposit_cents")
    money = {}
    for field in money_fields:
        if field in data:
            val = data[field]
            if not isinstance(val, int) or val < 0:
                errors.append(f"{field} must be a non-negative integer.")
            else:
                money[field] = val

    if errors:
        return _api_error("validation_error", "; ".join(errors), 400)

    updates: dict = {}
    for field in ("description", "diagnosis_notes", "promised_date"):
        if field in data:
            updates[field] = (str(data[field]).strip() or None) if data[field] is not None else None
    if priority is not None:
        updates["priority"] = priority
    if technician_id != "__unset__":
        updates["technician_id"] = technician_id
    updates.update(money)
    if money.get("labour_cents") is not None or money.get("parts_cents") is not None:
        labour = money.get("labour_cents", job["labour_cents"])
        parts = money.get("parts_cents", job["parts_cents"])
        gst, pst = _calc_tax(labour, parts)
        updates["gst_cents"] = gst
        updates["pst_cents"] = pst

    status_note = (data.get("note") or "").strip() or None
    changed_by = g.api_account.get("username", "api")
    old_status = job["status"]
    status_changing = new_status is not None and new_status != old_status

    try:
        db.execute("BEGIN")
        if updates:
            set_clause = ", ".join(f"{col} = ?" for col in updates)
            db.execute(
                f"UPDATE repair_jobs SET {set_clause} WHERE id = ?",
                (*updates.values(), job_id),
            )
        if status_changing:
            db.execute(
                "UPDATE repair_jobs SET status = ? WHERE id = ?",
                (new_status, job_id),
            )
            _log_status_change(
                db, job_id, old_status=old_status, new_status=new_status,
                changed_by=changed_by, note=status_note,
            )
        db.commit()

        # Side effects mirror the web flow (after commit).
        if status_changing and new_status == "ready":
            customer = db.execute(
                "SELECT name, phone FROM customers WHERE id = ?",
                (job["customer_id"],),
            ).fetchone()
            if customer:
                sms_ready(
                    phone=customer["phone"], customer_name=customer["name"],
                    job_id=job_id, customer_id=job["customer_id"],
                )
        elif status_changing and new_status == "picked_up":
            total = db.execute(
                "SELECT total_cents FROM repair_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            try:
                reward_job_pickup(
                    db, job["customer_id"], job_id,
                    total["total_cents"] if total else 0,
                )
                db.commit()
            except Exception:
                pass  # reward failure must not block the update
    except sqlite3.IntegrityError as e:
        db.execute("ROLLBACK")
        return _api_error("conflict", f"Could not save changes (data conflict): {e}", 409)
    except Exception:
        db.execute("ROLLBACK")
        raise

    job, err = _get_job_or_error(job_id)
    return jsonify(_job_full(job, _job_history(job_id)))


# ─────────────────────────────────────────────────────────────────────────────
# Invoices — admin only (mirrors web @admin_required)
# ─────────────────────────────────────────────────────────────────────────────

_INVOICE_COLS = """
    i.*, c.name AS customer_name
"""


@api_bp.route("/invoices")
@admin_required_api
def api_invoice_list():
    db = get_db()
    page, per_page = _pagination()

    total = db.execute("SELECT COUNT(*) AS cnt FROM invoices").fetchone()["cnt"]
    rows = db.execute(
        f"SELECT {_INVOICE_COLS} FROM invoices i "
        "JOIN customers c ON c.id = i.customer_id "
        "ORDER BY i.created_at DESC LIMIT ? OFFSET ?",
        (per_page, (page - 1) * per_page),
    ).fetchall()
    return _paged([_invoice_to_dict(r) for r in rows], total, page, per_page)


@api_bp.route("/invoices/<int:invoice_id>")
@admin_required_api
def api_invoice_detail(invoice_id: int):
    inv = get_db().execute(
        f"SELECT {_INVOICE_COLS} FROM invoices i "
        "JOIN customers c ON c.id = i.customer_id WHERE i.id = ?",
        (invoice_id,),
    ).fetchone()
    if inv is None:
        return _api_error("not_found", f"Invoice {invoice_id} not found.", 404)
    return jsonify(_invoice_to_dict(inv))


@api_bp.route("/invoices", methods=["POST"])
@admin_required_api
def api_invoice_create():
    """Create an invoice snapshotting a job's pricing. Mirrors
    /admin/jobs/<id>/invoice/new (POST)."""
    data = request.get_json(silent=True) or {}
    db = get_db()

    job_id = data.get("job_id")
    if not isinstance(job_id, int):
        return _api_error("validation_error", "job_id (integer) is required.", 400)
    coins_to_apply = data.get("coins_applied", 0)
    if not isinstance(coins_to_apply, int) or coins_to_apply < 0:
        return _api_error(
            "validation_error", "coins_applied must be a non-negative integer.", 400
        )
    notes = (data.get("notes") or "").strip() or None

    job = db.execute(
        "SELECT * FROM repair_jobs WHERE id = ?", (job_id,)
    ).fetchone()
    if job is None:
        return _api_error("not_found", f"Job {job_id} not found.", 404)
    job = dict(job)

    wallet = get_or_create_wallet(db, job["customer_id"])
    db.commit()  # persist wallet if just created (see invoice_new)
    max_coins = calc_max_coins(job["total_cents"], wallet["balance_coins"])
    if coins_to_apply > max_coins:
        return _api_error(
            "validation_error",
            f"At most {max_coins} coins can be applied to this invoice.",
            400,
        )

    try:
        db.execute("BEGIN")
        if coins_to_apply > 0:
            spend_coins(
                db, job["customer_id"], coins_to_apply,
                reason=f"Invoice for Job #{job_id} (API)", job_id=job_id,
            )
        cur = db.execute(
            """
            INSERT INTO invoices
                (job_id, customer_id, labour_cents, parts_cents, gst_cents, pst_cents,
                 coins_applied, discount_cents, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (job_id, job["customer_id"],
             job["labour_cents"], job["parts_cents"],
             job["gst_cents"], job["pst_cents"],
             coins_to_apply, coins_to_apply * 100, notes),
        )
        invoice_id = cur.lastrowid
        db.commit()
    except ValueError as e:
        db.execute("ROLLBACK")
        return _api_error("validation_error", str(e), 400)
    except sqlite3.IntegrityError as e:
        db.execute("ROLLBACK")
        return _api_error("conflict", f"Could not save invoice (data conflict): {e}", 409)
    except Exception:
        db.execute("ROLLBACK")
        raise

    inv = db.execute(
        f"SELECT {_INVOICE_COLS} FROM invoices i "
        "JOIN customers c ON c.id = i.customer_id WHERE i.id = ?",
        (invoice_id,),
    ).fetchone()
    return jsonify(_invoice_to_dict(inv)), 201


# ─────────────────────────────────────────────────────────────────────────────
# Customers — admin only (mirrors web @admin_required)
# ─────────────────────────────────────────────────────────────────────────────

@api_bp.route("/customers")
@admin_required_api
def api_customer_list():
    db = get_db()
    page, per_page = _pagination()
    search = request.args.get("search", "").strip()

    where, params = "", []
    if search:
        like = f"%{search}%"
        where = "WHERE c.name LIKE ? OR c.phone LIKE ? OR c.email LIKE ?"
        params = [like, like, like]

    total = db.execute(
        f"SELECT COUNT(*) AS cnt FROM customers c {where}", params
    ).fetchone()["cnt"]
    rows = db.execute(
        f"SELECT c.* FROM customers c {where} "
        "ORDER BY c.created_at DESC LIMIT ? OFFSET ?",
        (*params, per_page, (page - 1) * per_page),
    ).fetchall()
    return _paged([_customer_to_dict(r) for r in rows], total, page, per_page)


@api_bp.route("/customers/<int:customer_id>")
@admin_required_api
def api_customer_detail(customer_id: int):
    customer = get_db().execute(
        "SELECT * FROM customers WHERE id = ?", (customer_id,)
    ).fetchone()
    if customer is None:
        return _api_error(
            "not_found", f"Customer {customer_id} not found.", 404
        )
    return jsonify(_customer_to_dict(customer))


@api_bp.route("/customers", methods=["POST"])
@admin_required_api
def api_customer_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    phone_raw = (data.get("phone") or "").strip()
    email = (data.get("email") or "").strip() or None

    errors: list[str] = []
    if not name:
        errors.append("name is required.")
    try:
        phone = _validate_phone(phone_raw)
    except ValueError as e:
        errors.append(str(e))
    if errors:
        return _api_error("validation_error", "; ".join(errors), 400)

    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO customers (name, phone, email) VALUES (?, ?, ?)",
            (name, phone, email),
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.execute("ROLLBACK")
        return _api_error(
            "conflict", f"A customer with phone {phone} already exists.", 409
        )

    customer = db.execute(
        "SELECT * FROM customers WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return jsonify(_customer_to_dict(customer)), 201


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/portal/timeline — customer token only: own jobs + status history
# ─────────────────────────────────────────────────────────────────────────────

@api_bp.route("/portal/timeline")
@customer_required
def api_portal_timeline():
    db = get_db()
    customer_id = g.api_account["id"]

    jobs = db.execute(
        """
        SELECT rj.id, rj.status, rj.priority, rj.created_at, rj.promised_date,
               rj.total_cents, d.make, d.model
        FROM   repair_jobs rj
        JOIN   devices     d ON d.id = rj.device_id
        WHERE  rj.customer_id = ?
        ORDER  BY rj.created_at DESC
        """,
        (customer_id,),
    ).fetchall()

    result = []
    for j in jobs:
        history = db.execute(
            """
            SELECT old_status, new_status, changed_by, note, changed_at
            FROM   job_status_history
            WHERE  job_id = ?
            ORDER  BY changed_at
            """,
            (j["id"],),
        ).fetchall()
        result.append({
            "id": j["id"],
            "status": j["status"],
            "priority": j["priority"],
            "created_at": j["created_at"],
            "promised_date": j["promised_date"],
            "total_cents": j["total_cents"],
            "device": {"make": j["make"], "model": j["model"]},
            "history": [dict(h) for h in history],
        })

    return jsonify({"jobs": result, "count": len(result)})
