def test_post_without_csrf_token_is_rejected(client):
    # No prior GET, so no session token exists at all — simulates a forged
    # cross-site request that never loaded a real page on this app.
    resp = client.post("/admin/technicians/new", data={"name": "Nobody"})
    assert resp.status_code == 400


def test_post_with_wrong_csrf_token_is_rejected(admin_client):
    resp = admin_client.post("/admin/technicians/new", data={
        "name": "Nobody", "csrf_token": "not-the-real-token",
    })
    assert resp.status_code == 400


def test_post_with_valid_csrf_token_succeeds(admin_client, csrf_extractor):
    resp = admin_client.get("/admin/technicians")
    token = csrf_extractor(resp.get_data(as_text=True))
    resp = admin_client.post("/admin/technicians/new", data={
        "name": "Alex Tech", "email": "alex@example.com", "phone": "",
        "csrf_token": token,
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Alex Tech" in resp.data


def test_csrf_token_is_stable_across_requests_in_a_session(admin_client, csrf_extractor):
    resp1 = admin_client.get("/admin/technicians")
    resp2 = admin_client.get("/admin/jobs/new")
    token1 = csrf_extractor(resp1.get_data(as_text=True))
    token2 = csrf_extractor(resp2.get_data(as_text=True))
    assert token1 == token2
