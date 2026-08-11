from app.services.crypto import decrypt_passcode, encrypt_passcode


def test_encrypt_decrypt_roundtrip(app):
    with app.app_context():
        ciphertext = encrypt_passcode("1234")
        assert ciphertext != "1234"
        assert decrypt_passcode(ciphertext) == "1234"


def test_encrypt_empty_or_none_returns_none(app):
    with app.app_context():
        assert encrypt_passcode(None) is None
        assert encrypt_passcode("") is None
        assert decrypt_passcode(None) is None


def test_decrypt_falls_back_to_raw_value_on_invalid_token(app):
    with app.app_context():
        # covers legacy plaintext rows from before encryption was added
        assert decrypt_passcode("not-a-real-fernet-token") == "not-a-real-fernet-token"


def test_passcode_is_encrypted_at_rest_and_decrypted_for_display(admin_client, csrf_extractor, db):
    resp = admin_client.get("/admin/jobs/new")
    token = csrf_extractor(resp.get_data(as_text=True))
    resp = admin_client.post("/admin/jobs/new", data={
        "customer_name": "Jane Doe",
        "customer_phone": "+12505550199",
        "device_make": "Apple",
        "device_model": "iPhone 15",
        "device_passcode": "135790",
        "priority": "normal",
        "quoted_cents": "0",
        "csrf_token": token,
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"135790" in resp.data  # decrypted for display on the job page

    row = db.execute("SELECT passcode FROM devices ORDER BY id DESC LIMIT 1").fetchone()
    assert row["passcode"] is not None
    assert row["passcode"] != "135790"  # never stored in plaintext
