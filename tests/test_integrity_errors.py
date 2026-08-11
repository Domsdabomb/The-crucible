def _add_technician(admin_client, csrf_extractor, name, email):
    resp = admin_client.get("/admin/technicians")
    token = csrf_extractor(resp.get_data(as_text=True))
    return admin_client.post("/admin/technicians/new", data={
        "name": name, "email": email, "phone": "", "csrf_token": token,
    }, follow_redirects=True)


def test_duplicate_technician_email_does_not_500(admin_client, csrf_extractor):
    resp1 = _add_technician(admin_client, csrf_extractor, "Alex Tech", "dup@example.com")
    assert resp1.status_code == 200
    assert b"Alex Tech" in resp1.data

    resp2 = _add_technician(admin_client, csrf_extractor, "Sam Tech", "dup@example.com")
    assert resp2.status_code == 200  # friendly error page, not a crash
    assert b"already exists" in resp2.data
    assert b"Sam Tech" not in resp2.data  # the conflicting insert was rolled back


def test_technicians_with_distinct_emails_both_succeed(admin_client, csrf_extractor):
    resp1 = _add_technician(admin_client, csrf_extractor, "Alex Tech", "alex@example.com")
    resp2 = _add_technician(admin_client, csrf_extractor, "Sam Tech", "sam@example.com")
    assert b"Alex Tech" in resp1.data
    assert b"Sam Tech" in resp2.data
