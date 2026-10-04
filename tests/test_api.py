"""Tests for the /api/v1 JSON API (mobile backend)."""

import pytest

from app.services.auth import create_admin, hash_password


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _login(client, **payload):
    """POST /api/v1/auth/login and return (status, body)."""
    resp = client.post("/api/v1/auth/login", json=payload)
    return resp.status_code, resp.get_json()


def _auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def staff_token(client, db):
    """Admin staff token via the real login endpoint."""
    create_admin("apiadmin", "apipassword123", role="admin")
    status, body = _login(client, username="apiadmin", password="apipassword123")
    assert status == 200, body
    assert body["account_type"] == "staff"
    assert body["role"] == "admin"
    return body["token"]


@pytest.fixture
def tech_token(client, db):
    """Technician staff token linked to technicians row id 1."""
    cur = db.execute(
        "INSERT INTO technicians (name, email) VALUES (?, ?)",
        ("Tech One", "tech1@example.com"),
    )
    db.commit()
    create_admin("apitech", "apipassword123", role="technician",
                 technician_id=cur.lastrowid)
    status, body = _login(client, username="apitech", password="apipassword123")
    assert status == 200, body
    assert body["role"] == "technician"
    return body["token"]


@pytest.fixture
def customer_token(client, db):
    """Customer (portal) token via the real login endpoint."""
    db.execute(
        "INSERT INTO customers (name, phone, email, password_hash) "
        "VALUES (?, ?, ?, ?)",
        ("Cust One", "+16045550101", "cust1@example.com",
         hash_password("custpassword123")),
    )
    db.commit()
    status, body = _login(
        client, phone="+16045550101", password="custpassword123"
    )
    assert status == 200, body
    assert body["account_type"] == "customer"
    return body["token"]


