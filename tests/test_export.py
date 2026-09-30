"""CSV exports (jobs, invoices) and the PWA manifest.

Covers: admin jobs export shape/content, filter honoring, technician
scoping (fail-closed to own jobs), anonymous redirect, invoice export
permissions (admin-only), and the static web manifest.
"""

import json


# ── helpers (mirrors tests/test_roles.py — module-local there) ──────────────

def _setup_admin(app, csrf_extractor, username="boss", password="bosspassword1"):
    client = app.test_client()
    resp = client.get("/auth/setup")
    token = csrf_extractor(resp.get_data(as_text=True))
    client.post("/auth/setup", data={
        "username": username, "password": password, "confirm": password,
        "csrf_token": token,
    })
    return client


def _create_technician(admin, db, csrf_extractor, name, email):
    resp = admin.get("/admin/technicians")
    token = csrf_extractor(resp.get_data(as_text=True))
    admin.post("/admin/technicians/new", data={
        "name": name, "email": email, "phone": "", "csrf_token": token,
    })
    return db.execute("SELECT id FROM technicians WHERE email = ?", (email,)).fetchone()["id"]


def _create_technician_login(admin, csrf_extractor, tech_id, username, password="techpassword1"):
    resp = admin.get(f"/admin/technicians/{tech_id}/create-login")
    token = csrf_extractor(resp.get_data(as_text=True))
    return admin.post(f"/admin/technicians/{tech_id}/create-login", data={
        "username": username, "password": password, "confirm": password,
        "csrf_token": token,
    })


def _login(client, csrf_extractor, username, password):
    resp = client.get("/auth/login")
    token = csrf_extractor(resp.get_data(as_text=True))
    return client.post("/auth/login", data={
        "username": username, "password": password, "csrf_token": token,
    }, follow_redirects=True)


def _create_job(admin, csrf_extractor, phone, technician_id=None):
    resp = admin.get("/admin/jobs/new")
    token = csrf_extractor(resp.get_data(as_text=True))
    data = {
        "customer_name": "Job Customer", "customer_phone": phone,
        "device_make": "Apple", "device_model": "iPhone 15",
        "priority": "normal", "quoted_cents": "0", "csrf_token": token,
    }
    if technician_id is not None:
        data["technician_id"] = str(technician_id)
    resp = admin.post("/admin/jobs/new", data=data)
    return int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


def _set_job_status(admin, csrf_extractor, job_id, status):
    resp = admin.get(f"/admin/jobs/{job_id}")
    token = csrf_extractor(resp.get_data(as_text=True))
    return admin.post(f"/admin/jobs/{job_id}/status", data={
        "status": status, "csrf_token": token,
    })


def _create_invoice(admin, csrf_extractor, job_id):
    resp = admin.get(f"/admin/jobs/{job_id}/invoice/new")
    token = csrf_extractor(resp.get_data(as_text=True))
    resp = admin.post(f"/admin/jobs/{job_id}/invoice/new", data={
        "coins_applied": "0", "notes": "", "csrf_token": token,
    })
    return int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


# ── jobs export ─────────────────────────────────────────────────────────────

