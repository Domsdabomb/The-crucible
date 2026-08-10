"""
Database helpers — thin wrapper around sqlite3.

Usage inside a request:
    db = get_db()
    db.execute(...)

Outside a request (e.g. init_app):
    with app.app_context():
        init_db()
"""

import sqlite3
import os
import click
from flask import current_app, g


def get_db() -> sqlite3.Connection:
    """Return (or create) the per-request DB connection stored in Flask g."""
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DATABASE"],
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
    return g.db


def close_db(e=None) -> None:
    """Close the DB connection at the end of the request."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    """Drop and recreate all tables from schema.sql."""
    db = get_db()
    schema_path = os.path.join(os.path.dirname(__file__), "..", "db", "schema.sql")
    with open(schema_path, "r") as f:
        db.executescript(f.read())


@click.command("init-db")
def init_db_command():
    """CLI: flask init-db — wipe and recreate the schema."""
    init_db()
    click.echo("Database initialised.")


def init_app(app) -> None:
    """Register DB lifecycle hooks with the Flask app."""
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
