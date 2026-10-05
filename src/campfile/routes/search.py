"""Full-text search (mirrors SearchesController)."""

from flask import Blueprint, request

from .. import state as st
from ..domain import workload as w
from .helpers import current_uid, error, present_list

bp = Blueprint("search", __name__)


@bp.get("/searches")
def searches():
    store = st.get_store()
    index = st.get_index()
    uid = current_uid(request.args, store.users[0].id)
    res = w.search_page(store, index, uid, request.args.get("q", ""), 20)
    if not res.ok:
        return error(res.error, 404)
    return present_list(res.value)
