"""Full-text search (mirrors SearchesController + searches views).

GET records nothing but returns recent searches alongside hits; POST
records the query (capped at 10 per user); DELETE clears history. The
query is sanitized to word characters like Django before MATCH.
"""

import re
import time

from flask import Blueprint, jsonify, request

from campfile import queries as q
from campfile import ops
from campfile.routes.helpers import actor_or_login, db_session, error, login_redirect

bp = Blueprint("search", __name__)


def _clean(raw: str) -> str:
    return re.sub(r"[^\w]", " ", raw or "").strip()


@bp.get("/searches")
def searches():
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    res = q.search_page(db, uid, _clean(request.args.get("q", "")), 100)
    if not res.ok:
        return error(res.error, 404)
    import dataclasses
    return jsonify({
        "query": _clean(request.args.get("q", "")),
        "messages": [dataclasses.asdict(v) for v in res.value],
        "recent": ops.recent_searches(db, uid),
    })


@bp.post("/searches")
def searches_record():
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    data = request.get_json(silent=True) or {}
    query = _clean(data.get("q", request.args.get("q", "")))
    if query:
        ops.record_search(db, uid, query, int(time.time()))
    return jsonify({"query": query,
                    "recent": ops.recent_searches(db, uid)})


@bp.delete("/searches")
def searches_clear():
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    ops.clear_searches(db_session(), uid)
    return jsonify({"recent": []})


@bp.post("/searches/clear")
def searches_clear_post():
    return searches_clear()
