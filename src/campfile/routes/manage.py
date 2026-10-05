"""Room/message management: CRUD, refresh, involvement, boosts, autocomplete.

JSON mirrors of the Django room_form/refresh/involvement/boosts/messages
views. Same paths, same authz (admin-or-creator via can_administer,
involvement allow-lists, 16-char boosts), JSON bodies instead of pages
and turbo streams.
"""

import time

from flask import Blueprint, jsonify, request
from sqlmodel import select

from campfile import queries as q
from campfile.db import Membership, Message, User
from campfile.domain import campfire as c
from campfile import ops
from campfile.routes.helpers import actor_or_login, db_session, error, login_redirect, present, present_list

bp = Blueprint("manage", __name__)

KINDS = {"opens": c.ROOM_OPEN, "closeds": c.ROOM_CLOSED,
         "directs": c.ROOM_DIRECT}


def _payload(request_json):
    data = request.get_json(silent=True) or {}
    if "room" in data and isinstance(data["room"], dict):
        data = data["room"]
    return data


@bp.get("/rooms/<kind>/new")
def room_new_form(kind):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    if kind not in KINDS:
        return error("not found", 404)
    return jsonify({"kind": kind, "members": _user_list()})


@bp.post("/rooms/<kind>")
def room_create(kind):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    if kind not in KINDS:
        return error("not found", 404)
    db = db_session()
    me = db.get(User.__sqlmodel__, uid)
    if kind != "directs":
        account = ops.account_row(db)
        settings = q.account_settings(account)
        if (settings.get("restrict_room_creation_to_administrators")
                and me.role != c.ROLE_ADMIN):
            return error("forbidden", 403)
    data = _payload(request.json)
    name = (data.get("name") or "").strip()
    ids = data.get("user_ids", [])
    ids = [int(i) for i in ids if str(i).isdigit()]
    if kind == "directs":
        ids = list(set(ids) | {uid})
    elif kind != "opens":
        ids = list(set(ids) | {uid})
        if not name:
            return error("name required", 422)
    else:
        actives = [u.id for u in db.exec(select(User.__sqlmodel__).where(
            User.__sqlmodel__.status == 0)).all()]
        ids = actives
        if not name:
            return error("name required", 422)
    room = ops.create_room(db, KINDS[kind], name or None, uid, ids,
                           int(time.time()))
    res = q.room_page(db, room.id, uid)
    if not res.ok:
        return error("not found", 404)
    return present(res.value), 201


def _room_kind_or_404(room, kind):
    want = "Rooms::" + kind[:-1].capitalize()
    return room.type == want


@bp.get("/rooms/<kind>/<int:rid>/edit")
def room_edit_form(kind, rid):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    room, _mem = ops.room_access(db, uid, rid)
    if room is None or not _room_kind_or_404(room, kind):
        return error("not found", 404)
    return jsonify({"id": rid, "name": room.name, "kind": kind})


@bp.route("/rooms/<kind>/<int:rid>", methods=["PATCH", "PUT"])
def room_update(kind, rid):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    room, _mem = ops.room_access(db, uid, rid)
    if room is None or not _room_kind_or_404(room, kind):
        return error("not found", 404)
    me = db.get(User.__sqlmodel__, uid)
    if not c.can_administer(me.role, uid, room.creator_id, False):
        return error("forbidden", 403)
    data = _payload(request.json)
    rkind = ops.TYPE_TO_KIND.get(room.type, c.ROOM_OPEN)
    ids = data.get("user_ids", [])
    ids = [int(i) for i in ids if str(i).isdigit()]
    is_open = room.type == "Rooms::Open"
    ops.revise_room(db, room, (data.get("name") or room.name or ""),
                    rkind, ids, is_open, int(time.time()))
    res = q.room_page(db, rid, uid)
    if not res.ok:
        return error("not found", 404)
    return present(res.value)


def _destroy_room(db, uid, rid):
    room, _mem = ops.room_access(db, uid, rid)
    if room is None:
        return error("not found", 404)
    me = db.get(User.__sqlmodel__, uid)
    if (room.type != "Rooms::Direct"
            and not c.can_administer(me.role, uid, room.creator_id, False)):
        return error("forbidden", 403)
    ops.delete_room_cascade(db, rid)
    return jsonify({"deleted": rid})


@bp.delete("/rooms/<kind>/<int:rid>")
def room_delete_kind(kind, rid):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    if kind not in KINDS:
        return error("not found", 404)
    return _destroy_room(db_session(), uid, rid)


@bp.delete("/rooms/<int:rid>")
def room_delete(rid):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    return _destroy_room(db_session(), uid, rid)


@bp.get("/rooms/<int:rid>/refresh")
def refresh(rid):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    try:
        since = float(request.args.get("since", 0)) / 1000.0
    except ValueError:
        since = time.time()
    from campfile.db import to_db_time
    stamp = to_db_time(int(since))
    db = db_session()
    room, _mem = ops.room_access(db, uid, rid)
    if room is None:
        return error("not found", 404)
    M = Message.__sqlmodel__
    new_rows = db.exec(select(M).where(
        M.room_id == rid, M.created_at > stamp
    ).order_by(M.created_at).limit(40)).all()
    new_ids = [m.id for m in new_rows]
    upd_rows = db.exec(select(M).where(
        M.room_id == rid, M.updated_at > stamp
    ).order_by(M.created_at.desc()).limit(40)).all()
    upd_rows = [m for m in upd_rows if m.id not in set(new_ids)]
    upd_rows.reverse()
    import dataclasses
    return jsonify({
        "new": [dataclasses.asdict(v) for v in q.views_for(db, list(new_rows))],
        "updated": [dataclasses.asdict(v) for v in q.views_for(db, upd_rows)],
    })


