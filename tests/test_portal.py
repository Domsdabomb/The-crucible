"""
Tests for the customer portal (app/portal): sign-up (including the
ticket-verification path for claiming an existing staff-created customer
record), login/lockout, dashboard scoping, and the customer-initiated
intake route.
"""


def _signup(client, csrf_extractor, phone, password="password123",
            name="Jane Doe", email=None, ticket=None, confirm=None):
    resp = client.get("/portal/signup")
    token = csrf_extractor(resp.get_data(as_text=True))
    return client.post("/portal/signup", data={
        "name": name,
        "phone": phone,
        "email": email or "",
        "password": password,
        "confirm": confirm if confirm is not None else password,
        "ticket": ticket or "",
        "csrf_token": token,
    })


def _login(client, csrf_extractor, phone, password):
    resp = client.get("/portal/login")
    token = csrf_extractor(resp.get_data(as_text=True))
    return client.post("/portal/login", data={
        "phone": phone, "password": password, "csrf_token": token,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Sign up
# ─────────────────────────────────────────────────────────────────────────────

def test_signup_new_customer_creates_account_and_logs_in(client, csrf_extractor):
    resp = _signup(client, csrf_extractor, "+12505550111")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/portal/")

    with client.session_transaction() as sess:
        assert "customer_id" in sess


def test_signup_requires_matching_password_confirmation(client, csrf_extractor):
    resp = _signup(client, csrf_extractor, "+12505550112", confirm="somethingelse")
    assert b"do not match" in resp.data


def test_signup_new_customer_requires_name(client, csrf_extractor):
    resp = _signup(client, csrf_extractor, "+12505550113", name="")
    assert b"Name is required" in resp.data


def test_signup_existing_customer_without_ticket_is_rejected(client, csrf_extractor, db, admin_client):
    # Staff creates a customer record (via intake) with no portal account yet.
    resp = admin_client.get("/admin/jobs/new")
    token = csrf_extractor(resp.get_data(as_text=True))
    admin_client.post("/admin/jobs/new", data={
        "customer_name": "Walk-in Customer",
        "customer_phone": "+12505550114",
        "device_make": "Apple",
        "device_model": "iPhone 14",
        "priority": "normal",
        "quoted_cents": "0",
        "csrf_token": token,
    })

    resp = _signup(client, csrf_extractor, "+12505550114")
    assert b"already has repair history on file" in resp.data
    with client.session_transaction() as sess:
        assert "customer_id" not in sess


def test_signup_existing_customer_with_wrong_ticket_is_rejected(client, csrf_extractor, admin_client):
    resp = admin_client.get("/admin/jobs/new")
    token = csrf_extractor(resp.get_data(as_text=True))
    admin_client.post("/admin/jobs/new", data={
        "customer_name": "Walk-in Customer",
        "customer_phone": "+12505550115",
        "device_make": "Apple",
        "device_model": "iPhone 14",
        "priority": "normal",
        "quoted_cents": "0",
        "csrf_token": token,
    })

    resp = _signup(client, csrf_extractor, "+12505550115", ticket="999999")
    assert b"doesn&#39;t match" in resp.data or b"doesn't match" in resp.data


def test_signup_existing_customer_with_correct_ticket_claims_account(client, csrf_extractor, admin_client):
    resp = admin_client.get("/admin/jobs/new")
    token = csrf_extractor(resp.get_data(as_text=True))
    resp = admin_client.post("/admin/jobs/new", data={
        "customer_name": "Walk-in Customer",
        "customer_phone": "+12505550116",
        "device_make": "Apple",
        "device_model": "iPhone 14",
        "priority": "normal",
        "quoted_cents": "0",
        "csrf_token": token,
    })
    job_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])

    resp = _signup(client, csrf_extractor, "+12505550116", ticket=str(job_id))
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/portal/")

    # Existing name/history is preserved, not overwritten by the signup form.
    with client.session_transaction() as sess:
        assert sess["customer_name"] == "Walk-in Customer"


