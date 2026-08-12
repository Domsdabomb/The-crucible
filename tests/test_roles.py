"""
Role separation: 'admin' has full access; 'technician' can only view/update
jobs assigned to their own technicians row (see app/admin/routes._can_access_job
and app/services/auth.admin_required).

These tests need two independent sessions against the same app (one admin,
one technician), so they build clients directly from the `app` fixture
instead of the shared `admin_client` fixture (which is a single client).
"""


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


def test_technician_can_access_own_job_but_not_others(app, db, csrf_extractor):
    admin = _setup_admin(app, csrf_extractor)
    tech_id = _create_technician(admin, db, csrf_extractor, "Alex Tech", "alex@example.com")
    _create_technician_login(admin, csrf_extractor, tech_id, "alexlogin")

    owned_job_id = _create_job(admin, csrf_extractor, "+12505550201", technician_id=tech_id)
    other_job_id = _create_job(admin, csrf_extractor, "+12505550202")  # unassigned

    tech = app.test_client()
    resp = _login(tech, csrf_extractor, "alexlogin", "techpassword1")
    assert resp.status_code == 200

    assert tech.get(f"/admin/jobs/{owned_job_id}").status_code == 200
    assert tech.get(f"/admin/jobs/{other_job_id}").status_code == 403


def test_technician_job_list_is_forced_filtered_to_own_jobs(app, db, csrf_extractor):
    admin = _setup_admin(app, csrf_extractor)
    tech_id = _create_technician(admin, db, csrf_extractor, "Blake Tech", "blake@example.com")
    _create_technician_login(admin, csrf_extractor, tech_id, "blakelogin")

    owned_job_id = _create_job(admin, csrf_extractor, "+12505550203", technician_id=tech_id)
    other_job_id = _create_job(admin, csrf_extractor, "+12505550204")

    tech = app.test_client()
    _login(tech, csrf_extractor, "blakelogin", "techpassword1")

    # Even trying to override the filter via query string is ignored server-side.
    other_tech_id = _create_technician(admin, db, csrf_extractor, "Casey Tech", "casey@example.com")
    resp = tech.get(f"/admin/jobs?tech_id={other_tech_id}")
    assert resp.status_code == 200
    assert f"#{owned_job_id}".encode() in resp.data
    assert f"#{other_job_id}".encode() not in resp.data


def test_technician_can_update_status_and_add_parts_on_own_job(app, db, csrf_extractor):
    admin = _setup_admin(app, csrf_extractor)
    tech_id = _create_technician(admin, db, csrf_extractor, "Drew Tech", "drew@example.com")
    _create_technician_login(admin, csrf_extractor, tech_id, "drewlogin")
    job_id = _create_job(admin, csrf_extractor, "+12505550205", technician_id=tech_id)

    tech = app.test_client()
    _login(tech, csrf_extractor, "drewlogin", "techpassword1")

    resp = tech.get(f"/admin/jobs/{job_id}")
    token = csrf_extractor(resp.get_data(as_text=True))
    resp = tech.post(f"/admin/jobs/{job_id}/status", data={
        "status": "diagnosed", "changed_by": "drewlogin", "csrf_token": token,
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"badge-diagnosed" in resp.data

    resp = tech.get(f"/admin/jobs/{job_id}")
    token = csrf_extractor(resp.get_data(as_text=True))
    resp = tech.post(f"/admin/jobs/{job_id}/parts/add", data={
        "name": "Screen", "cost_cents": "5000", "csrf_token": token,
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Screen" in resp.data


def test_technician_cannot_update_status_or_add_parts_on_others_job(app, db, csrf_extractor):
    admin = _setup_admin(app, csrf_extractor)
    tech_id = _create_technician(admin, db, csrf_extractor, "Emery Tech", "emery@example.com")
    _create_technician_login(admin, csrf_extractor, tech_id, "emerylogin")
    other_job_id = _create_job(admin, csrf_extractor, "+12505550206")  # unassigned

    tech = app.test_client()
    _login(tech, csrf_extractor, "emerylogin", "techpassword1")

    # The CSRF token must come from the technician's own session. job_list.html
    # has no POST form so it never renders one; /auth/login always does and
    # renders regardless of login state (the token is session-stable either way).
    resp = tech.get("/auth/login")
    token = csrf_extractor(resp.get_data(as_text=True))

    resp = tech.post(f"/admin/jobs/{other_job_id}/status", data={
        "status": "diagnosed", "changed_by": "emerylogin", "csrf_token": token,
    })
    assert resp.status_code == 403

    resp = tech.post(f"/admin/jobs/{other_job_id}/parts/add", data={
        "name": "Screen", "cost_cents": "5000", "csrf_token": token,
    })
    assert resp.status_code == 403


def test_technician_gets_403_on_admin_only_pages(app, db, csrf_extractor):
    admin = _setup_admin(app, csrf_extractor)
    tech_id = _create_technician(admin, db, csrf_extractor, "Finley Tech", "finley@example.com")
    _create_technician_login(admin, csrf_extractor, tech_id, "finleylogin")

    tech = app.test_client()
    _login(tech, csrf_extractor, "finleylogin", "techpassword1")

    for path in (
        "/admin/", "/admin/customers", "/admin/technicians",
        "/admin/sms-log", "/admin/invoices", "/admin/wallets", "/admin/jobs/new",
    ):
        resp = tech.get(path)
        assert resp.status_code == 403, f"{path} should 403 for a technician account"


def test_technician_root_redirect_goes_to_job_list_not_dashboard(app, db, csrf_extractor):
    admin = _setup_admin(app, csrf_extractor)
    tech_id = _create_technician(admin, db, csrf_extractor, "Gray Tech", "gray@example.com")
    _create_technician_login(admin, csrf_extractor, tech_id, "graylogin")

    tech = app.test_client()
    _login(tech, csrf_extractor, "graylogin", "techpassword1")

    resp = tech.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].rstrip("/").endswith("/admin/jobs")


def test_admin_root_redirect_still_goes_to_dashboard(app, csrf_extractor):
    admin = _setup_admin(app, csrf_extractor)
    resp = admin.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].rstrip("/").endswith("/admin")


def test_cannot_create_a_second_login_for_the_same_technician(app, db, csrf_extractor):
    admin = _setup_admin(app, csrf_extractor)
    tech_id = _create_technician(admin, db, csrf_extractor, "Harper Tech", "harper@example.com")
    _create_technician_login(admin, csrf_extractor, tech_id, "harperlogin")

    resp = admin.get(f"/admin/technicians/{tech_id}/create-login", follow_redirects=True)
    assert b"already has a login" in resp.data

    count = db.execute(
        "SELECT COUNT(*) AS n FROM admins WHERE technician_id = ?", (tech_id,)
    ).fetchone()["n"]
    assert count == 1


def test_duplicate_username_on_technician_login_does_not_500(app, db, csrf_extractor):
    admin = _setup_admin(app, csrf_extractor, username="dupetest")
    tech_id = _create_technician(admin, db, csrf_extractor, "Ivy Tech", "ivy@example.com")

    resp = _create_technician_login(admin, csrf_extractor, tech_id, "dupetest")  # same as admin's username
    assert resp.status_code == 200
    assert b"already taken" in resp.data
