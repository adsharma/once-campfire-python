"""Room/message management: CRUD, refresh, involvement, boosts, autocomplete.

JSON mirrors of the Django room_form/refresh/involvement/boosts/messages
views. Same paths, same authz (admin-or-creator via can_administer,
involvement allow-lists, 16-char boosts), JSON bodies instead of pages
and turbo streams.
"""

import time

from flask import Blueprint, jsonify, request

from campfile import queries as q
from campfile.db import User
from campfile.domain import campfire as c
from campfile import ops
from campfile.fq import use_db
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
    use_db(db)
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
        from campfile import fq as _fq
        actives = (_fq.UserQuery([])
                           .where(_fq.pred("user.status == 0"))
                           .project(["user.id"])).rows()
        ids = [u["id"] for u in actives]
        if not name:
            return error("name required", 422)
    room = ops.create_room(db, KINDS[kind], name or None, uid, ids,
                           int(time.time()))
    if room is None:
        return error("unprocessable", 422)
    res = q.room_page(db, room["id"], uid)
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
    use_db(db)
    room, _mem = ops.room_access(db, uid, rid)
    if room is None:
        return error("not found", 404)
    from campfile import fq as _fq
    new_rows = (_fq.MessageQuery([])
        .where(_fq.pred('message.room_id == param("rid")'
                        ' and message.created_at > param("ts")'))
        .order_by(_fq.order("message.created_at"))
        .take(40).project(q.MSG_COLS)).bind(**({"rid": rid, "ts": stamp})).rows()
    new_ids = [m["id"] for m in new_rows]
    upd_rows = [m for m in (_fq.MessageQuery([])
        .where(_fq.pred('message.room_id == param("rid")'
                        ' and message.updated_at > param("ts")'))
        .order_by(_fq.order("desc(message.created_at)"))
        .take(40).project(q.MSG_COLS + ["message.updated_at"])).bind(**({"rid": rid, "ts": stamp})).rows() if m["id"] not in set(new_ids)]
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
    row = q.message_dict(db, mid)
    if row is None or row["room_id"] != rid:
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
    row = q.message_dict(db, mid)
    if row is None or row["room_id"] != rid:
        return error("not found", 404)
    me = db.get(User.__sqlmodel__, uid)
    if not c.can_administer(me.role, uid, row["creator_id"], False):
        return error("forbidden", 403)
    data = request.get_json(silent=True) or {}
    body = data.get("body", data.get("message", {}).get("body")
                    if isinstance(data.get("message"), dict) else None)
    if body is None:
        return error("body required", 422)
    ops.update_message_body(db, mid, body, int(time.time()))
    return present(q.views_for(db, [q.message_dict(db, mid)])[0])


@bp.delete("/rooms/<int:rid>/messages/<int:mid>")
def message_delete(rid, mid):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    room, _mem = ops.room_access(db, uid, rid)
    if room is None:
        return error("not found", 404)
    row = q.message_dict(db, mid)
    if row is None or row["room_id"] != rid:
        return error("not found", 404)
    me = db.get(User.__sqlmodel__, uid)
    if not c.can_administer(me.role, uid, row["creator_id"], False):
        return error("forbidden", 403)
    ops.delete_message_cascade(db, mid)
    return "", 204


@bp.get("/messages/<int:mid>/boosts")
def boost_list(mid):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    use_db(db)
    row = q.message_dict(db, mid)
    if row is None:
        return error("not found", 404)
    _room, mem = ops.room_access(db, uid, row["room_id"])
    if mem is None:
        return error("not found", 404)
    from campfile import fq as _fq
    boosts = (_fq.BoostQuery([])
                       .where(_fq.pred('boost.message_id == param("mid")'))
                       .project(["boost.id", "boost.content",
                                 "boost.booster_id"])).bind(**({"mid": mid})).rows()
    return jsonify([{"id": b["id"], "content": b["content"],
                     "booster_id": b["booster_id"]} for b in boosts])


@bp.post("/messages/<int:mid>/boosts")
def boost_create(mid):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    row = q.message_dict(db, mid)
    if row is None:
        return error("not found", 404)
    _room, mem = ops.room_access(db, uid, row["room_id"])
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
    row = q.message_dict(db, mid)
    if row is None:
        return error("not found", 404)
    _room, mem = ops.room_access(db, uid, row["room_id"])
    if mem is None:
        return error("not found", 404)
    if not ops.delete_boost(db, bid, mid, uid):
        return error("not found", 404)
    return "", 204


def _user_list(room_id=None, filt=None):
    from campfile import fq as _fq
    db = db_session()
    use_db(db)
    conds = ["user.status == 0"]
    params = {}
    if room_id is not None:
        mems = (_fq.MembershipQuery([])
                         .where(_fq.pred('membership.room_id == param("rid")'))
                         .project(["membership.user_id"])).bind(**({"rid": room_id})).rows()
        ids = [m["user_id"] for m in mems]
        if not ids:
            return []
        conds.append("user.id in [%s]" % ",".join(str(int(i)) for i in ids))
    if filt:
        conds.append("like(lower(user.name), param(\"pat\"))")
        params["pat"] = "%" + filt.lower() + "%"
    chain = (_fq.UserQuery([])
             .where(_fq.pred(" and ".join(conds)))
             .order_by(_fq.order("lower(user.name)"))
             .take(20))
    return [{"id": u["id"], "name": u["name"], "label": u["name"]}
            for u in (chain.project(
                ["user.id", "user.name"])).bind(**(params)).rows()]


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
