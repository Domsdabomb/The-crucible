from app.services.auth import admin_exists, create_admin, get_admin, hash_password, verify_password


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
