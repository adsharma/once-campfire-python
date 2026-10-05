"""Shared route helpers."""

from dataclasses import asdict

from flask import jsonify


def present(obj):
    return jsonify(asdict(obj))


def present_list(objs):
    return jsonify([asdict(o) for o in objs])


def error(message, code):
    return jsonify({"error": message}), code


def current_uid(args, default):
    try:
        return int(args.get("as", default))
    except ValueError:
        return default


def actor_uid(args, default):
    from flask import g
    if g.get("user") is not None:
        return g.user.id
    return current_uid(args, default)


def actor_or_login(args, default):
    """Session user, else the ?as= bench backdoor, else login redirect."""
    from flask import g, redirect
    if g.get("user") is not None:
        return g.user.id, None
    if "as" in args:
        return current_uid(args, default), None
    return None, redirect("/session/new")


def default_uid():
    from sqlmodel import select

    from .. import state as st
    from ..db import User
    return st.get_db().exec(select(User.__sqlmodel__.id)).first() or 0
