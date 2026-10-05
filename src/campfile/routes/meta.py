"""Bench discovery endpoint (ids and corpus scale)."""

from flask import Blueprint, jsonify
from sqlalchemy import func, text
from sqlmodel import select

from .. import state as st
from ..db import Message, Room, User

bp = Blueprint("meta", __name__)


@bp.get("/__meta")
def meta():
    db = st.get_db()
    wc = db.exec(select(Room.__sqlmodel__.id).order_by(Room.__sqlmodel__.id)).first()
    uid = db.exec(select(User.__sqlmodel__.id).order_by(User.__sqlmodel__.id)).first()
    total = db.exec(select(func.count(Message.__sqlmodel__.id))).one()
    mid = db.exec(select(Message.__sqlmodel__.id).order_by(Message.__sqlmodel__.id)
                  .offset(total // 2)).first()
    fts = db.exec(text("SELECT count(*) FROM message_search_index")).one()[0]
    return jsonify({
        "users": db.exec(select(func.count(User.__sqlmodel__.id))).one(),
        "rooms": db.exec(select(func.count(Room.__sqlmodel__.id))).one(),
        "messages": total,
        "fts_rows": fts,
        "watercooler": wc,
        "first_user": uid,
        "busy_message": mid,
    })
