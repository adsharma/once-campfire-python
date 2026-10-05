"""Sidebar (mirrors Users::SidebarsController)."""

from flask import Blueprint

from .. import queries as q
from .helpers import actor_or_login, db_session, error, login_redirect, present_list

bp = Blueprint("sidebar", __name__)


@bp.get("/users/me/sidebar")
def sidebar():
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    res = q.sidebar(db_session(), uid)
    if not res.ok:
        return error(res.error, 404)
    return present_list(res.value)