def test_jobs_export_admin(app, csrf_extractor):
    admin = _setup_admin(app, csrf_extractor)
    job_id = _create_job(admin, csrf_extractor, "+12505550301")

    resp = admin.get("/admin/jobs/export.csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["Content-Type"]
    assert "attachment" in resp.headers["Content-Disposition"]
    assert "jobs-export-" in resp.headers["Content-Disposition"]

    body = resp.get_data(as_text=True)
    lines = body.strip().splitlines()
    assert lines[0] == (
        "job_id,status,priority,customer_name,customer_phone,device_make,"
        "device_model,technician,created_at,promised_date,labour,parts,gst,"
        "pst,total"
    )
    assert len(lines) == 2  # header + the one job
    assert lines[1].startswith(f"{job_id},received,normal,Job Customer,+12505550301,Apple,iPhone 15,")
    assert lines[1].endswith(",0.00,0.00,0.00,0.00,0.00")  # money in dollars


def test_jobs_export_honors_status_filter(app, csrf_extractor):
    admin = _setup_admin(app, csrf_extractor)
    received_id = _create_job(admin, csrf_extractor, "+12505550302")
    diagnosed_id = _create_job(admin, csrf_extractor, "+12505550303")
    assert _set_job_status(admin, csrf_extractor, diagnosed_id, "diagnosed").status_code == 302

    resp = admin.get("/admin/jobs/export.csv?status=received")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    data_lines = body.strip().splitlines()[1:]
    assert any(l.startswith(f"{received_id},") for l in data_lines)
    assert not any(l.startswith(f"{diagnosed_id},") for l in data_lines)


def test_jobs_export_technician_sees_only_own_jobs(app, db, csrf_extractor):
    admin = _setup_admin(app, csrf_extractor)
    tech_id = _create_technician(admin, db, csrf_extractor, "CSV Tech", "csvtech@example.com")
    _create_technician_login(admin, csrf_extractor, tech_id, "csvlogin")

    owned_id = _create_job(admin, csrf_extractor, "+12505550304", technician_id=tech_id)
    other_id = _create_job(admin, csrf_extractor, "+12505550305")

    tech = app.test_client()
    _login(tech, csrf_extractor, "csvlogin", "techpassword1")

    resp = tech.get("/admin/jobs/export.csv")
    assert resp.status_code == 200
    data_lines = resp.get_data(as_text=True).strip().splitlines()[1:]
    assert any(l.startswith(f"{owned_id},") for l in data_lines)
    assert not any(l.startswith(f"{other_id},") for l in data_lines)


def test_jobs_export_anonymous_redirects_to_login(app):
    resp = app.test_client().get("/admin/jobs/export.csv")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


# ── invoices export ─────────────────────────────────────────────────────────

def test_invoices_export_admin(app, csrf_extractor):
    admin = _setup_admin(app, csrf_extractor)
    job_id = _create_job(admin, csrf_extractor, "+12505550306")
    invoice_id = _create_invoice(admin, csrf_extractor, job_id)

    resp = admin.get("/admin/invoices/export.csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["Content-Type"]
    assert "attachment" in resp.headers["Content-Disposition"]
    assert "invoices-export-" in resp.headers["Content-Disposition"]

    body = resp.get_data(as_text=True)
    lines = body.strip().splitlines()
    assert lines[0] == (
        "invoice_id,status,customer_name,customer_phone,job_id,created_at,"
        "paid_at,labour,parts,gst,pst,subtotal,coins_applied,discount,amount_due"
    )
    assert len(lines) == 2
    assert lines[1].startswith(f"{invoice_id},unpaid,Job Customer,+12505550306,{job_id},")
    assert ",0,0.00,0.00" in lines[1]  # coins_applied, discount, amount_due


def test_invoices_export_technician_forbidden(app, db, csrf_extractor):
    admin = _setup_admin(app, csrf_extractor)
    tech_id = _create_technician(admin, db, csrf_extractor, "Inv Tech", "invtech@example.com")
    _create_technician_login(admin, csrf_extractor, tech_id, "invlogin")

    tech = app.test_client()
    _login(tech, csrf_extractor, "invlogin", "techpassword1")

    resp = tech.get("/admin/invoices/export.csv")
    assert resp.status_code == 403


def test_invoices_export_anonymous_redirects_to_login(app):
    resp = app.test_client().get("/admin/invoices/export.csv")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


# ── PWA manifest ────────────────────────────────────────────────────────────

def test_manifest_served_as_json(app):
    resp = app.test_client().get("/static/manifest.webmanifest")
    assert resp.status_code == 200
    manifest = json.loads(resp.get_data(as_text=True))
    assert manifest["name"] == "The Crucible"
    assert manifest["short_name"] == "Crucible"
    assert manifest["display"] == "standalone"
    assert manifest["theme_color"] == "#1a1a2e"
    assert manifest["icons"][0]["src"] == "icon.svg"
