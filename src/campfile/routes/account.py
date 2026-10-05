"""Account administration: account, users, bots, styles, join code, bans.

JSON mirrors of the Django account/account_users/bots/custom_styles/
join_code/ban views. Administrator-only except the account overview;
same status codes (403/404) and the same deactivate/ban semantics.
"""

import secrets
import time

from flask import Blueprint, jsonify, request

from campfile import queries as q
from campfile.db import User, to_db_time
from campfile.domain import campfire as c
from campfile import ops
from campfile.routes.helpers import actor_or_login, db_session, error, login_redirect

bp = Blueprint("account", __name__)


def _admin(db, uid: int):
    me = db.get(User.__sqlmodel__, uid)
    if me is None or me.role != c.ROLE_ADMIN:
        return None
    return me


def _user_json(u):
    return {"id": u["id"], "name": u["name"],
            "email_address": u["email_address"],
            "role": u["role"], "status": u["status"]}


@bp.get("/account")
def account_show():
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    me = db.get(User.__sqlmodel__, uid)
    account = ops.account_row(db)
    if account is None:
        return error("not found", 404)
    from campfile import fq as _fq
    if me.role != c.ROLE_ADMIN:
        status_pred = "user.status == 0"
    else:
        status_pred = "user.status in [0, 2]"
    users = _fq.rows(db, _fq.UserQuery([])
                     .where(_fq.pred(
                         'user.role != param("bot") and (%s)' % status_pred))
                     .order_by(_fq.order("lower(user.name)"))
                     .take(500)
                     .project(["user.id", "user.name", "user.email_address",
                               "user.role", "user.status"]),
                     {"bot": c.ROLE_BOT})
    admins = [_user_json(u) for u in users if u["role"] == c.ROLE_ADMIN]
    members = [_user_json(u) for u in users if u["role"] != c.ROLE_ADMIN]
    return jsonify({
        "name": account.name,
        "join_url": "/join/" + (account.join_code or ""),
        "can_administer": me.role == c.ROLE_ADMIN,
        "administrators": admins,
        "members": members,
    })


@bp.route("/account", methods=["PATCH", "PUT"])
def account_update():
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    if _admin(db, uid) is None:
        return error("forbidden", 403)
    account = ops.account_row(db)
    if account is None:
        return error("not found", 404)
    data = request.get_json(silent=True) or {}
    payload = data.get("account") if isinstance(data.get("account"),
                                               dict) else data
    settings = payload.get("settings")
    if ("account[settings][restrict_room_creation_to_administrators]"
            in (request.form or {})):
        settings = {"restrict_room_creation_to_administrators": True}
    ops.update_account(db, account, payload.get("name"), settings,
                       int(time.time()))
    return jsonify({"name": account.name,
                    "settings": q.account_settings(account)})


@bp.route("/account/users/<int:other>", methods=["PUT", "PATCH", "DELETE"])
def account_user(other):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    if _admin(db, uid) is None:
        return error("forbidden", 403)
    row = db.get(User.__sqlmodel__, other)
    if row is None or row.status != 0:
        return error("not found", 404)
    now = int(time.time())
    if request.method == "DELETE":
        ops.deactivate_user(db, row, now)
        return jsonify({"id": other, "status": 1})
    data = request.get_json(silent=True) or {}
    payload = data.get("user") if isinstance(data.get("user"),
                                            dict) else data
    role = (c.ROLE_ADMIN if payload.get("role") == "administrator"
            else c.ROLE_MEMBER)
    ops.set_role(db, row, role, now)
    return jsonify({"id": other, "role": role})


@bp.get("/account/bots")
def bots_list():
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    if _admin(db, uid) is None:
        return error("forbidden", 403)
    from campfile import fq as _fq
    out = []
    bots = _fq.rows(db, _fq.UserQuery([])
                    .where(_fq.pred(
                        'user.role == param("bot") and user.status == 0'))
                    .order_by(_fq.order("lower(user.name)"))
                    .project(["user.id", "user.name", "user.bot_token"]),
                    {"bot": c.ROLE_BOT})
    for bot in bots:
        rooms = [{"id": r["id"], "name": r["name"]} for r in _fq.rows(
            db, _fq.RoomWithMembershipsQuery([])
            .edge("memberships", _fq.JoinOn("id", "room_id"))
            .where(_fq.pred('membership.user_id == param("uid")'))
            .project(["room.id", "room.name"]),
            {"uid": bot["id"]})]
        out.append({"id": bot["id"], "name": bot["name"],
                    "key": c.bot_key_of(bot["id"], bot["bot_token"] or ""),
                    "webhook": ops.bot_webhook(db, bot["id"]), "rooms": rooms})
    return jsonify(out)


