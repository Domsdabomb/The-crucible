"""
Admin blueprint routes — The Crucible tech-repair shop backend.

All monetary values are stored as integer cents; the UI layer is responsible
for formatting (e.g. 1050 → "$10.50").

BC tax rates applied server-side:
    GST = 5%  of (labour + parts)
    PST = 7%  of (labour + parts)
"""

import re
from datetime import datetime, timezone

from flask import (
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from app.db import get_db
from app.services.auth import login_required
from app.services.sms_service import sms_intake, sms_ready, send_sms
from app.services.wallet import (
    add_coins, calc_max_coins, get_or_create_wallet,
    reward_job_pickup, spend_coins, COIN_VALUE_CENTS,
)
from . import admin_bp

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

VALID_STATUSES = (
    "received", "diagnosed", "awaiting_parts", "in_repair",
    "quality_check", "ready", "picked_up", "cancelled",
    "warranty_return", "closed",
)

VALID_PRIORITIES = ("low", "normal", "high", "urgent")

# Allowed forward and backward transitions. None in a set means "any previous".
# Format: current_status → set of statuses it may move to.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "received":       {"diagnosed", "cancelled"},
    "diagnosed":      {"awaiting_parts", "in_repair", "cancelled"},
    "awaiting_parts": {"in_repair", "cancelled"},
    "in_repair":      {"quality_check", "awaiting_parts", "cancelled"},
    "quality_check":  {"ready", "in_repair"},
    "ready":          {"picked_up", "warranty_return"},
    "picked_up":      {"warranty_return", "closed"},
    "cancelled":      {"received"},              # allow re-open
    "warranty_return": {"in_repair", "closed"},
    "closed":         set(),                     # terminal
}

# GST / PST (BC) applied to labour + parts
GST_RATE = 0.05
PST_RATE = 0.07

E164_RE = re.compile(r"^\+1[2-9]\d{9}$")  # Canadian numbers only


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _calc_tax(labour_cents: int, parts_cents: int) -> tuple[int, int]:
    """Return (gst_cents, pst_cents) rounded to nearest cent."""
    taxable = labour_cents + parts_cents
    return round(taxable * GST_RATE), round(taxable * PST_RATE)


def _job_row_to_dict(row) -> dict:
    return dict(row)


def _wants_json() -> bool:
    best = request.accept_mimetypes.best_match(
        ["application/json", "text/html"]
    )
    return best == "application/json"


