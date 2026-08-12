from app.services.auth import (
    admin_exists, create_admin, get_admin, hash_password, verify_password,
    is_locked, register_failed_login, register_successful_login,
    MAX_FAILED_LOGIN_ATTEMPTS,
)


def test_password_hash_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_password_hash_does_not_contain_plaintext():
    hashed = hash_password("supersecret")
    assert "supersecret" not in hashed


def test_admin_exists_and_create_admin(db):
    assert admin_exists() is False
    create_admin("alice", "password123")
    assert admin_exists() is True

    admin = get_admin("alice")
    assert admin is not None
    assert verify_password("password123", admin["password_hash"])
    assert not verify_password("wrongpassword", admin["password_hash"])


def test_login_required_redirects_unauthenticated_requests(client):
    resp = client.get("/admin/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_setup_then_logout_then_login_flow(client, csrf_extractor):
    resp = client.get("/auth/setup")
    token = csrf_extractor(resp.get_data(as_text=True))
    resp = client.post("/auth/setup", data={
        "username": "bob", "password": "hunter2222", "confirm": "hunter2222",
        "csrf_token": token,
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Dashboard" in resp.data

    client.get("/auth/logout")
    resp = client.get("/admin/", follow_redirects=False)
    assert resp.status_code == 302  # logged out, guard kicks back in

    resp = client.get("/auth/login")
    token = csrf_extractor(resp.get_data(as_text=True))
    resp = client.post("/auth/login", data={
        "username": "bob", "password": "hunter2222", "csrf_token": token,
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Dashboard" in resp.data


def test_login_with_wrong_password_is_rejected(client, csrf_extractor):
    resp = client.get("/auth/setup")
    token = csrf_extractor(resp.get_data(as_text=True))
    client.post("/auth/setup", data={
        "username": "carol", "password": "correcthorse1", "confirm": "correcthorse1",
        "csrf_token": token,
    })
    client.get("/auth/logout")

    resp = client.get("/auth/login")
    token = csrf_extractor(resp.get_data(as_text=True))
    resp = client.post("/auth/login", data={
        "username": "carol", "password": "wrongpassword", "csrf_token": token,
    })
    assert b"Invalid username or password" in resp.data


def test_account_not_locked_below_threshold(db):
    create_admin("dave", "password123")
    admin = get_admin("dave")
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS - 1):
        register_failed_login(admin["id"])
    assert is_locked(get_admin("dave")) is False


def test_account_locks_after_max_failed_attempts(db):
    create_admin("erin", "password123")
    admin = get_admin("erin")
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        register_failed_login(admin["id"])
    assert is_locked(get_admin("erin")) is True


def test_successful_login_resets_lockout_state(db):
    create_admin("frank", "password123")
    admin = get_admin("frank")
    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        register_failed_login(admin["id"])
    assert is_locked(get_admin("frank")) is True

    register_successful_login(admin["id"])
    refreshed = get_admin("frank")
    assert is_locked(refreshed) is False
    assert refreshed["failed_attempts"] == 0


def test_locked_account_rejects_even_correct_password_via_route(client, csrf_extractor):
    resp = client.get("/auth/setup")
    token = csrf_extractor(resp.get_data(as_text=True))
    client.post("/auth/setup", data={
        "username": "grace", "password": "correcthorse1", "confirm": "correcthorse1",
        "csrf_token": token,
    })
    client.get("/auth/logout")

    for _ in range(MAX_FAILED_LOGIN_ATTEMPTS):
        resp = client.get("/auth/login")
        token = csrf_extractor(resp.get_data(as_text=True))
        client.post("/auth/login", data={
            "username": "grace", "password": "wrongpassword", "csrf_token": token,
        })

    resp = client.get("/auth/login")
    token = csrf_extractor(resp.get_data(as_text=True))
    resp = client.post("/auth/login", data={
        "username": "grace", "password": "correcthorse1", "csrf_token": token,
    })
    assert b"locked" in resp.data.lower()
