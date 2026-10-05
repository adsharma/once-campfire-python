"""Sidebar (mirrors Users::SidebarsController)."""

from flask import Blueprint, request

from .. import queries as q
from .. import state as st
from .helpers import actor_or_login, default_uid, error, present_list

bp = Blueprint("sidebar", __name__)


@bp.get("/users/me/sidebar")
def sidebar():
    uid, login = actor_or_login(request.args, default_uid())
    if login is not None:
        return login
    res = q.sidebar(st.get_db(), uid)
    if not res.ok:
        return error(res.error, 404)
    return present_list(res.value)
