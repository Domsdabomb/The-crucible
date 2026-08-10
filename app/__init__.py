"""
Application factory — The Crucible.
"""

import os
from flask import Flask


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

    # Convenience redirect: / → /login (or /admin/ if already logged in)
    from flask import redirect, url_for, session

    @app.route("/")
    def index():
        if "admin_id" in session:
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("auth.login"))

    return app
