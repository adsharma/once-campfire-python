"""People: profile, user pages, push subscriptions.

JSON mirrors of the Django profile/user_show/push_subscriptions views.
Push endpoints store and list subscriptions; delivery itself needs the
native Web Push implementation and is out of scope (documented).
"""

import time

from flask import Blueprint, jsonify, request

from campfile.db import User
from campfile.domain import campfire as c
from campfile import ops
from campfile.fq import use_db
from campfile.routes.helpers import actor_or_login, db_session, error, login_redirect

bp = Blueprint("people", __name__)


@bp.route("/users/me/profile", methods=["GET", "PATCH", "PUT"])
def profile():
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    use_db(db)
    me = db.get(User.__sqlmodel__, uid)
    if me is None:
        return error("not found", 404)
    if request.method in ("PATCH", "PUT"):
        data = request.get_json(silent=True) or {}
        payload = data.get("user") if isinstance(data.get("user"),
                                                dict) else data
        ops.update_profile(db, me, payload.get("name"), payload.get("bio"),
                           payload.get("email_address"),
                           payload.get("password", ""), int(time.time()))
    from campfile import fq as _fq
    shared, direct = [], []
    mems = (_fq.MembershipQuery([])
                     .where(_fq.pred('membership.user_id == param("uid")'))
                     .project(["membership.id", "membership.room_id",
                               "membership.involvement"])).bind(**({"uid": uid})).rows()
    rids = list({m["room_id"] for m in mems})
    by_room = {}
    if rids:
        in_list = ",".join(str(int(i)) for i in rids)
        for r in (_fq.RoomQuery([])
                           .where(_fq.pred("room.id in [%s]" % in_list))
                           .project(["room.id", "room.name", "room.type"])).rows():
            by_room[r["id"]] = r
    for mem in mems:
        room = by_room.get(mem["room_id"])
        if room is None:
            continue
        entry = {"membership_id": mem["id"], "room_id": room["id"],
                 "room_name": room["name"] or "",
                 "room_kind": ops.TYPE_TO_KIND.get(room["type"], 0),
                 "involvement": mem["involvement"]}
        (direct if room["type"] == "Rooms::Direct"
         else shared).append(entry)
    return jsonify({
        "id": me.id, "name": me.name, "bio": me.bio,
        "email_address": me.email_address, "role": me.role,
        "can_administer": me.role == c.ROLE_ADMIN,
        "shared_memberships": shared, "direct_memberships": direct,
    })


@bp.get("/users/<int:other>")
def user_show(other):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    me = db.get(User.__sqlmodel__, uid)
    row = db.get(User.__sqlmodel__, other)
    if row is None:
        return error("not found", 404)
    return jsonify({
        "id": row.id, "name": row.name, "bio": row.bio, "role": row.role,
        "can_administer": me is not None and me.role == c.ROLE_ADMIN,
    })


@bp.get("/users/me/push_subscriptions")
def push_list():
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    return jsonify([{
        "id": p["id"], "endpoint": p["endpoint"],
        "user_agent": p["user_agent"] or ""} for p in ops.pushsub_list(db, uid)])


@bp.post("/users/me/push_subscriptions")
def push_create():
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    data = request.get_json(silent=True) or {}
    payload = data.get("push_subscription") if isinstance(
        data.get("push_subscription"), dict) else data
    row = ops.pushsub_upsert(db, uid, payload.get("endpoint", ""),
                             payload.get("p256dh_key", ""),
                             payload.get("auth_key", ""),
                             request.headers.get("User-Agent", ""),
                             int(time.time()))
    if row is None:
        return error("endpoint required", 422)
    return jsonify({"id": row.id, "endpoint": row.endpoint})


@bp.delete("/users/me/push_subscriptions/<int:sid>")
def push_delete(sid):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    if not ops.pushsub_delete(db, uid, sid):
        return error("not found", 404)
    return jsonify({"deleted": sid})


@bp.post("/users/me/push_subscriptions/<int:sid>/test_notifications")
def push_test(sid):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    found = [p for p in ops.pushsub_list(db, uid) if p["id"] == sid]
    if not found:
        return error("not found", 404)
    # Delivery needs the native Web Push implementation (out of scope).
    return error("push delivery not implemented", 501)
