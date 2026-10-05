"""Room pages, message windows, and posting (mirrors Rooms/MessagesController)."""

import time

from flask import Blueprint, request

from .. import queries as q
from .helpers import actor_or_login, db_session, error, login_redirect, present, present_list

bp = Blueprint("rooms", __name__)


def _int_arg(name, default=0):
    try:
        return int(request.args.get(name, default))
    except ValueError:
        return default


@bp.get("/rooms/<int:room_id>")
def room_page(room_id: int):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    res = q.room_page(db_session(), room_id, uid)
    if not res.ok:
        return error(res.error, 404)
    return present(res.value)


@bp.get("/rooms/<int:room_id>/messages")
def room_messages(room_id: int):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    res = q.messages_page(
        db_session(), room_id, uid, _int_arg("before"), _int_arg("after")
    )
    if not res.ok:
        return error(res.error, 404)
    return present_list(res.value)


@bp.post("/rooms/<int:room_id>/messages")
def post_message(room_id: int):
    db = db_session()
    payload = request.get_json(force=True, silent=True) or {}
    creator = actor_or_login()
    if creator is None:
        try:
            creator = int(payload.get("creator_id", 0))
        except ValueError:
            creator = 0
    if not creator:
        return login_redirect()
    body = str(payload.get("body", ""))
    res = q.post_message_view(
        db, room_id, creator, body,
        str(payload.get("client_message_id", "")), int(time.time()),
    )
    if not res.ok:
        return error(res.error, 422)
    return present(q.message_view(
        db, res.value,
        q._users_by_id(db, [res.value.creator_id]), {}, {},
        {res.value.id: body},
    )), 201