@bp.get("/account/bots/new")
def bot_new_form():
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    if _admin(db, uid) is None:
        return error("forbidden", 403)
    return jsonify({"new": True})


@bp.get("/account/bots/<int:bid>/edit")
def bot_edit_form(bid):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    if _admin(db, uid) is None:
        return error("forbidden", 403)
    bot = db.get(User.__sqlmodel__, bid)
    if bot is None or bot.role != c.ROLE_BOT:
        return error("not found", 404)
    return jsonify({"id": bot.id, "name": bot.name,
                    "webhook": ops.bot_webhook(db, bot.id)})


@bp.post("/account/bots")
def bot_create():
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    if _admin(db, uid) is None:
        return error("forbidden", 403)
    data = request.get_json(silent=True) or {}
    payload = data.get("user") if isinstance(data.get("user"),
                                            dict) else data
    name = (payload.get("name") or "").strip()
    if not name:
        return error("name required", 422)
    now = int(time.time())
    bot = ops.create_user(db, name, "", "", c.ROLE_BOT,
                          secrets.token_hex(6), now)
    if bot is None:
        return error("unprocessable", 422)
    ops.bot_upsert_webhook(db, bot.id, payload.get("webhook_url", ""), now)
    return jsonify({"id": bot.id, "name": bot.name,
                    "key": c.bot_key_of(bot.id, bot.bot_token or "")}), 201


@bp.route("/account/bots/<int:bid>", methods=["PATCH", "PUT", "DELETE"])
def bot_edit(bid):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    if _admin(db, uid) is None:
        return error("forbidden", 403)
    bot = db.get(User.__sqlmodel__, bid)
    if bot is None or bot.role != c.ROLE_BOT or bot.status != 0:
        return error("not found", 404)
    now = int(time.time())
    if request.method == "DELETE":
        ops.deactivate_user(db, bot, now)
        return jsonify({"id": bid, "status": 1})
    data = request.get_json(silent=True) or {}
    payload = data.get("user") if isinstance(data.get("user"),
                                            dict) else data
    if payload.get("name"):
        bot.name = payload["name"]
        bot.updated_at = to_db_time(now)
        db.add(bot)
    ops.bot_upsert_webhook(db, bot.id, payload.get("webhook_url", ""), now)
    db.commit()
    db.refresh(bot)
    return jsonify({"id": bot.id, "name": bot.name,
                    "key": c.bot_key_of(bot.id, bot.bot_token or ""),
                    "webhook": ops.bot_webhook(db, bot.id)})


@bp.put("/account/bots/<int:bid>/key")
def bot_key_reset(bid):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    if _admin(db, uid) is None:
        return error("forbidden", 403)
    bot = db.get(User.__sqlmodel__, bid)
    if bot is None or bot.role != c.ROLE_BOT or bot.status != 0:
        return error("not found", 404)
    bot.bot_token = secrets.token_hex(6)
    bot.updated_at = to_db_time(int(time.time()))
    db.add(bot)
    db.commit()
    return jsonify({"id": bid,
                    "key": c.bot_key_of(bot.id, bot.bot_token)})


@bp.get("/account/custom_styles")
def styles_show():
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    if _admin(db, uid) is None:
        return error("forbidden", 403)
    account = ops.account_row(db)
    return jsonify({"custom_styles": (account.custom_styles
                                      if account else "") or ""})


@bp.route("/account/custom_styles", methods=["PATCH", "PUT"])
def styles_update():
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    if _admin(db, uid) is None:
        return error("forbidden", 403)
    account = ops.account_row(db)
    if account is None:
        return error("not found", 404)
    data = request.get_json(silent=True) or {}
    payload = data.get("account") if isinstance(data.get("account"),
                                               dict) else data
    ops.update_styles(db, account, payload.get("custom_styles", ""),
                      int(time.time()))
    return jsonify({"custom_styles": account.custom_styles or ""})


@bp.post("/account/join_code")
def join_code_reset():
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    if _admin(db, uid) is None:
        return error("forbidden", 403)
    account = ops.account_row(db)
    if account is None:
        return error("not found", 404)
    code = ops.reset_join_code(db, account, int(time.time()))
    return jsonify({"join_code": code, "join_url": "/join/" + code})


@bp.route("/users/<int:other>/ban", methods=["POST", "DELETE"])
def ban(other):
    uid = actor_or_login()
    if uid is None:
        return login_redirect()
    db = db_session()
    if _admin(db, uid) is None:
        return error("forbidden", 403)
    row = db.get(User.__sqlmodel__, other)
    if row is None:
        return error("not found", 404)
    now = int(time.time())
    if request.method == "DELETE":
        ops.unban_user(db, row, now)
        return jsonify({"id": other, "status": 0})
    count = ops.ban_user(db, row, now)
    return jsonify({"id": other, "status": 2, "banned_ips": count})
