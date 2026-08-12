def _create_job(admin_client, csrf_extractor, phone):
    resp = admin_client.get("/admin/jobs/new")
    token = csrf_extractor(resp.get_data(as_text=True))
    resp = admin_client.post("/admin/jobs/new", data={
        "customer_name": "Track Test Customer",
        "customer_phone": phone,
        "device_make": "Apple",
        "device_model": "iPhone 15",
        "priority": "normal",
        "quoted_cents": "5000",
        "csrf_token": token,
    })
    return int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])


def test_track_requires_no_login(client):
    resp = client.get("/track/")
    assert resp.status_code == 200
    assert b"Track Your Repair" in resp.data


def test_track_with_correct_phone_and_ticket_shows_job(admin_client, csrf_extractor):
    job_id = _create_job(admin_client, csrf_extractor, "+12505550188")

    # The public tracker doesn't share the admin session's login state.
    resp = admin_client.get("/track/")
    token = csrf_extractor(resp.get_data(as_text=True))
    resp = admin_client.post("/track/", data={
        "phone": "+12505550188", "ticket": str(job_id), "csrf_token": token,
    })
    assert resp.status_code == 200
    assert f"Ticket #{job_id}".encode() in resp.data
    assert b"iPhone 15" in resp.data


def test_track_with_wrong_phone_shows_no_match(admin_client, csrf_extractor):
    job_id = _create_job(admin_client, csrf_extractor, "+12505550189")

    resp = admin_client.get("/track/")
    token = csrf_extractor(resp.get_data(as_text=True))
    resp = admin_client.post("/track/", data={
        "phone": "+12505550199", "ticket": str(job_id), "csrf_token": token,
    })
    assert resp.status_code == 200
    assert b"No matching repair found" in resp.data
    assert b"iPhone 15" not in resp.data


def test_track_with_invalid_phone_format_is_rejected(client, csrf_extractor):
    resp = client.get("/track/")
    token = csrf_extractor(resp.get_data(as_text=True))
    resp = client.post("/track/", data={
        "phone": "not-a-phone", "ticket": "1", "csrf_token": token,
    })
    assert resp.status_code == 200
    assert b"Enter a valid phone number" in resp.data


def test_track_does_not_expose_passcode(admin_client, csrf_extractor):
    resp = admin_client.get("/admin/jobs/new")
    token = csrf_extractor(resp.get_data(as_text=True))
    resp = admin_client.post("/admin/jobs/new", data={
        "customer_name": "Passcode Test",
        "customer_phone": "+12505550190",
        "device_make": "Apple",
        "device_model": "iPhone 15",
        "device_passcode": "998877",
        "priority": "normal",
        "quoted_cents": "0",
        "csrf_token": token,
    })
    job_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])

    resp = admin_client.get("/track/")
    token = csrf_extractor(resp.get_data(as_text=True))
    resp = admin_client.post("/track/", data={
        "phone": "+12505550190", "ticket": str(job_id), "csrf_token": token,
    })
    assert b"998877" not in resp.data