@bp.route("/rooms/<int:rid>/involvement", methods=["GET", "PUT", "PATCH"])
@bp.route("/rooms/<int:rid>/settings", methods=["GET", "PUT", "PATCH"])
def involvement(rid):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    room, mem = ops.room_access(db, uid, rid)
    if room is None or mem is None:
        return error("not found", 404)
    if request.method in ("PUT", "PATCH"):
        data = request.get_json(silent=True) or {}
        choice = (data.get("involvement")
                  or request.args.get("involvement") or "")
        allowed = (["everything", "nothing"]
                   if room.type == "Rooms::Direct"
                   else ["mentions", "everything", "nothing", "invisible"])
        if choice not in allowed:
            return error("invalid involvement", 422)
        ops.set_involvement(db, mem, choice, int(time.time()))
        db.refresh(mem)
    return jsonify({"room_id": rid, "involvement": mem.involvement})


@bp.get("/rooms/<int:rid>/messages/<int:mid>")
def message_show(rid, mid):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    room, _mem = ops.room_access(db, uid, rid)
    if room is None:
        return error("not found", 404)
    row = db.get(Message.__sqlmodel__, mid)
    if row is None or row.room_id != rid:
        return error("not found", 404)
    return present(q.views_for(db, [row])[0])


@bp.route("/rooms/<int:rid>/messages/<int:mid>", methods=["PATCH", "PUT"])
def message_update(rid, mid):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    room, _mem = ops.room_access(db, uid, rid)
    if room is None:
        return error("not found", 404)
    row = db.get(Message.__sqlmodel__, mid)
    if row is None or row.room_id != rid:
        return error("not found", 404)
    me = db.get(User.__sqlmodel__, uid)
    if not c.can_administer(me.role, uid, row.creator_id, False):
        return error("forbidden", 403)
    data = request.get_json(silent=True) or {}
    body = data.get("body", data.get("message", {}).get("body")
                    if isinstance(data.get("message"), dict) else None)
    if body is None:
        return error("body required", 422)
    ops.update_message_body(db, mid, body, int(time.time()))
    return present(q.views_for(db, [db.get(
        Message.__sqlmodel__, mid)])[0])


@bp.delete("/rooms/<int:rid>/messages/<int:mid>")
def message_delete(rid, mid):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    room, _mem = ops.room_access(db, uid, rid)
    if room is None:
        return error("not found", 404)
    row = db.get(Message.__sqlmodel__, mid)
    if row is None or row.room_id != rid:
        return error("not found", 404)
    me = db.get(User.__sqlmodel__, uid)
    if not c.can_administer(me.role, uid, row.creator_id, False):
        return error("forbidden", 403)
    ops.delete_message_cascade(db, mid)
    return "", 204


@bp.get("/messages/<int:mid>/boosts")
def boost_list(mid):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    row = db.get(Message.__sqlmodel__, mid)
    if row is None:
        return error("not found", 404)
    _room, mem = ops.room_access(db, uid, row.room_id)
    if mem is None:
        return error("not found", 404)
    from sqlmodel import select as _select
    from campfile.db import Boost as _B
    boosts = db.exec(_select(_B.__sqlmodel__).where(
        _B.__sqlmodel__.message_id == mid)).all()
    return jsonify([{"id": b.id, "content": b.content,
                     "booster_id": b.booster_id} for b in boosts])


@bp.post("/messages/<int:mid>/boosts")
def boost_create(mid):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    row = db.get(Message.__sqlmodel__, mid)
    if row is None:
        return error("not found", 404)
    _room, mem = ops.room_access(db, uid, row.room_id)
    if mem is None:
        return error("not found", 404)
    data = request.get_json(silent=True) or {}
    content = data.get("content", "")
    if isinstance(data.get("boost"), dict):
        content = data["boost"].get("content", content)
    boost = ops.create_boost(db, mid, uid, content, int(time.time()))
    if boost is None:
        return error("invalid boost content", 422)
    return jsonify({"id": boost.id, "content": boost.content}), 201


@bp.delete("/messages/<int:mid>/boosts/<int:bid>")
def boost_delete(mid, bid):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    row = db.get(Message.__sqlmodel__, mid)
    if row is None:
        return error("not found", 404)
    _room, mem = ops.room_access(db, uid, row.room_id)
    if mem is None:
        return error("not found", 404)
    if not ops.delete_boost(db, bid, mid, uid):
        return error("not found", 404)
    return "", 204


def _user_list(room_id=None, filt=None):
    from sqlalchemy import func as _func
    db = db_session()
    U = User.__sqlmodel__
    query = select(U).where(U.status == 0)
    if room_id is not None:
        M = Membership.__sqlmodel__
        ids = [m.user_id for m in db.exec(
            select(M).where(M.room_id == room_id)).all()]
        query = query.where(U.id.in_(ids)) if ids else query.where(False)
    if filt:
        like = "%" + filt.lower() + "%"
        query = query.where(_func.lower(U.name).like(like))
    query = query.order_by(_func.lower(U.name)).limit(20)
    return [{"id": u.id, "name": u.name, "label": u.name}
            for u in db.exec(query).all()]


@bp.get("/autocompletable/users")
def autocomplete():
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    room_id = request.args.get("room_id")
    rid = int(room_id) if room_id and room_id.isdigit() else None
    if rid is not None:
        db = db_session()
        _room, mem = ops.room_access(db, uid, rid)
        if mem is None:
            return error("not found", 404)
    filt = request.args.get("filter") or request.args.get("query")
    return jsonify(_user_list(rid, filt))
