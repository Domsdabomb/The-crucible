"""Round 3 features: admin dashboard revenue summaries and the customer
portal repair timeline.

Revenue: aggregate queries over the invoices table — total collected,
this month, outstanding, unpaid count.
Portal timeline: GET /portal/jobs/<id> — ownership-scoped vertical
timeline of job_status_history for the customer's own job.
"""

from datetime import datetime, timedelta, timezone


# ── helpers (module-local; mirrors tests/test_portal.py and tests/test_export.py) ──

def _signup(client, csrf_extractor, phone, password="password123",
            name="Jane Doe", email=None, ticket=None, confirm=None):
    resp = client.get("/portal/signup")
    token = csrf_extractor(resp.get_data(as_text=True))
    return client.post("/portal/signup", data={
        "name": name, "phone": phone, "email": email or "",
        "password": password, "confirm": confirm if confirm is not None else password,
        "ticket": ticket or "", "csrf_token": token,
    })


def _login(client, csrf_extractor, phone, password):
    resp = client.get("/portal/login")
    token = csrf_extractor(resp.get_data(as_text=True))
    return client.post("/portal/login", data={
        "phone": phone, "password": password, "csrf_token": token,
    })


def _admin_post(admin, csrf_extractor, get_path, post_path, data):
    """POST via a CSRF token extracted from a GET on a (possibly different) page."""
    resp = admin.get(get_path)
    token = csrf_extractor(resp.get_data(as_text=True))
    data = dict(data)
    data["csrf_token"] = token
    return admin.post(post_path, data=data)


def _create_job(admin, csrf_extractor, phone):
    resp = _admin_post(admin, csrf_extractor, "/admin/jobs/new", "/admin/jobs/new", {
        "customer_name": "Job Customer", "customer_phone": phone,
        "device_make": "Apple", "device_model": "iPhone 15",
        "priority": "normal", "quoted_cents": "0",
    })
    return int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


def _set_job_status(admin, csrf_extractor, job_id, status):
    return _admin_post(admin, csrf_extractor, f"/admin/jobs/{job_id}",
                       f"/admin/jobs/{job_id}/status", {"status": status})


def _invoice_row(db, customer_id, job_id, labour_cents, status="unpaid", paid_at=None):
    cur = db.execute(
        """INSERT INTO invoices
               (job_id, customer_id, labour_cents, parts_cents,
                gst_cents, pst_cents, status, paid_at)
           VALUES (?, ?, ?, 0, 0, 0, ?, ?)""",
        (job_id, customer_id, labour_cents, status, paid_at),
    )
    db.commit()
    return cur.lastrowid


def _paid_this_month() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _paid_last_month() -> str:
    now = datetime.now(timezone.utc)
    prev = (now.replace(day=1) - timedelta(days=1)).replace(day=1)
    return prev.strftime("%Y-%m-01T00:00:00.000Z")


# ─────────────────────────────────────────────────────────────────────────────
# Admin dashboard revenue overview
# ─────────────────────────────────────────────────────────────────────────────

def test_dashboard_revenue_empty_db(admin_client):
    """No invoices at all — revenue cards render zeros, no crash."""
    resp = admin_client.get("/admin/", headers={"Accept": "application/json"})
    assert resp.status_code == 200
    revenue = resp.get_json()["revenue"]
    assert revenue == {
        "collected_cents": 0,
        "month_cents": 0,
        "outstanding_cents": 0,
        "unpaid_count": 0,
    }


def test_dashboard_revenue_totals(admin_client, db):
    """Collected (all-time paid), this-month paid, outstanding unpaid,
    and unpaid invoice count."""
    cust = db.execute(
        "INSERT INTO customers (name, phone) VALUES (?, ?)",
        ("Revenue Customer", "+12505550301"),
    ).lastrowid
    dev = db.execute(
        "INSERT INTO devices (customer_id, make, model) VALUES (?, ?, ?)",
        (cust, "Apple", "iPhone 15"),
    ).lastrowid
    job = db.execute(
        "INSERT INTO repair_jobs (device_id, customer_id) VALUES (?, ?)",
        (dev, cust),
    ).lastrowid
    db.commit()

    # Paid this month: $100
    _invoice_row(db, cust, job, 10000, status="paid", paid_at=_paid_this_month())
    # Paid last month: $50 — counts toward all-time, not this month
    _invoice_row(db, cust, job, 5000, status="paid", paid_at=_paid_last_month())
    # Unpaid: $25
    _invoice_row(db, cust, job, 2500, status="unpaid")

    resp = admin_client.get("/admin/", headers={"Accept": "application/json"})
    assert resp.status_code == 200
    revenue = resp.get_json()["revenue"]
    assert revenue["collected_cents"] == 15000
    assert revenue["month_cents"] == 10000
    assert revenue["outstanding_cents"] == 2500
    assert revenue["unpaid_count"] == 1


def test_dashboard_revenue_renders_in_html(admin_client, db):
    """The revenue overview cards appear in the HTML dashboard."""
    cust = db.execute(
        "INSERT INTO customers (name, phone) VALUES (?, ?)",
        ("HTML Customer", "+12505550302"),
    ).lastrowid
    dev = db.execute(
        "INSERT INTO devices (customer_id, make, model) VALUES (?, ?, ?)",
        (cust, "Samsung", "Galaxy S24"),
    ).lastrowid
    job = db.execute(
        "INSERT INTO repair_jobs (device_id, customer_id) VALUES (?, ?)",
        (dev, cust),
    ).lastrowid
    db.commit()
    _invoice_row(db, cust, job, 12345, status="paid", paid_at=_paid_this_month())
    _invoice_row(db, cust, job, 6700, status="unpaid")

    resp = admin_client.get("/admin/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "$123.45" in html            # total collected card
    assert "$67.00" in html             # outstanding card
    assert "Unpaid invoices" in html


# ─────────────────────────────────────────────────────────────────────────────
# Customer portal repair timeline
# ─────────────────────────────────────────────────────────────────────────────

def test_portal_job_detail_requires_login(client):
    resp = client.get("/portal/jobs/1")
    assert resp.status_code == 302
    assert "/portal/login" in resp.headers["Location"]


def test_portal_job_detail_shows_timeline(client, csrf_extractor, db, admin_client):
    """Own job: status history renders as a vertical timeline, in order."""
    phone = "+12505550401"
    _signup(client, csrf_extractor, phone)
    job_id = _create_job(admin_client, csrf_extractor, phone)
    _set_job_status(admin_client, csrf_extractor, job_id, "diagnosed")

    resp = client.get(f"/portal/jobs/{job_id}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "timeline" in html
    assert f"Ticket #{job_id}" in html
    assert "Apple iPhone 15" in html
    # Timeline entries in chronological order: received before diagnosed
    assert html.index("received") < html.index("diagnosed")


def test_portal_job_detail_other_customers_job_is_404(
    client, csrf_extractor, db, admin_client
):
    """A customer cannot view another customer's repair timeline."""
    _signup(client, csrf_extractor, "+12505550402", name="Cust A")
    other_job = _create_job(admin_client, csrf_extractor, "+12505550403")

    resp = client.get(f"/portal/jobs/{other_job}")
    assert resp.status_code == 404


def test_portal_dashboard_links_to_job_timeline(client, csrf_extractor, admin_client):
    phone = "+12505550404"
    _signup(client, csrf_extractor, phone)
    job_id = _create_job(admin_client, csrf_extractor, phone)

    resp = client.get("/portal/")
    assert resp.status_code == 200
    assert f"/portal/jobs/{job_id}" in resp.get_data(as_text=True)
