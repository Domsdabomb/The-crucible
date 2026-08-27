"""
The rate_limit decorator no-ops under app.testing (see app/services/rate_limit.py
for why), so the rest of the suite never exercises its real enforcement path.
These tests flip app.testing off for the duration of a request context to
verify the decorator's actual counting/expiry/429 behavior in isolation.
"""

import time

import pytest
from werkzeug.exceptions import TooManyRequests

from app.services.rate_limit import _hits, rate_limit


@pytest.fixture(autouse=True)
def _clean_hits():
    _hits.clear()
    yield
    _hits.clear()


def test_allows_requests_under_the_limit(app):
    calls = {"n": 0}

    @rate_limit(max_requests=3, window_seconds=60)
    def limited():
        calls["n"] += 1
        return "ok"

    app.testing = False
    try:
        with app.test_request_context("/", environ_overrides={"REMOTE_ADDR": "1.2.3.4"}):
            for _ in range(3):
                assert limited() == "ok"
        assert calls["n"] == 3
    finally:
        app.testing = True


def test_blocks_once_the_limit_is_exceeded(app):
    @rate_limit(max_requests=3, window_seconds=60)
    def limited():
        return "ok"

    app.testing = False
    try:
        with app.test_request_context("/", environ_overrides={"REMOTE_ADDR": "1.2.3.5"}):
            for _ in range(3):
                limited()
            with pytest.raises(TooManyRequests):
                limited()
    finally:
        app.testing = True


def test_different_ips_get_independent_limits(app):
    @rate_limit(max_requests=1, window_seconds=60)
    def limited():
        return "ok"

    app.testing = False
    try:
        with app.test_request_context("/", environ_overrides={"REMOTE_ADDR": "1.2.3.6"}):
            assert limited() == "ok"
        with app.test_request_context("/", environ_overrides={"REMOTE_ADDR": "1.2.3.7"}):
            assert limited() == "ok"  # different IP, not blocked by the first one's usage
    finally:
        app.testing = True


def test_old_hits_expire_out_of_the_window(app):
    @rate_limit(max_requests=1, window_seconds=0.01)
    def limited():
        return "ok"

    app.testing = False
    try:
        with app.test_request_context("/", environ_overrides={"REMOTE_ADDR": "1.2.3.8"}):
            assert limited() == "ok"
            time.sleep(0.05)  # let the 0.01s window fully elapse
            assert limited() == "ok"
    finally:
        app.testing = True


def test_rate_limit_is_a_noop_under_app_testing(app, client):
    # app.testing is True for the whole suite (see conftest.py's `app` fixture),
    # so hammering a real rate-limited route well past its configured limit
    # must never 429 during tests.
    for _ in range(20):
        resp = client.get("/auth/login")
        assert resp.status_code != 429
