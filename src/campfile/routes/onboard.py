"""Onboarding: welcome, first run, join by code.

JSON mirrors of the Django welcome/first_run/join views. Signed transfer
URLs need the Rails crypto helpers and are out of scope; password login
covers the same flow.
"""

import time

from flask import Blueprint, jsonify, redirect, request
from sqlmodel import select

from campfile.db import Account, Room, User
from campfile.domain import campfire as c
from campfile import ops
from campfile.routes import session as session_routes
from campfile.routes.helpers import actor_or_login, db_session, error, login_redirect

bp = Blueprint("onboard", __name__)


@bp.get("/")
def welcome():
    db = db_session()
    if ops.account_row(db) is None:
        return redirect("/first_run")
    uid = actor_or_login()
    if uid is None:
        return redirect("/session/new")
    R = Room.__sqlmodel__
    from campfile.db import Membership
    M = Membership.__sqlmodel__
    first = db.exec(select(R).join(
        M, M.room_id == R.id).where(
            M.user_id == uid).order_by(R.created_at).limit(1)).all()
    if first:
        return redirect("/rooms/%d" % first[0].id)
    return jsonify({"welcome": True})


@bp.route("/first_run", methods=["GET", "POST"])
def first_run():
    db = db_session()
    if ops.account_row(db) is not None:
        return redirect("/")
    if request.method == "GET":
        return jsonify({"first_run": True})
    data = request.get_json(silent=True) or {}
    payload = data.get("user") if isinstance(data.get("user"),
                                            dict) else data
    name = (payload.get("name") or "").strip()
    email = (payload.get("email_address") or "").strip()
    password = payload.get("password", "")
    if not name or not email or not password:
        return error("name, email and password required", 422)
    now = int(time.time())
    _account, user, _room = ops.first_run_create(db, name, email,
                                                password, now)
    token = session_routes.issue_session(
        db, user.id, request.remote_addr or "",
        request.headers.get("User-Agent", ""), now)
    return session_routes.session_cookie(
        jsonify({"id": user.id, "name": user.name}), token), 201


@bp.route("/join/<code>", methods=["GET", "POST"])
def join(code):
    db = db_session()
    account = ops.account_row(db)
    if account is None or account.join_code != code:
        return error("not found", 404)
    uid = actor_or_login()
    if uid is not None:
        return redirect("/")
    if request.method == "GET":
        return jsonify({"join_code": code})
    data = request.get_json(silent=True) or {}
    payload = data.get("user") if isinstance(data.get("user"),
                                            dict) else data
    name = (payload.get("name") or "").strip()
    email = (payload.get("email_address") or "").strip()
    password = payload.get("password", "")
    if not name or not email or not password:
        return error("name, email and password required", 422)
    now = int(time.time())
    user = ops.create_user(db, name, email, password, c.ROLE_MEMBER, "",
                           now)
    if user is None:
        return error("email already taken", 422)
    token = session_routes.issue_session(
        db, user.id, request.remote_addr or "",
        request.headers.get("User-Agent", ""), now)
    return session_routes.session_cookie(
        jsonify({"id": user.id, "name": user.name}), token), 201
