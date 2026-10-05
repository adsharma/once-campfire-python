"""Bot API: key-authenticated message and boost endpoints.

Mirrors the Django bot messages/bot_boosts views: '<id>-<token>' key auth
(401), membership-scoped rooms (404), raw-string post bodies, 201 with a
Location header on post, bot-shaped boost JSON, X-Total-Count/Link
pagination headers on listing.
"""

import time

from flask import Blueprint, jsonify, request

from campfile import queries as q
from campfile.db import Message
from campfile import ops
from campfile.fq import use_db
from campfile.routes.helpers import db_session, error

bp = Blueprint("bots_api", __name__)


def _room_for_bot(db, bot, rid: int):
    room, mem = ops.room_access(db, bot.id, rid)
    return room if mem is not None else None


@bp.get("/rooms/<int:rid>/<bot_key>/messages")
def bot_list(rid, bot_key):
    db = db_session()
    use_db(db)
    bot = ops.bot_auth(db, bot_key)
    if bot is None:
        return error("unauthorized", 401)
    room = _room_for_bot(db, bot, rid)
    if room is None:
        return error("not found", 404)
    from campfile import fq as _fq
    M = Message.__sqlmodel__
    direction = "after" if request.args.get("after") else "before"
    anchor = request.args.get("after") or request.args.get("before")
    conds = ['message.room_id == param("rid")']
    params = {"rid": rid}
    if anchor and anchor.isdigit():
        pivot = db.get(M, int(anchor))
        if pivot is None or pivot.room_id != rid:
            return error("not found", 404)
        params["ts"] = pivot.created_at
        if direction == "after":
            conds.append("message.created_at > param(\"ts\")")
        else:
            conds.append("message.created_at < param(\"ts\")")
    if direction == "after":
        keys = "message.created_at"
    else:
        keys = "desc(message.created_at)"
    rows = (_fq.MessageQuery([])
                    .where(_fq.pred(" and ".join(conds)))
                    .order_by(_fq.order(keys))
                    .take(40).project(q.MSG_COLS)).bind(**(params)).rows()
    if direction == "before":
        rows = list(reversed(rows))
    if not rows:
        return "", 204
    import dataclasses
    body = jsonify([dataclasses.asdict(v)
                    for v in q.views_for(db, list(rows))])
    total = (_fq.MessageQuery([])
                     .where(_fq.pred('message.room_id == param("rid")'))
                     .count()).bind(**({"rid": rid})).rows()
    body.headers["X-Total-Count"] = str(
        total[0]["COUNT(*)"] if total else 0)
    edge = rows[-1] if direction == "after" else rows[0]
    if direction == "after":
        more_cond = "message.created_at > param(\"ts\")"
    else:
        more_cond = "message.created_at < param(\"ts\")"
    more = (_fq.MessageQuery([])
                    .where(_fq.pred(
                        'message.room_id == param("rid") and (%s)' % more_cond))
                    .take(1).project(["message.id"])).bind(**({"rid": rid, "ts": edge["created_at"]})).rows()
    if more:
        body.headers["Link"] = (
            "</rooms/%d/%s/messages?%s=%d>; rel=\"next\""
            % (rid, bot_key, direction, edge["id"]))
    return body


@bp.post("/rooms/<int:rid>/<bot_key>/messages")
def bot_post(rid, bot_key):
    db = db_session()
    bot = ops.bot_auth(db, bot_key)
    if bot is None:
        return error("unauthorized", 401)
    room = _room_for_bot(db, bot, rid)
    if room is None:
        return error("not found", 404)
    raw = request.get_data(as_text=True)
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        body = data.get("body", "")
    else:
        body = raw or ""
    if not (body or "").strip():
        return error("body required", 422)
    now = int(time.time())
    res = q.post_message_view(db, rid, bot.id, body,
                              "bot-%d-%d" % (bot.id, now), now)
    if not res.ok:
        return error("unprocessable", 422)
    ops.touch_room(db, rid, now)
    db.commit()
    resp = jsonify({})
    resp.status_code = 201
    resp.headers["Location"] = "/rooms/%d/messages/%d" % (rid, res.value["id"])
    return resp


@bp.post("/rooms/<int:rid>/<bot_key>/messages/<int:mid>/boosts")
def bot_boost_create(rid, bot_key, mid):
    db = db_session()
    bot = ops.bot_auth(db, bot_key)
    if bot is None:
        return error("unauthorized", 401)
    room = _room_for_bot(db, bot, rid)
    if room is None:
        return error("not found", 404)
    row = q.message_dict(db, mid)
    if row is None or row["room_id"] != rid:
        return error("not found", 404)
    raw = request.get_data(as_text=True)
    data = request.get_json(silent=True)
    content = (data.get("content") if isinstance(data, dict)
               else None) or raw or ""
    boost = ops.create_boost(db, mid, bot.id, content, int(time.time()))
    if boost is None:
        return error("invalid boost content", 422)
    from campfile.db import from_db_time
    from datetime import datetime, timezone
    iso = datetime.fromtimestamp(
        from_db_time(boost.created_at),
        tz=timezone.utc).isoformat(timespec="milliseconds").replace(
            "+00:00", "Z")
    return jsonify({
        "id": boost.id,
        "content": boost.content,
        "created_at": iso,
        "booster": {"id": bot.id, "name": bot.name, "role": "bot"},
        "message": {"id": mid, "url": "/rooms/%d/messages/%d" % (rid, mid)},
    }), 201


@bp.delete("/rooms/<int:rid>/<bot_key>/messages/<int:mid>/boosts/<int:bid>")
def bot_boost_delete(rid, bot_key, mid, bid):
    db = db_session()
    bot = ops.bot_auth(db, bot_key)
    if bot is None:
        return error("unauthorized", 401)
    room = _room_for_bot(db, bot, rid)
    if room is None:
        return error("not found", 404)
    if not ops.delete_boost(db, bid, mid, bot.id):
        return error("not found", 404)
    return "", 204
