"""Bench discovery endpoint (ids and corpus scale)."""

from flask import Blueprint, jsonify
from sqlalchemy import text

from .. import state as st
from campfile import fq as _fq

bp = Blueprint("meta", __name__)


def _count(db, qcls, alias):
    rows = _fq.rows(db, qcls([]).count())
    return rows[0]["COUNT(*)"] if rows else 0


def _first_id(db, qcls, alias):
    rows = _fq.rows(db, qcls([]).order_by(_fq.order(alias + ".id"))
                    .take(1).project([alias + ".id"]))
    return rows[0]["id"] if rows else 0


@bp.get("/__meta")
def meta():
    db = st.get_db()
    from campfile.fq import MessageQuery, RoomQuery, UserQuery
    total = _count(db, MessageQuery, "message")
    mid = _fq.rows(db, MessageQuery([])
                   .order_by(_fq.order("message.id"))
                   .take(1).skip(total // 2).project(["message.id"]))
    fts = db.exec(text("SELECT count(*) FROM message_search_index")).one()[0]
    return jsonify({
        "users": _count(db, UserQuery, "user"),
        "rooms": _count(db, RoomQuery, "room"),
        "messages": total,
        "fts_rows": fts,
        "watercooler": _first_id(db, RoomQuery, "room"),
        "first_user": _first_id(db, UserQuery, "user"),
        "busy_message": mid[0]["id"] if mid else 0,
    })
