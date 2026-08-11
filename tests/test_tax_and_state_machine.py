from app.admin.routes import ALLOWED_TRANSITIONS, VALID_STATUSES, _calc_tax


def test_calc_tax_matches_documented_bc_rates():
    # GST 5%, PST 7% of (labour + parts) — see CLAUDE.md "Key Business Logic"
    gst, pst = _calc_tax(labour_cents=10050, parts_cents=5000)
    taxable = 10050 + 5000
    assert gst == round(taxable * 0.05)
    assert pst == round(taxable * 0.07)


def test_calc_tax_zero_amounts():
    assert _calc_tax(0, 0) == (0, 0)


def test_every_status_has_a_transitions_entry():
    assert set(ALLOWED_TRANSITIONS.keys()) == set(VALID_STATUSES)


def test_closed_is_a_terminal_state():
    assert ALLOWED_TRANSITIONS["closed"] == set()


def test_every_transition_target_is_a_valid_status():
    for status, targets in ALLOWED_TRANSITIONS.items():
        for target in targets:
            assert target in VALID_STATUSES, f"{status!r} -> {target!r} is not a real status"


def test_illegal_status_transition_returns_422(admin_client, csrf_extractor):
    resp = admin_client.get("/admin/jobs/new")
    token = csrf_extractor(resp.get_data(as_text=True))
    resp = admin_client.post("/admin/jobs/new", data={
        "customer_name": "Jane Doe",
        "customer_phone": "+12505550123",
        "device_make": "Apple",
        "device_model": "iPhone 15",
        "priority": "normal",
        "quoted_cents": "0",
        "csrf_token": token,
    })
    job_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])

    resp = admin_client.get(f"/admin/jobs/{job_id}")
    token = csrf_extractor(resp.get_data(as_text=True))
    # a fresh job is 'received'; 'received' -> 'picked_up' is not an allowed jump
    resp = admin_client.post(f"/admin/jobs/{job_id}/status", data={
        "status": "picked_up", "changed_by": "tester", "csrf_token": token,
    })
    assert resp.status_code == 422


def test_legal_status_transition_succeeds(admin_client, csrf_extractor):
    resp = admin_client.get("/admin/jobs/new")
    token = csrf_extractor(resp.get_data(as_text=True))
    resp = admin_client.post("/admin/jobs/new", data={
        "customer_name": "Jane Doe",
        "customer_phone": "+12505550124",
        "device_make": "Apple",
        "device_model": "iPhone 15",
        "priority": "normal",
        "quoted_cents": "0",
        "csrf_token": token,
    })
    job_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])

    resp = admin_client.get(f"/admin/jobs/{job_id}")
    token = csrf_extractor(resp.get_data(as_text=True))
    resp = admin_client.post(f"/admin/jobs/{job_id}/status", data={
        "status": "diagnosed", "changed_by": "tester", "csrf_token": token,
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"badge-diagnosed" in resp.data