def _log_status_change(db, job_id: int, old_status: str | None,
                       new_status: str, changed_by: str,
                       note: str | None = None) -> None:
    db.execute(
        """
        INSERT INTO job_status_history
            (job_id, old_status, new_status, changed_by, note, changed_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (job_id, old_status, new_status, changed_by, note, _now_iso()),
    )


def _validate_phone(phone: str) -> str:
    """Raise ValueError if not a valid Canadian E.164 number."""
    phone = phone.strip()
    if not E164_RE.match(phone):
        raise ValueError(
            f"Phone must be a Canadian E.164 number (e.g. +12505550100), got: {phone!r}"
        )
    return phone


# ─────────────────────────────────────────────────────────────────────────────
# GET /admin/  — Dashboard
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/")
@login_required
def dashboard():
    db = get_db()

    # Pipeline counts by status
    status_counts = {
        row["status"]: row["cnt"]
        for row in db.execute(
            "SELECT status, COUNT(*) AS cnt FROM repair_jobs GROUP BY status"
        )
    }

    # Overdue: promised_date < today and not in a terminal/pickup state
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    overdue = db.execute(
        """
        SELECT rj.*, c.name AS customer_name, c.phone AS customer_phone,
               d.make, d.model
        FROM   repair_jobs rj
        JOIN   customers   c ON c.id = rj.customer_id
        JOIN   devices     d ON d.id = rj.device_id
        WHERE  rj.promised_date < ?
          AND  rj.status NOT IN ('picked_up', 'cancelled', 'closed')
        ORDER  BY rj.promised_date ASC
        """,
        (today,),
    ).fetchall()

    # Active jobs sorted by priority then age
    priority_order = "CASE rj.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END"
    active_feed = db.execute(
        f"""
        SELECT rj.*, c.name AS customer_name, d.make, d.model,
               t.name AS technician_name
        FROM   repair_jobs rj
        JOIN   customers   c ON c.id = rj.customer_id
        JOIN   devices     d ON d.id = rj.device_id
        LEFT JOIN technicians t ON t.id = rj.technician_id
        WHERE  rj.status NOT IN ('picked_up', 'cancelled', 'closed')
        ORDER  BY {priority_order}, rj.created_at ASC
        """,
    ).fetchall()

    ctx = {
        "status_counts": status_counts,
        "overdue":        [dict(r) for r in overdue],
        "active_feed":    [dict(r) for r in active_feed],
        "all_statuses":   VALID_STATUSES,
    }

    if _wants_json():
        return jsonify(ctx)
    return render_template("admin/dashboard.html", **ctx)


# ─────────────────────────────────────────────────────────────────────────────
# GET /admin/jobs  — Filterable job list
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/jobs")
@login_required
def job_list():
    db = get_db()

    status    = request.args.get("status")
    priority  = request.args.get("priority")
    tech_id   = request.args.get("tech_id", type=int)
    date_from = request.args.get("date_from")
    date_to   = request.args.get("date_to")
    search    = request.args.get("search", "").strip()

    conditions = []
    params: list = []

    if status and status in VALID_STATUSES:
        conditions.append("rj.status = ?")
        params.append(status)

    if priority and priority in VALID_PRIORITIES:
        conditions.append("rj.priority = ?")
        params.append(priority)

    if tech_id:
        conditions.append("rj.technician_id = ?")
        params.append(tech_id)

    if date_from:
        conditions.append("date(rj.created_at) >= ?")
        params.append(date_from)

    if date_to:
        conditions.append("date(rj.created_at) <= ?")
        params.append(date_to)

    if search:
        like = f"%{search}%"
        conditions.append(
            "(c.name LIKE ? OR c.phone LIKE ? OR d.make LIKE ? OR d.model LIKE ? "
            "OR d.serial_imei LIKE ? OR CAST(rj.id AS TEXT) LIKE ?)"
        )
        params.extend([like, like, like, like, like, like])

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    priority_order = (
        "CASE rj.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 "
        "WHEN 'normal' THEN 2 ELSE 3 END"
    )

    rows = db.execute(
        f"""
        SELECT rj.*,
               c.name  AS customer_name, c.phone AS customer_phone,
               d.make, d.model, d.serial_imei,
               t.name  AS technician_name
        FROM   repair_jobs rj
        JOIN   customers   c ON c.id = rj.customer_id
        JOIN   devices     d ON d.id = rj.device_id
        LEFT JOIN technicians t ON t.id = rj.technician_id
        {where_clause}
        ORDER  BY {priority_order}, rj.updated_at DESC
        """,
        params,
    ).fetchall()

    jobs = [dict(r) for r in rows]
    technicians = db.execute(
        "SELECT id, name FROM technicians WHERE active = 1 ORDER BY name"
    ).fetchall()

    if _wants_json():
        return jsonify({"jobs": jobs, "count": len(jobs)})

    return render_template(
        "admin/job_list.html",
        jobs=jobs,
        technicians=[dict(t) for t in technicians],
        filters={
            "status": status, "priority": priority, "tech_id": tech_id,
            "date_from": date_from, "date_to": date_to, "search": search,
        },
        all_statuses=VALID_STATUSES,
        all_priorities=VALID_PRIORITIES,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /admin/jobs/<id>  — Full ticket view
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/jobs/<int:job_id>")
@login_required
def job_detail(job_id: int):
    db = get_db()

    job = db.execute(
        """
        SELECT rj.*,
               c.name  AS customer_name, c.phone AS customer_phone, c.email AS customer_email,
               d.make, d.model, d.serial_imei, d.passcode, d.condition_notes AS device_condition,
               t.name  AS technician_name
        FROM   repair_jobs rj
        JOIN   customers   c ON c.id = rj.customer_id
        JOIN   devices     d ON d.id = rj.device_id
        LEFT JOIN technicians t ON t.id = rj.technician_id
        WHERE  rj.id = ?
        """,
        (job_id,),
    ).fetchone()

    if job is None:
        abort(404)

    parts = db.execute(
        "SELECT * FROM parts WHERE job_id = ? ORDER BY created_at",
        (job_id,),
    ).fetchall()

    history = db.execute(
        "SELECT * FROM job_status_history WHERE job_id = ? ORDER BY changed_at",
        (job_id,),
    ).fetchall()

    sms_logs = db.execute(
        "SELECT * FROM sms_log WHERE job_id = ? ORDER BY sent_at DESC",
        (job_id,),
    ).fetchall()

    technicians = db.execute(
        "SELECT id, name FROM technicians WHERE active = 1 ORDER BY name"
    ).fetchall()

    ctx = {
        "job":         dict(job),
        "parts":       [dict(p) for p in parts],
        "history":     [dict(h) for h in history],
        "sms_logs":    [dict(s) for s in sms_logs],
        "technicians": [dict(t) for t in technicians],
        "allowed_transitions": sorted(ALLOWED_TRANSITIONS.get(job["status"], [])),
    }

    if _wants_json():
        return jsonify(ctx)

    return render_template("admin/job_detail.html", **ctx)


# ─────────────────────────────────────────────────────────────────────────────
# POST /admin/jobs/<id>/status  — State transition
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/jobs/<int:job_id>/status", methods=["POST"])
@login_required
def job_update_status(job_id: int):
    db = get_db()

    job = db.execute(
        "SELECT id, status, customer_id FROM repair_jobs WHERE id = ?",
        (job_id,),
    ).fetchone()

    if job is None:
        abort(404)

    new_status  = (request.form.get("status") or "").strip()
    changed_by  = (request.form.get("changed_by") or "admin").strip()
    note        = (request.form.get("note") or "").strip() or None

    if new_status not in VALID_STATUSES:
        abort(400, f"Invalid status: {new_status!r}")

    old_status = job["status"]

    # ── Guard: block illegal transitions ─────────────────────────────────────
    allowed = ALLOWED_TRANSITIONS.get(old_status, set())
    if new_status not in allowed:
        msg = (
            f"Transition '{old_status}' → '{new_status}' is not permitted. "
            f"Allowed next states: {sorted(allowed) or 'none (terminal)'}"
        )
        if _wants_json():
            return jsonify({"error": msg}), 422
        abort(422, msg)

    try:
        db.execute("BEGIN")

        db.execute(
            "UPDATE repair_jobs SET status = ? WHERE id = ?",
            (new_status, job_id),
        )

        _log_status_change(
            db, job_id, old_status=old_status,
            new_status=new_status, changed_by=changed_by, note=note,
        )

        # ── Auto-fire SMS when job becomes ready ─────────────────────────────
        # ── Reward coins when job is picked up ───────────────────────────────
        sms_result = None
        if new_status == "ready":
            customer = db.execute(
                "SELECT name, phone FROM customers WHERE id = ?",
                (job["customer_id"],),
            ).fetchone()
            if customer:
                db.commit()
                sms_result = sms_ready(
                    phone=customer["phone"],
                    customer_name=customer["name"],
                    job_id=job_id,
                    customer_id=job["customer_id"],
                )
            else:
                db.commit()
        elif new_status == "picked_up":
            job_full = db.execute(
                "SELECT total_cents FROM repair_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            total_cents = job_full["total_cents"] if job_full else 0
            db.commit()
            try:
                reward_job_pickup(db, job["customer_id"], job_id, total_cents)
                db.commit()
            except Exception:
                pass  # reward failure should not block the status update
        else:
            db.commit()

    except Exception:
        db.execute("ROLLBACK")
        raise

    if _wants_json():
        resp: dict = {"success": True, "new_status": new_status}
        if sms_result:
            resp["sms"] = sms_result
        return jsonify(resp)

    return redirect(url_for("admin.job_detail", job_id=job_id))


# ─────────────────────────────────────────────────────────────────────────────
# POST /admin/jobs/new  — Intake: upsert customer, create device + job
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/jobs/new", methods=["GET", "POST"])
@login_required
def job_new():
    if request.method == "GET":
        db = get_db()
        technicians = db.execute(
            "SELECT id, name FROM technicians WHERE active = 1 ORDER BY name"
        ).fetchall()
        return render_template(
            "admin/job_new.html",
            technicians=[dict(t) for t in technicians],
            priorities=VALID_PRIORITIES,
        )

    # ── POST ─────────────────────────────────────────────────────────────────
    db = get_db()
    errors: list[str] = []

    # Customer fields
    customer_name  = (request.form.get("customer_name")  or "").strip()
    customer_phone = (request.form.get("customer_phone") or "").strip()
    customer_email = (request.form.get("customer_email") or "").strip() or None

    # Device fields
    device_make        = (request.form.get("device_make")    or "").strip()
    device_model       = (request.form.get("device_model")   or "").strip()
    device_serial      = (request.form.get("device_serial")  or "").strip() or None
    device_passcode    = (request.form.get("device_passcode") or "").strip() or None
    device_condition   = (request.form.get("device_condition") or "").strip() or None

    # Job fields
    description    = (request.form.get("description")    or "").strip() or None
    priority       = (request.form.get("priority")       or "normal").strip()
    technician_id  = request.form.get("technician_id", type=int) or None
    promised_date  = (request.form.get("promised_date")  or "").strip() or None
    quoted_cents   = request.form.get("quoted_cents",  default=0, type=int)

    # Validate
    if not customer_name:
        errors.append("Customer name is required.")
    try:
        customer_phone = _validate_phone(customer_phone)
    except ValueError as e:
        errors.append(str(e))
    if not device_make:
        errors.append("Device make is required.")
    if not device_model:
        errors.append("Device model is required.")
    if priority not in VALID_PRIORITIES:
        errors.append(f"Invalid priority: {priority!r}")
    if quoted_cents < 0:
        errors.append("Quoted amount cannot be negative.")

    if errors:
        if _wants_json():
            return jsonify({"errors": errors}), 400
        db2 = get_db()
        technicians = db2.execute(
            "SELECT id, name FROM technicians WHERE active = 1 ORDER BY name"
        ).fetchall()
        return render_template(
            "admin/job_new.html",
            errors=errors,
            form=request.form,
            technicians=[dict(t) for t in technicians],
            priorities=VALID_PRIORITIES,
        ), 400

    # ── Single transaction: upsert customer → device → job → history ─────────
    try:
        db.execute("BEGIN")

        # Upsert customer by phone (the unique business key)
        existing = db.execute(
            "SELECT id, name FROM customers WHERE phone = ?", (customer_phone,)
        ).fetchone()

        if existing:
            customer_id = existing["id"]
            # Optionally update name/email if provided
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

        # Create device
        cur = db.execute(
            """
            INSERT INTO devices
                (customer_id, make, model, serial_imei, passcode, condition_notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (customer_id, device_make, device_model, device_serial,
             device_passcode, device_condition),
        )
        device_id = cur.lastrowid

        # Create job
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

        # Seed status history
        _log_status_change(
            db, job_id, old_status=None, new_status="received",
            changed_by="intake", note="Job created at intake.",
        )

        # Commit before SMS (sms_service does its own commit for sms_log)
        db.commit()

        # Send intake SMS
        sms_result = sms_intake(
            phone=customer_phone,
            customer_name=customer_name,
            job_id=job_id,
            customer_id=customer_id,
        )

    except Exception:
        db.execute("ROLLBACK")
        raise

    if _wants_json():
        return jsonify({"success": True, "job_id": job_id, "sms": sms_result}), 201

    return redirect(url_for("admin.job_detail", job_id=job_id))


# ─────────────────────────────────────────────────────────────────────────────
# POST /admin/jobs/<id>/edit  — Update notes, pricing, promised date
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/jobs/<int:job_id>/edit", methods=["POST"])
@login_required
def job_edit(job_id: int):
    db = get_db()

    job = db.execute(
        "SELECT id FROM repair_jobs WHERE id = ?", (job_id,)
    ).fetchone()
    if job is None:
        abort(404)

    description      = (request.form.get("description")      or "").strip() or None
    diagnosis_notes  = (request.form.get("diagnosis_notes")  or "").strip() or None
    promised_date    = (request.form.get("promised_date")     or "").strip() or None
    technician_id    = request.form.get("technician_id", type=int) or None
    priority         = (request.form.get("priority") or "").strip()

    labour_cents = request.form.get("labour_cents", default=0, type=int)
    parts_cents  = request.form.get("parts_cents",  default=0, type=int)
    deposit_cents = request.form.get("deposit_cents", default=0, type=int)

    errors: list[str] = []
    if priority and priority not in VALID_PRIORITIES:
        errors.append(f"Invalid priority: {priority!r}")
    if labour_cents < 0:
        errors.append("Labour cannot be negative.")
    if parts_cents < 0:
        errors.append("Parts cost cannot be negative.")
    if deposit_cents < 0:
        errors.append("Deposit cannot be negative.")

    if errors:
        if _wants_json():
            return jsonify({"errors": errors}), 400
        abort(400, "; ".join(errors))

    gst_cents, pst_cents = _calc_tax(labour_cents, parts_cents)

    fields: list[tuple] = [
        ("description",     description),
        ("diagnosis_notes", diagnosis_notes),
        ("promised_date",   promised_date),
        ("technician_id",   technician_id),
        ("labour_cents",    labour_cents),
        ("parts_cents",     parts_cents),
        ("deposit_cents",   deposit_cents),
        ("gst_cents",       gst_cents),
        ("pst_cents",       pst_cents),
    ]
    if priority:
        fields.append(("priority", priority))

    set_clause = ", ".join(f"{col} = ?" for col, _ in fields)
    values = [v for _, v in fields] + [job_id]

    try:
        db.execute("BEGIN")
        db.execute(f"UPDATE repair_jobs SET {set_clause} WHERE id = ?", values)
        db.commit()
    except Exception:
        db.execute("ROLLBACK")
        raise

    if _wants_json():
        return jsonify({
            "success":    True,
            "gst_cents":  gst_cents,
            "pst_cents":  pst_cents,
            "total_cents": labour_cents + parts_cents + gst_cents + pst_cents,
        })

    return redirect(url_for("admin.job_detail", job_id=job_id))


# ─────────────────────────────────────────────────────────────────────────────
# GET /admin/customers/<id>  — Full repair history
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/customers")
@login_required
def customer_list():
    db = get_db()
    customers = db.execute(
        """
        SELECT c.*,
               COUNT(DISTINCT rj.id) AS job_count,
               SUM(CASE WHEN rj.status NOT IN ('picked_up','cancelled','closed') THEN 1 ELSE 0 END) AS active_jobs,
               COUNT(DISTINCT s.id) AS sms_count
        FROM   customers c
        LEFT JOIN repair_jobs rj ON rj.customer_id = c.id
        LEFT JOIN sms_log     s  ON s.customer_id  = c.id
        GROUP  BY c.id
        ORDER  BY c.created_at DESC
        """
    ).fetchall()
    ctx = {"customers": [dict(r) for r in customers]}
    if _wants_json():
        return jsonify(ctx)
    return render_template("admin/customer_list.html", **ctx)


@admin_bp.route("/customers/<int:customer_id>")
@login_required
def customer_detail(customer_id: int):
    db = get_db()

    customer = db.execute(
        "SELECT * FROM customers WHERE id = ?", (customer_id,)
    ).fetchone()

    if customer is None:
        abort(404)

    devices = db.execute(
        "SELECT * FROM devices WHERE customer_id = ? ORDER BY created_at DESC",
        (customer_id,),
    ).fetchall()

    jobs = db.execute(
        """
        SELECT rj.*, d.make, d.model, t.name AS technician_name
        FROM   repair_jobs rj
        JOIN   devices     d ON d.id = rj.device_id
        LEFT JOIN technicians t ON t.id = rj.technician_id
        WHERE  rj.customer_id = ?
        ORDER  BY rj.created_at DESC
        """,
        (customer_id,),
    ).fetchall()

    ctx = {
        "customer": dict(customer),
        "devices":  [dict(d) for d in devices],
        "jobs":     [dict(j) for j in jobs],
    }

    if _wants_json():
        return jsonify(ctx)

    return render_template("admin/customer_detail.html", **ctx)


# ─────────────────────────────────────────────────────────────────────────────
# Technician management
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/technicians")
@login_required
def technician_list():
    db = get_db()
    technicians = db.execute(
        """
        SELECT t.*, COUNT(rj.id) AS active_jobs
        FROM   technicians t
        LEFT JOIN repair_jobs rj
               ON rj.technician_id = t.id
              AND rj.status NOT IN ('picked_up', 'cancelled', 'closed')
        GROUP  BY t.id
        ORDER  BY t.active DESC, t.name ASC
        """
    ).fetchall()
    ctx = {"technicians": [dict(r) for r in technicians]}
    if _wants_json():
        return jsonify(ctx)
    return render_template("admin/technician_list.html", **ctx)


@admin_bp.route("/technicians/new", methods=["POST"])
@login_required
def technician_new():
    name  = (request.form.get("name")  or "").strip()
    email = (request.form.get("email") or "").strip() or None
    phone = (request.form.get("phone") or "").strip() or None

    if not name:
        flash("Name is required.", "error")
        return redirect(url_for("admin.technician_list"))

    if phone:
        try:
            phone = _validate_phone(phone)
        except ValueError as e:
            flash(str(e), "error")
            return redirect(url_for("admin.technician_list"))

    db = get_db()
    db.execute(
        "INSERT INTO technicians (name, email, phone) VALUES (?, ?, ?)",
        (name, email, phone),
    )
    db.commit()
    flash(f"Technician '{name}' added.", "success")
    return redirect(url_for("admin.technician_list"))


@admin_bp.route("/technicians/<int:tech_id>/toggle", methods=["POST"])
@login_required
def technician_toggle(tech_id: int):
    db = get_db()
    tech = db.execute("SELECT id, active, name FROM technicians WHERE id = ?", (tech_id,)).fetchone()
    if not tech:
        abort(404)
    new_active = 0 if tech["active"] else 1
    db.execute("UPDATE technicians SET active = ? WHERE id = ?", (new_active, tech_id))
    db.commit()
    state = "activated" if new_active else "deactivated"
    flash(f"Technician '{tech['name']}' {state}.", "success")
    return redirect(url_for("admin.technician_list"))


# ─────────────────────────────────────────────────────────────────────────────
# Parts management
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/jobs/<int:job_id>/parts/add", methods=["POST"])
@login_required
def part_add(job_id: int):
    db = get_db()
    if not db.execute("SELECT id FROM repair_jobs WHERE id = ?", (job_id,)).fetchone():
        abort(404)

    name        = (request.form.get("name")        or "").strip()
    part_number = (request.form.get("part_number") or "").strip() or None
    supplier    = (request.form.get("supplier")    or "").strip() or None
    cost_cents  = request.form.get("cost_cents", default=0, type=int)

    if not name:
        flash("Part name is required.", "error")
        return redirect(url_for("admin.job_detail", job_id=job_id))
    if cost_cents < 0:
        flash("Cost cannot be negative.", "error")
        return redirect(url_for("admin.job_detail", job_id=job_id))

    db.execute(
        """INSERT INTO parts (job_id, name, part_number, supplier, cost_cents)
           VALUES (?, ?, ?, ?, ?)""",
        (job_id, name, part_number, supplier, cost_cents),
    )
    db.commit()
    flash(f"Part '{name}' added.", "success")
    return redirect(url_for("admin.job_detail", job_id=job_id))


@admin_bp.route("/parts/<int:part_id>/status", methods=["POST"])
@login_required
def part_update_status(part_id: int):
    db = get_db()
    part = db.execute("SELECT * FROM parts WHERE id = ?", (part_id,)).fetchone()
    if not part:
        abort(404)

    new_status = (request.form.get("status") or "").strip()
    valid = ("ordered", "received", "installed", "returned")
    if new_status not in valid:
        flash("Invalid part status.", "error")
        return redirect(url_for("admin.job_detail", job_id=part["job_id"]))

    db.execute("UPDATE parts SET status = ? WHERE id = ?", (new_status, part_id))
    db.commit()
    flash(f"Part status updated to '{new_status}'.", "success")
    return redirect(url_for("admin.job_detail", job_id=part["job_id"]))


# ─────────────────────────────────────────────────────────────────────────────
# SMS log (global)
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/sms-log")
@login_required
def sms_log():
    db = get_db()
    logs = db.execute(
        """
        SELECT s.*,
               c.name  AS customer_name,
               c.phone AS customer_phone,
               rj.id   AS repair_job_id
        FROM   sms_log   s
        LEFT JOIN customers  c  ON c.id  = s.customer_id
        LEFT JOIN repair_jobs rj ON rj.id = s.job_id
        ORDER  BY s.sent_at DESC
        LIMIT  200
        """
    ).fetchall()
    ctx = {"logs": [dict(r) for r in logs]}
    if _wants_json():
        return jsonify(ctx)
    return render_template("admin/sms_log.html", **ctx)


# ─────────────────────────────────────────────────────────────────────────────
# Invoice routes
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/invoices")
@login_required
def invoice_list():
    db = get_db()
    rows = db.execute(
        """
        SELECT i.*,
               c.name  AS customer_name, c.phone AS customer_phone,
               rj.status AS job_status
        FROM   invoices i
        JOIN   customers   c  ON c.id  = i.customer_id
        JOIN   repair_jobs rj ON rj.id = i.job_id
        ORDER  BY i.created_at DESC
        """
    ).fetchall()
    ctx = {"invoices": [dict(r) for r in rows]}
    if _wants_json():
        return jsonify(ctx)
    return render_template("admin/invoice_list.html", **ctx)


@admin_bp.route("/jobs/<int:job_id>/invoice/new", methods=["GET", "POST"])
@login_required
def invoice_new(job_id: int):
    db = get_db()

    job = db.execute(
        """
        SELECT rj.*,
               c.name  AS customer_name, c.phone AS customer_phone,
               d.make, d.model
        FROM   repair_jobs rj
        JOIN   customers   c ON c.id = rj.customer_id
        JOIN   devices     d ON d.id = rj.device_id
        WHERE  rj.id = ?
        """,
        (job_id,),
    ).fetchone()

    if job is None:
        abort(404)

    job = dict(job)
    wallet = get_or_create_wallet(db, job["customer_id"])
    subtotal = job["total_cents"]
    max_coins = calc_max_coins(subtotal, wallet["balance_coins"])

    if request.method == "GET":
        return render_template(
            "admin/invoice_new.html",
            job=job,
            wallet=wallet,
            max_coins=max_coins,
            COIN_VALUE_CENTS=COIN_VALUE_CENTS,
        )

    # ── POST: create invoice ──────────────────────────────────────────────────
    coins_to_apply = request.form.get("coins_applied", default=0, type=int)
    notes = (request.form.get("notes") or "").strip() or None

    if coins_to_apply < 0:
        coins_to_apply = 0
    if coins_to_apply > max_coins:
        flash(f"You can apply at most {max_coins} coins on this invoice.", "error")
        return redirect(url_for("admin.invoice_new", job_id=job_id))

    discount_cents = coins_to_apply * COIN_VALUE_CENTS

    try:
        db.execute("BEGIN")

        if coins_to_apply > 0:
            spend_coins(db, job["customer_id"], coins_to_apply,
                        reason=f"Invoice for Job #{job_id}", job_id=job_id)

        cur = db.execute(
            """
            INSERT INTO invoices
                (job_id, customer_id, labour_cents, parts_cents, gst_cents, pst_cents,
                 coins_applied, discount_cents, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (job_id, job["customer_id"],
             job["labour_cents"], job["parts_cents"],
             job["gst_cents"],   job["pst_cents"],
             coins_to_apply, discount_cents, notes),
        )
        invoice_id = cur.lastrowid
        db.commit()
    except ValueError as e:
        db.execute("ROLLBACK")
        flash(str(e), "error")
        return redirect(url_for("admin.invoice_new", job_id=job_id))
    except Exception:
        db.execute("ROLLBACK")
        raise

    flash(f"Invoice #{invoice_id} created.", "success")
    return redirect(url_for("admin.invoice_detail", invoice_id=invoice_id))


@admin_bp.route("/invoices/<int:invoice_id>")
@login_required
def invoice_detail(invoice_id: int):
    db = get_db()
    inv = db.execute(
        """
        SELECT i.*,
               c.name  AS customer_name, c.phone AS customer_phone,
               d.make, d.model,
               rj.status AS job_status
        FROM   invoices    i
        JOIN   customers   c  ON c.id  = i.customer_id
        JOIN   repair_jobs rj ON rj.id = i.job_id
        JOIN   devices     d  ON d.id  = rj.device_id
        WHERE  i.id = ?
        """,
        (invoice_id,),
    ).fetchone()
    if inv is None:
        abort(404)

    ctx = {"inv": dict(inv)}
    if _wants_json():
        return jsonify(ctx)
    return render_template("admin/invoice_detail.html", **ctx)


@admin_bp.route("/invoices/<int:invoice_id>/mark-paid", methods=["POST"])
@login_required
def invoice_mark_paid(invoice_id: int):
    db = get_db()
    inv = db.execute("SELECT id, status FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if inv is None:
        abort(404)
    if inv["status"] == "paid":
        flash("Invoice is already marked paid.", "error")
        return redirect(url_for("admin.invoice_detail", invoice_id=invoice_id))

    db.execute(
        "UPDATE invoices SET status = 'paid', paid_at = ? WHERE id = ?",
        (_now_iso(), invoice_id),
    )
    db.commit()
    flash("Invoice marked as paid.", "success")
    return redirect(url_for("admin.invoice_detail", invoice_id=invoice_id))


@admin_bp.route("/invoices/<int:invoice_id>/send-sms", methods=["POST"])
@login_required
def invoice_send_sms(invoice_id: int):
    db = get_db()
    inv = db.execute(
        """
        SELECT i.*, c.name AS customer_name, c.phone AS customer_phone,
               d.make, d.model
        FROM   invoices    i
        JOIN   customers   c  ON c.id  = i.customer_id
        JOIN   repair_jobs rj ON rj.id = i.job_id
        JOIN   devices     d  ON d.id  = rj.device_id
        WHERE  i.id = ?
        """,
        (invoice_id,),
    ).fetchone()
    if inv is None:
        abort(404)

    inv = dict(inv)
    amount_dollars = inv["amount_due_cents"] / 100
    body = (
        f"Hi {inv['customer_name']}, your invoice for Job #{inv['job_id']} "
        f"({inv['make']} {inv['model']}) is ready. "
        f"Amount due: ${amount_dollars:.2f} CAD. "
        f"Thank you for choosing The Crucible!"
    )
    result = send_sms(
        phone=inv["customer_phone"],
        message=body,
        customer_id=inv["customer_id"],
        job_id=inv["job_id"],
    )
    if result.get("success"):
        flash("Invoice SMS sent.", "success")
    else:
        flash(f"SMS failed: {result.get('error_message', 'unknown error')}", "error")
    return redirect(url_for("admin.invoice_detail", invoice_id=invoice_id))


# ─────────────────────────────────────────────────────────────────────────────
# Wallet / Crucible Coin routes
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/wallets")
@login_required
def wallet_list():
    db = get_db()
    rows = db.execute(
        """
        SELECT w.*, c.name AS customer_name, c.phone AS customer_phone
        FROM   wallets    w
        JOIN   customers  c ON c.id = w.customer_id
        ORDER  BY w.balance_coins DESC, c.name ASC
        """
    ).fetchall()
    ctx = {"wallets": [dict(r) for r in rows]}
    if _wants_json():
        return jsonify(ctx)
    return render_template("admin/wallet_list.html", **ctx)


@admin_bp.route("/wallets/<int:customer_id>")
@login_required
def wallet_detail(customer_id: int):
    db = get_db()

    customer = db.execute(
        "SELECT * FROM customers WHERE id = ?", (customer_id,)
    ).fetchone()
    if customer is None:
        abort(404)

    wallet = get_or_create_wallet(db, customer_id)
    db.commit()  # persist wallet if just created

    txns = db.execute(
        """
        SELECT * FROM wallet_transactions
        WHERE wallet_id = ?
        ORDER BY created_at DESC
        """,
        (wallet["id"],),
    ).fetchall()

    ctx = {
        "customer": dict(customer),
        "wallet":   wallet,
        "txns":     [dict(t) for t in txns],
    }
    if _wants_json():
        return jsonify(ctx)
    return render_template("admin/wallet_detail.html", **ctx)


@admin_bp.route("/wallets/<int:customer_id>/adjust", methods=["POST"])
@login_required
def wallet_adjust(customer_id: int):
    db = get_db()
    customer = db.execute(
        "SELECT id FROM customers WHERE id = ?", (customer_id,)
    ).fetchone()
    if customer is None:
        abort(404)

    txn_type = (request.form.get("type") or "").strip()
    amount   = request.form.get("amount", default=0, type=int)
    reason   = (request.form.get("reason") or "").strip()

    if txn_type not in ("credit", "debit"):
        flash("Type must be 'credit' or 'debit'.", "error")
        return redirect(url_for("admin.wallet_detail", customer_id=customer_id))
    if amount <= 0:
        flash("Amount must be at least 1 coin.", "error")
        return redirect(url_for("admin.wallet_detail", customer_id=customer_id))
    if not reason:
        flash("Reason is required.", "error")
        return redirect(url_for("admin.wallet_detail", customer_id=customer_id))

    try:
        db.execute("BEGIN")
        if txn_type == "credit":
            add_coins(db, customer_id, amount, reason=f"[Manual] {reason}")
        else:
            spend_coins(db, customer_id, amount, reason=f"[Manual] {reason}")
        db.commit()
        flash(f"{'Credited' if txn_type == 'credit' else 'Debited'} {amount} coin(s).", "success")
    except ValueError as e:
        db.execute("ROLLBACK")
        flash(str(e), "error")
    except Exception:
        db.execute("ROLLBACK")
        raise

    return redirect(url_for("admin.wallet_detail", customer_id=customer_id))
