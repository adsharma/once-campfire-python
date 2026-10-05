"""Per-request accessors (engine is shared; sessions are per request)."""

from flask import current_app, g


def get_engine():
    return current_app.extensions["campfile_engine"]


def get_db():
    return g.db
