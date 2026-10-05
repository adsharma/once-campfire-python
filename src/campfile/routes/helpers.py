"""Shared route helpers."""

from dataclasses import asdict

from flask import jsonify


def present(obj):
    return jsonify(asdict(obj))


def present_list(objs):
    return jsonify([asdict(o) for o in objs])


def error(message, code):
    return jsonify({"error": message}), code


def db_session():
    from flask import g
    return g.db


def actor_or_login():
    """Session user id, else the ?as= bench backdoor, else None."""
    from flask import g, request
    if g.get("user") is not None:
        return g.user.id
    as_user = request.args.get("as", "")
    if as_user.isdigit():
        return int(as_user)
    return None


def login_redirect():
    from flask import redirect
    return redirect("/session/new")
