from flask import Blueprint

admin_bp = Blueprint(
    "admin",
    __name__,
    url_prefix="/admin",
    template_folder="../../app/templates",
)

from app.admin import routes  # noqa: E402,F401 — registers routes on the blueprint
