"""Room pages, message windows, and posting (mirrors Rooms/MessagesController)."""

import time

from flask import Blueprint, request

from .. import state as st
from ..domain import workload as w
from .helpers import current_uid, error, present, present_list

bp = Blueprint("rooms", __name__)


def _int_arg(name, default=0):
    try:
        return int(request.args.get(name, default))
    except ValueError:
        return default


@bp.get("/rooms/<int:room_id>")
def room_page(room_id: int):
    store = st.get_store()
    uid = current_uid(request.args, store.users[0].id)
    res = w.room_page(store, room_id, uid)
    if not res.ok:
        return error(res.error, 404)
    return present(res.value)


@bp.get("/rooms/<int:room_id>/messages")
def room_messages(room_id: int):
    store = st.get_store()
    uid = current_uid(request.args, store.users[0].id)
    res = w.messages_page(
        store, room_id, uid, _int_arg("before"), _int_arg("after")
    )
    if not res.ok:
        return error(res.error, 404)
    return present_list(res.value)


@bp.post("/rooms/<int:room_id>/messages")
def post_message(room_id: int):
    store = st.get_store()
    index = st.get_index()
    payload = request.get_json(force=True, silent=True) or {}
    try:
        creator = int(payload.get("creator_id", store.users[0].id))
    except ValueError:
        creator = store.users[0].id
    body = str(payload.get("body", ""))
    res = w.post_message_view(
        store, room_id, creator, body,
        str(payload.get("client_message_id", "")), int(time.time()),
    )
    if not res.ok:
        return error(res.error, 422)
    w.index_message(index, room_id, res.value.id, body)
    return present(w.build_message_view(store, res.value)), 201
