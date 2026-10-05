"""Per-process store holder (one in-memory store per gunicorn worker)."""

from flask import current_app


def get_store():
    return current_app.extensions["campfile_store"]


def get_index():
    return current_app.extensions["campfire_index"]
