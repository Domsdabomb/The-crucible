"""SMS provider configuration — SMS_PROVIDER_URL env override."""

import json

from app.services import sms_service


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def _capture_urlopen(monkeypatch, captured: dict):
    def fake_urlopen(req, timeout=10):
        captured["url"] = req.full_url
        return _FakeResponse({"message_id": "test-123"})

    # Runs after the autouse no_network_sms fixture, so this wins.
    monkeypatch.setattr(sms_service.urllib.request, "urlopen", fake_urlopen)


def test_provider_url_env_override(app, monkeypatch):
    captured: dict = {}
    _capture_urlopen(monkeypatch, captured)
    monkeypatch.setenv("SMS_PROVIDER_URL", "https://sms.example.com/v1/send")

    with app.app_context():
        result = sms_service.send_sms("+12505550100", "hello")

    assert result["success"] is True
    assert result["provider_message_id"] == "test-123"
    assert captured["url"] == "https://sms.example.com/v1/send"


def test_provider_url_defaults_to_placeholder(app, monkeypatch):
    captured: dict = {}
    _capture_urlopen(monkeypatch, captured)
    monkeypatch.delenv("SMS_PROVIDER_URL", raising=False)

    with app.app_context():
        result = sms_service.send_sms("+12505550100", "hello")

    assert result["success"] is True
    assert captured["url"] == sms_service._DEFAULT_PROVIDER_URL