def test_signup_rejects_a_phone_that_already_has_a_password(client, csrf_extractor):
    _signup(client, csrf_extractor, "+12505550117")
    client.get("/portal/logout")

    resp = _signup(client, csrf_extractor, "+12505550117")
    assert b"already exists" in resp.data


# ─────────────────────────────────────────────────────────────────────────────
# Login / lockout
# ─────────────────────────────────────────────────────────────────────────────

def test_login_success_and_wrong_password(client, csrf_extractor):
    _signup(client, csrf_extractor, "+12505550118", password="correctpassword1")
    client.get("/portal/logout")

    resp = _login(client, csrf_extractor, "+12505550118", "wrongpassword")
    assert b"Invalid phone number or password" in resp.data
    with client.session_transaction() as sess:
        assert "customer_id" not in sess

    resp = _login(client, csrf_extractor, "+12505550118", "correctpassword1")
    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert "customer_id" in sess


def test_login_against_phone_with_no_account_is_rejected(client, csrf_extractor):
    resp = _login(client, csrf_extractor, "+12505559999", "whatever123")
    assert b"Invalid phone number or password" in resp.data


def test_login_lockout_after_max_failed_attempts(client, csrf_extractor):
    from app.services.customer_auth import MAX_FAILED_LOGIN_ATTEMPTS

    _signup(client, csrf_extractor, "+12505550119", password="correctpassword1")
    client.get("/portal/logout")

    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        _login(client, csrf_extractor, "+12505550119", "wrongpassword")

    resp = _login(client, csrf_extractor, "+12505550119", "correctpassword1")
    assert b"locked" in resp.data
    with client.session_transaction() as sess:
        assert "customer_id" not in sess


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard / job intake
# ─────────────────────────────────────────────────────────────────────────────

def test_dashboard_requires_login(client):
    resp = client.get("/portal/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/portal/login" in resp.headers["Location"]


def test_dashboard_shows_wallet_and_only_own_jobs(client, csrf_extractor):
    _signup(client, csrf_extractor, "+12505550120")
    resp = client.get("/portal/")
    assert resp.status_code == 200
    assert b"0 coins" in resp.data
    assert b"No repairs on file yet" in resp.data


def test_job_new_requires_login(client):
    resp = client.get("/portal/jobs/new", follow_redirects=False)
    assert resp.status_code == 302
    assert "/portal/login" in resp.headers["Location"]


def test_job_new_pins_job_to_the_logged_in_customer(client, csrf_extractor, db):
    _signup(client, csrf_extractor, "+12505550121", name="Portal Customer")

    resp = client.get("/portal/jobs/new")
    token = csrf_extractor(resp.get_data(as_text=True))
    resp = client.post("/portal/jobs/new", data={
        "device_make": "Samsung",
        "device_model": "Galaxy S24",
        "description": "Cracked screen",
        "csrf_token": token,
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Samsung Galaxy S24" in resp.data

    row = db.execute(
        "SELECT rj.id, c.phone FROM repair_jobs rj JOIN customers c ON c.id = rj.customer_id "
        "ORDER BY rj.id DESC LIMIT 1"
    ).fetchone()
    assert row["phone"] == "+12505550121"


def test_job_new_requires_device_make_and_model(client, csrf_extractor):
    _signup(client, csrf_extractor, "+12505550122")
    resp = client.get("/portal/jobs/new")
    token = csrf_extractor(resp.get_data(as_text=True))
    resp = client.post("/portal/jobs/new", data={
        "device_make": "", "device_model": "", "csrf_token": token,
    })
    assert b"Device make is required" in resp.data


# ─────────────────────────────────────────────────────────────────────────────
# Session isolation between admin and customer accounts
# ─────────────────────────────────────────────────────────────────────────────

def test_customer_session_cannot_access_admin_routes(client, csrf_extractor):
    _signup(client, csrf_extractor, "+12505550123")
    resp = client.get("/admin/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_admin_session_cannot_access_portal_dashboard(admin_client):
    # An admin session has no customer_id, so it's bounced to the portal login
    # just like anyone else who isn't a signed-up customer.
    resp = admin_client.get("/portal/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/portal/login" in resp.headers["Location"]
