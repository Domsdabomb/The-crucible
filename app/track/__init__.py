from flask import Blueprint

track_bp = Blueprint(
    "track",
    __name__,
    url_prefix="/track",
    template_folder="../../app/templates",
)

from app.track import routes  # noqa: E402,F401 — registers routes on the blueprint
