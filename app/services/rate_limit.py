"""
Minimal in-memory, per-IP rate limiter for public/anonymous endpoints
(/track, /portal/signup, /portal/login, /auth/login).

Not distributed — state lives in a process-local dict, resets on restart,
and isn't shared across multiple worker processes. That's an accepted
tradeoff for a single-shop app with no existing rate-limiting infra; if
this ever runs behind multiple gunicorn workers, swap in Flask-Limiter
with a shared backend (Redis) instead of scaling this up further.
"""

import time
from collections import defaultdict, deque
from functools import wraps

from flask import abort, current_app, request

_hits: dict[str, deque] = defaultdict(deque)


def rate_limit(max_requests: int, window_seconds: int):
    """Decorator: allow at most max_requests per window_seconds per client IP
    per decorated view. Aborts with 429 once the limit is exceeded.

    A no-op when current_app.testing is set: _hits is a process-global dict,
    so without this the test suite's own request volume (many tests hitting
    the same route+loopback-IP combo within the run's short wall-clock
    window) would trip the limiter and fail tests for reasons that have
    nothing to do with what's under test.
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if current_app.testing:
                return f(*args, **kwargs)
            key = f"{f.__module__}.{f.__name__}:{request.remote_addr}"
            now = time.monotonic()
            hits = _hits[key]
            while hits and now - hits[0] > window_seconds:
                hits.popleft()
            if len(hits) >= max_requests:
                abort(429, "Too many requests. Please wait a bit and try again.")
            hits.append(now)
            return f(*args, **kwargs)
        return wrapped
    return decorator
