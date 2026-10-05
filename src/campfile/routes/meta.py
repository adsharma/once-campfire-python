"""Bench discovery endpoint (ids and corpus scale)."""

from flask import Blueprint, jsonify

from .. import state as st

bp = Blueprint("meta", __name__)


@bp.get("/__meta")
def meta():
    store = st.get_store()
    index = st.get_index()
    return jsonify({
        "users": len(store.users),
        "rooms": len(store.rooms),
        "messages": len(store.messages),
        "terms": len(index.postings),
        "watercooler": store.rooms[0].id,
        "first_user": store.users[0].id,
        "busy_message": store.messages[len(store.messages) // 2].id,
    })
