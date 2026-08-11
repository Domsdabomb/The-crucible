"""
Application factory — The Crucible.
"""

import os
import secrets
from flask import Flask, abort, request, session


def _get_csrf_token() -> str:
    """Return the per-session CSRF token, generating one on first use."""
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)

    # ── Default config ────────────────────────────────────────────────────────
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-change-in-production"),
        DATABASE=os.path.join(app.instance_path, "crucible.db"),
    )

    if test_config is None:
        app.config.from_pyfile("config.py", silent=True)
    else:
        app.config.from_mapping(test_config)

    # Ensure instance folder exists
    os.makedirs(app.instance_path, exist_ok=True)

    # ── Database ──────────────────────────────────────────────────────────────
    from app import db as db_module
    db_module.init_app(app)

    # ── Blueprints ────────────────────────────────────────────────────────────
    from app.admin import admin_bp
    from app.auth import auth_bp
    app.register_blueprint(admin_bp)
    app.register_blueprint(auth_bp)

    # ── CSRF protection ──────────────────────────────────────────────────────
    # Every form POSTs a hidden csrf_token field; this checks it against the
    # per-session token before any state-changing request is processed.
    app.jinja_env.globals["csrf_token"] = _get_csrf_token

    @app.before_request
    def _csrf_protect():
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            token = session.get("_csrf_token")
            # Form posts carry the token as a field; JSON API callers (this
            # app's routes dual-return JSON per _wants_json()) can't populate
            # request.form, so also accept it as a header.
            submitted = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            if not token or not submitted or not secrets.compare_digest(token, submitted):
                abort(400, "Invalid or missing CSRF token. Please refresh the page and try again.")

    # Convenience redirect: / → /login (or /admin/ if already logged in)
    from flask import redirect, url_for

    @app.route("/")
    def index():
        if "admin_id" in session:
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("auth.login"))

    return app
