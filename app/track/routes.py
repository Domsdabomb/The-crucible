"""
Public, unauthenticated job-status lookup — the v1 `/track` route, ported.

Requires both the customer's phone number AND their ticket number (two
factors the shop gave them on their receipt) so a phone number alone
isn't enough to browse a customer's repair history.
"""

import re

from flask import render_template, request

from app.db import get_db
from . import track_bp

E164_RE = re.compile(r"^\+1[2-9]\d{9}$")


def _lookup_job(job_id: int, phone: str):
    db = get_db()
    return db.execute(
        """
        SELECT rj.id, rj.status, rj.promised_date, rj.quoted_cents, rj.updated_at,
               d.make, d.model
        FROM   repair_jobs rj
        JOIN   customers   c ON c.id = rj.customer_id
        JOIN   devices     d ON d.id = rj.device_id
        WHERE  rj.id = ? AND c.phone = ?
        """,
        (job_id, phone),
    ).fetchone()


@track_bp.route("/", methods=["GET", "POST"])
def track():
    job = None
    history = []
    error = None

    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        ticket_raw = request.form.get("ticket", "").strip().lstrip("#")

        if not E164_RE.match(phone) or not ticket_raw.isdigit():
            error = "Enter a valid phone number (e.g. +12505550100) and ticket number."
        else:
            row = _lookup_job(int(ticket_raw), phone)
            if row is None:
                error = "No matching repair found. Double-check your phone number and ticket number."
            else:
                job = dict(row)
                history = [
                    dict(h) for h in get_db().execute(
                        """
                        SELECT new_status, changed_at
                        FROM   job_status_history
                        WHERE  job_id = ?
                        ORDER  BY changed_at
                        """,
                        (job["id"],),
                    ).fetchall()
                ]

    return render_template("track/track.html", job=job, history=history, error=error)
