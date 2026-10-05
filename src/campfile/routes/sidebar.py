"""Sidebar (mirrors Users::SidebarsController)."""

from flask import Blueprint, request

from .. import state as st
from ..domain import workload as w
from .helpers import current_uid, error, present_list

bp = Blueprint("sidebar", __name__)


@bp.get("/users/me/sidebar")
def sidebar():
    store = st.get_store()
    uid = current_uid(request.args, store.users[0].id)
    res = w.sidebar(store, uid)
    if not res.ok:
        return error(res.error, 404)
    return present_list(res.value)