def _make_job(db, customer_id=None, technician_id=None, status="received",
              labour_cents=0, parts_cents=0, phone="+16045550201", name="Job Cust"):
    """Insert a customer + device + job directly, seeding status history."""
    if customer_id is None:
        cur = db.execute(
            "INSERT INTO customers (name, phone) VALUES (?, ?)", (name, phone)
        )
        customer_id = cur.lastrowid
    cur = db.execute(
        "INSERT INTO devices (customer_id, make, model) VALUES (?, ?, ?)",
        (customer_id, "Apple", "iPhone 14"),
    )
    device_id = cur.lastrowid
    cur = db.execute(
        """
        INSERT INTO repair_jobs
            (device_id, customer_id, technician_id, status, labour_cents, parts_cents)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (device_id, customer_id, technician_id, status, labour_cents, parts_cents),
    )
    job_id = cur.lastrowid
    db.execute(
        "INSERT INTO job_status_history (job_id, old_status, new_status, changed_by) "
        "VALUES (?, NULL, 'received', 'test')",
        (job_id,),
    )
    db.commit()
    return job_id, customer_id


def _api_headers(token):
    return _auth_headers(token)


# ─────────────────────────────────────────────────────────────────────────────
# Health + auth
# ─────────────────────────────────────────────────────────────────────────────

def test_health_no_auth(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "version": "1"}


def test_login_staff_success(client, db):
    create_admin("boss", "bosssecret1", role="admin")
    status, body = _login(client, username="boss", password="bosssecret1")
    assert status == 200
    assert body["token"]
    assert body["account_type"] == "staff"
    # Only the hash is stored — the raw token must not be in the DB.
    row = db.execute("SELECT token_hash FROM api_tokens").fetchone()
    assert row["token_hash"] != body["token"]
    assert len(row["token_hash"]) == 64


def test_login_wrong_password_401(client, db):
    create_admin("boss", "bosssecret1", role="admin")
    status, body = _login(client, username="boss", password="wrongpassword")
    assert status == 401
    assert body["error"]["code"] == "invalid_credentials"


def test_login_unknown_user_401(client):
    status, body = _login(client, username="nobody", password="whatever123")
    assert status == 401
    assert body["error"]["code"] == "invalid_credentials"


def test_login_missing_fields_400(client):
    status, body = _login(client, password="whatever123")
    assert status == 400
    assert body["error"]["code"] == "validation_error"


def test_login_customer_no_portal_account_401(client, db):
    db.execute(
        "INSERT INTO customers (name, phone) VALUES (?, ?)",
        ("No Portal", "+16045550301"),
    )
    db.commit()
    status, body = _login(
        client, phone="+16045550301", password="whatever123"
    )
    assert status == 401
    assert body["error"]["code"] == "invalid_credentials"


def test_no_token_401(client):
    resp = client.get("/api/v1/jobs")
    assert resp.status_code == 401
    assert resp.get_json()["error"]["code"] == "unauthorized"


def test_malformed_auth_header_401(client):
    resp = client.get("/api/v1/jobs", headers={"Authorization": "Token abc"})
    assert resp.status_code == 401


def test_bad_token_401(client):
    resp = client.get("/api/v1/jobs", headers=_auth_headers("bogus-token"))
    assert resp.status_code == 401


def test_logout_revokes_token(client, staff_token):
    h = _api_headers(staff_token)
    assert client.get("/api/v1/jobs", headers=h).status_code == 200
    resp = client.post("/api/v1/auth/logout", headers=h)
    assert resp.status_code == 200
    assert resp.get_json() == {"success": True}
    resp = client.get("/api/v1/jobs", headers=h)
    assert resp.status_code == 401
    assert resp.get_json()["error"]["code"] == "unauthorized"


def test_locked_account_423(client, db):
    create_admin("lockme", "lockmepass1", role="admin")
    for _ in range(5):
        _login(client, username="lockme", password="wrongpassword")
    status, body = _login(client, username="lockme", password="lockmepass1")
    assert status == 423
    assert body["error"]["code"] == "account_locked"


# ─────────────────────────────────────────────────────────────────────────────
# Role separation
# ─────────────────────────────────────────────────────────────────────────────

def test_technician_sees_only_own_jobs(client, db, tech_token):
    tech1 = db.execute(
        "SELECT technician_id FROM admins WHERE username = 'apitech'"
    ).fetchone()["technician_id"]
    cur = db.execute(
        "INSERT INTO technicians (name) VALUES (?)", ("Tech Two",)
    )
    tech2 = cur.lastrowid
    db.commit()
    _make_job(db, technician_id=tech1, phone="+16045551111")
    _make_job(db, technician_id=tech2, phone="+16045552222")

    resp = client.get("/api/v1/jobs", headers=_api_headers(tech_token))
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total"] == 1
    assert body["data"][0]["technician"]["id"] == tech1


def test_technician_cannot_view_others_job(client, db, tech_token):
    cur = db.execute("INSERT INTO technicians (name) VALUES (?)", ("Tech Two",))
    db.commit()
    job_id, _ = _make_job(db, technician_id=cur.lastrowid,
                          phone="+16045553333")
    resp = client.get(f"/api/v1/jobs/{job_id}", headers=_api_headers(tech_token))
    assert resp.status_code == 403
    assert resp.get_json()["error"]["code"] == "forbidden"


def test_technician_forbidden_on_admin_endpoints(client, tech_token):
    h = _api_headers(tech_token)
    assert client.get("/api/v1/dashboard", headers=h).status_code == 403
    assert client.get("/api/v1/invoices", headers=h).status_code == 403
    assert client.get("/api/v1/customers", headers=h).status_code == 403
    assert client.post("/api/v1/jobs", headers=h, json={}).status_code == 403
    assert client.post("/api/v1/invoices", headers=h, json={}).status_code == 403


def test_customer_forbidden_on_staff_endpoints(client, customer_token):
    h = _api_headers(customer_token)
    assert client.get("/api/v1/jobs", headers=h).status_code == 403
    assert client.get("/api/v1/dashboard", headers=h).status_code == 403


def test_staff_forbidden_on_portal_timeline(client, staff_token):
    resp = client.get("/api/v1/portal/timeline",
                      headers=_api_headers(staff_token))
    assert resp.status_code == 403


def test_job_not_found_404_shape(client, staff_token):
    resp = client.get("/api/v1/jobs/99999", headers=_api_headers(staff_token))
    assert resp.status_code == 404
    body = resp.get_json()
    assert set(body["error"].keys()) == {"code", "message"}


def test_unknown_api_route_404_json(client):
    resp = client.get("/api/v1/definitely-not-here")
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "not_found"


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────────

def test_dashboard_revenue(client, db, staff_token):
    job_id, cust_id = _make_job(db, labour_cents=10000, parts_cents=0,
                                phone="+16045554444")
    # paid invoice: 10000 + 5% GST + 7% PST = 11200
    db.execute(
        "INSERT INTO invoices (job_id, customer_id, labour_cents, gst_cents, pst_cents, status, paid_at) "
        "VALUES (?, ?, 10000, 500, 700, 'paid', '2026-10-01T00:00:00.000Z')",
        (job_id, cust_id),
    )
    # unpaid invoice: 5000 + 250 + 350 = 5600
    db.execute(
        "INSERT INTO invoices (job_id, customer_id, labour_cents, gst_cents, pst_cents, status) "
        "VALUES (?, ?, 5000, 250, 350, 'unpaid')",
        (job_id, cust_id),
    )
    db.commit()

    resp = client.get("/api/v1/dashboard", headers=_api_headers(staff_token))
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["revenue"]["collected_cents"] == 11200
    assert body["revenue"]["outstanding_cents"] == 5600
    assert body["revenue"]["unpaid_count"] == 1
    assert body["status_counts"]["received"] == 1
    assert len(body["recent_jobs"]) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Jobs
# ─────────────────────────────────────────────────────────────────────────────

def test_job_list_pagination(client, db, staff_token):
    for i in range(25):
        _make_job(db, phone=f"+1604555{i:04d}", name=f"Cust {i}")
    h = _api_headers(staff_token)
    resp = client.get("/api/v1/jobs?page=2&per_page=10", headers=h)
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["page"] == 2
    assert body["per_page"] == 10
    assert body["total"] == 25
    assert len(body["data"]) == 10


def test_job_list_filter_status(client, db, staff_token):
    _make_job(db, status="received", phone="+16045556666")
    _make_job(db, status="ready", phone="+16045557777")
    resp = client.get("/api/v1/jobs?status=ready",
                      headers=_api_headers(staff_token))
    body = resp.get_json()
    assert body["total"] == 1
    assert body["data"][0]["status"] == "ready"


def test_job_create_admin_201(client, staff_token, db):
    payload = {
        "customer_name": "New Cust",
        "customer_phone": "+16045558888",
        "device_make": "Samsung",
        "device_model": "Galaxy S24",
        "description": "Cracked screen",
        "priority": "high",
        "quoted_cents": 12000,
    }
    resp = client.post("/api/v1/jobs", headers=_api_headers(staff_token),
                       json=payload)
    assert resp.status_code == 201
    body = resp.get_json()
    job = body["job"]
    assert job["status"] == "received"
    assert job["priority"] == "high"
    assert job["customer"]["phone"] == "+16045558888"
    assert job["device"]["make"] == "Samsung"
    assert len(job["history"]) == 1
    assert job["history"][0]["new_status"] == "received"


def test_job_create_validation_400(client, staff_token):
    resp = client.post("/api/v1/jobs", headers=_api_headers(staff_token),
                       json={"customer_name": "X"})
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "validation_error"


def test_job_create_bad_phone_400(client, staff_token):
    resp = client.post(
        "/api/v1/jobs", headers=_api_headers(staff_token),
        json={"customer_name": "X", "customer_phone": "555-1234",
              "device_make": "A", "device_model": "B"},
    )
    assert resp.status_code == 400


def test_job_patch_status_valid(client, db, staff_token):
    job_id, _ = _make_job(db, phone="+16045559999")
    resp = client.patch(f"/api/v1/jobs/{job_id}",
                        headers=_api_headers(staff_token),
                        json={"status": "diagnosed", "note": "Checked it"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "diagnosed"
    assert len(body["history"]) == 2
    assert body["history"][-1]["new_status"] == "diagnosed"
    assert body["history"][-1]["note"] == "Checked it"


def test_job_patch_status_invalid_transition_422(client, db, staff_token):
    job_id, _ = _make_job(db, phone="+16045550001")
    resp = client.patch(f"/api/v1/jobs/{job_id}",
                        headers=_api_headers(staff_token),
                        json={"status": "ready"})
    assert resp.status_code == 422
    assert resp.get_json()["error"]["code"] == "invalid_transition"


def test_job_patch_invalid_status_value_400(client, db, staff_token):
    job_id, _ = _make_job(db, phone="+16045550002")
    resp = client.patch(f"/api/v1/jobs/{job_id}",
                        headers=_api_headers(staff_token),
                        json={"status": "exploded"})
    assert resp.status_code == 400


def test_job_patch_pricing_recalcs_tax(client, db, staff_token):
    job_id, _ = _make_job(db, phone="+16045550003")
    resp = client.patch(
        f"/api/v1/jobs/{job_id}", headers=_api_headers(staff_token),
        json={"labour_cents": 10000, "parts_cents": 5000},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    # GST 5% + PST 7% of 15000 → 750 + 1050
    assert body["gst_cents"] == 750
    assert body["pst_cents"] == 1050
    assert body["total_cents"] == 15000 + 750 + 1050


def test_job_patch_negative_money_400(client, db, staff_token):
    job_id, _ = _make_job(db, phone="+16045550004")
    resp = client.patch(f"/api/v1/jobs/{job_id}",
                        headers=_api_headers(staff_token),
                        json={"labour_cents": -5})
    assert resp.status_code == 400


def test_technician_cannot_patch_others_job(client, db, tech_token):
    cur = db.execute("INSERT INTO technicians (name) VALUES (?)", ("Other",))
    db.commit()
    job_id, _ = _make_job(db, technician_id=cur.lastrowid,
                          phone="+16045550005")
    resp = client.patch(f"/api/v1/jobs/{job_id}",
                        headers=_api_headers(tech_token),
                        json={"priority": "urgent"})
    assert resp.status_code == 403


def test_technician_cannot_reassign_job(client, db, tech_token):
    tech_id = db.execute(
        "SELECT technician_id FROM admins WHERE username = 'apitech'"
    ).fetchone()["technician_id"]
    job_id, _ = _make_job(db, technician_id=tech_id, phone="+16045550006")
    resp = client.patch(f"/api/v1/jobs/{job_id}",
                        headers=_api_headers(tech_token),
                        json={"technician_id": 999})
    assert resp.status_code == 403


def test_technician_can_update_own_job_status(client, db, tech_token):
    tech_id = db.execute(
        "SELECT technician_id FROM admins WHERE username = 'apitech'"
    ).fetchone()["technician_id"]
    job_id, _ = _make_job(db, technician_id=tech_id, phone="+16045550007")
    resp = client.patch(f"/api/v1/jobs/{job_id}",
                        headers=_api_headers(tech_token),
                        json={"status": "diagnosed"})
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "diagnosed"


# ─────────────────────────────────────────────────────────────────────────────
# Invoices
# ─────────────────────────────────────────────────────────────────────────────

def test_invoice_create_201(client, db, staff_token):
    job_id, cust_id = _make_job(db, phone="+16045550008")
    # Set pricing through PATCH so tax is recalculated like the web UI does.
    resp = client.patch(f"/api/v1/jobs/{job_id}",
                        headers=_api_headers(staff_token),
                        json={"labour_cents": 10000, "parts_cents": 2000})
    assert resp.status_code == 200
    resp = client.post("/api/v1/invoices", headers=_api_headers(staff_token),
                       json={"job_id": job_id, "notes": "test"})
    assert resp.status_code == 201
    body = resp.get_json()
    # subtotal = 12000 + 600 GST + 840 PST = 13440
    assert body["subtotal_cents"] == 13440
    assert body["amount_due_cents"] == 13440
    assert body["status"] == "unpaid"


def test_invoice_create_unknown_job_404(client, staff_token):
    resp = client.post("/api/v1/invoices", headers=_api_headers(staff_token),
                       json={"job_id": 424242})
    assert resp.status_code == 404


def test_invoice_create_too_many_coins_400(client, db, staff_token):
    job_id, _ = _make_job(db, labour_cents=10000, phone="+16045550009")
    resp = client.post("/api/v1/invoices", headers=_api_headers(staff_token),
                       json={"job_id": job_id, "coins_applied": 99999})
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "validation_error"


def test_invoice_list_paginated(client, db, staff_token):
    job_id, _ = _make_job(db, labour_cents=1000, phone="+16045550010")
    for _ in range(3):
        db.execute(
            "INSERT INTO invoices (job_id, customer_id, labour_cents) "
            "SELECT ?, customer_id, 1000 FROM repair_jobs WHERE id = ?",
            (job_id, job_id),
        )
    db.commit()
    resp = client.get("/api/v1/invoices?per_page=2",
                      headers=_api_headers(staff_token))
    body = resp.get_json()
    assert body["total"] == 3
    assert len(body["data"]) == 2


# ─────────────────────────────────────────────────────────────────────────────
# Customers
# ─────────────────────────────────────────────────────────────────────────────

def test_customer_create_201(client, staff_token):
    resp = client.post(
        "/api/v1/customers", headers=_api_headers(staff_token),
        json={"name": "API Cust", "phone": "+16045550011",
              "email": "a@example.com"},
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["name"] == "API Cust"
    assert body["phone"] == "+16045550011"


def test_customer_create_duplicate_phone_409(client, db, staff_token):
    db.execute(
        "INSERT INTO customers (name, phone) VALUES (?, ?)",
        ("Existing", "+16045550012"),
    )
    db.commit()
    resp = client.post(
        "/api/v1/customers", headers=_api_headers(staff_token),
        json={"name": "Dupe", "phone": "+16045550012"},
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"]["code"] == "conflict"


def test_customer_create_bad_phone_400(client, staff_token):
    resp = client.post(
        "/api/v1/customers", headers=_api_headers(staff_token),
        json={"name": "Bad", "phone": "123"},
    )
    assert resp.status_code == 400


def test_customer_detail_404(client, staff_token):
    resp = client.get("/api/v1/customers/98765",
                      headers=_api_headers(staff_token))
    assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Portal timeline
# ─────────────────────────────────────────────────────────────────────────────

def test_portal_timeline_own_jobs(client, db):
    db.execute(
        "INSERT INTO customers (name, phone, password_hash) VALUES (?, ?, ?)",
        ("Portal Cust", "+16045550013", hash_password("portalpass1")),
    )
    cust_id = db.execute(
        "SELECT id FROM customers WHERE phone = '+16045550013'"
    ).fetchone()["id"]
    db.commit()
    _make_job(db, customer_id=cust_id, status="in_repair")
    _make_job(db, customer_id=cust_id, status="ready")
    _make_job(db, phone="+16045550014")  # someone else's job

    status, body = _login(client, phone="+16045550013", password="portalpass1")
    assert status == 200
    resp = client.get("/api/v1/portal/timeline",
                      headers=_api_headers(body["token"]))
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["count"] == 2
    for job in payload["jobs"]:
        assert len(job["history"]) >= 1
        assert job["device"]["make"] == "Apple"


def test_portal_timeline_empty_for_new_customer(client, db, customer_token):
    # customer_token's customer has no jobs
    resp = client.get("/api/v1/portal/timeline",
                      headers=_api_headers(customer_token))
    assert resp.status_code == 200
    assert resp.get_json() == {"jobs": [], "count": 0}
