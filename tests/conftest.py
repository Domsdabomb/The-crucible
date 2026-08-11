import re
import urllib.error

import pytest

from app import create_app
from app.db import get_db, init_db


@pytest.fixture
def app(tmp_path):
    application = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "test.db"),
        "SECRET_KEY": "test-secret-key",
    })
    with application.app_context():
        init_db()
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    """A raw DB connection sharing the same app context (and thus the same
    underlying connection) that route handlers see during this test."""
    with app.app_context():
        yield get_db()


@pytest.fixture(autouse=True)
def no_network_sms(monkeypatch):
    """sms_service posts to a placeholder domain; never hit the real network
    in tests regardless of the test machine's DNS/connectivity."""
    def fake_urlopen(*args, **kwargs):
        raise urllib.error.URLError("network disabled in tests")
    monkeypatch.setattr("app.services.sms_service.urllib.request.urlopen", fake_urlopen)


@pytest.fixture
def csrf_extractor():
    def _extract(html: str) -> str:
        match = re.search(r'name="csrf_token" value="([^"]+)"', html)
        assert match, "csrf_token hidden field not found in response HTML"
        return match.group(1)
    return _extract


@pytest.fixture
def admin_client(client, csrf_extractor):
    """A test client that has created the first admin account and is logged in."""
    resp = client.get("/auth/setup")
    token = csrf_extractor(resp.get_data(as_text=True))
    client.post("/auth/setup", data={
        "username": "testadmin",
        "password": "testpassword123",
        "confirm": "testpassword123",
        "csrf_token": token,
    })
    return client
