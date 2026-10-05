"""Full-text search (mirrors SearchesController)."""

from flask import Blueprint, request

from .. import queries as q
from .. import state as st
from .helpers import actor_or_login, default_uid, error, present_list

bp = Blueprint("search", __name__)


@bp.get("/searches")
def searches():
    uid, login = actor_or_login(request.args, default_uid())
    if login is not None:
        return login
    res = q.search_page(st.get_db(), uid, request.args.get("q", ""), 20)
    if not res.ok:
        return error(res.error, 404)
    return present_list(res.value)
