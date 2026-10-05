"""DB-backed hot paths + session auth (SQL mirrors of workload.py over Store).

Reads are fquery chains: the query tree compiles to parameterized SQL
(? placeholders, never interpolated text) executed on the session's own
connection. Writes stay on db.exec / raw SQL. Same view dataclasses
(bench JSON unchanged); same rules (membership scoping, 40/page
pagination, unread fan-out, visibility). Enum strings live in the DB
(Rails form); the int enums stay in Python views.

Auth mirrors the Rails/Django session model: bcrypt password check on
POST /session, a sessions row keyed by token, and a signed
session_token cookie. Cookie crypto is Flask-native (itsdangerous), not
Rails-compatible — see README for the boundary.
"""

import secrets

from sqlalchemy import text

from campfile import fq
from campfile.db import (
    INVOLVEMENT_TO_ID,
    ROOM_TYPE_TO_KIND,
    Message,
    RichText,
    Room,
    User,
    UserSession,
)
from campfile.domain.workload import (
    MessageView,
    MessagesPageResult,
    RoomPageResult,
    RoomPageView,
    SearchHitView,
    SearchPageResult,
    SidebarEntry,
    SidebarResult,
)

PAGE_SIZE = 40

MSG_COLS = ["message.id", "message.room_id", "message.creator_id",
            "message.client_message_id", "message.created_at"]


def _member(session, room_id: int, user_id: int) -> bool:
    fq.use_db(session)
    rows = (fq.MembershipQuery([])
                   .where(fq.pred(
                       'membership.room_id == param("rid")'
                       ' and membership.user_id == param("uid")'))
                   .take(1).project(["membership.id"])).bind(**({"rid": room_id, "uid": user_id})).rows()
    return bool(rows)


def _users_by_id(session, ids: list) -> dict:
    fq.use_db(session)
    out = {}
    if not ids:
        return out
    in_list = ",".join(str(int(i)) for i in ids)
    rows = (fq.UserQuery([])
                   .where(fq.pred("user.id in [%s]" % in_list))
                   .project(["user.id", "user.name"])).rows()
    for r in rows:
        out[r["id"]] = r["name"]
    return out


def _boosts_by_message(session, ids: list) -> dict:
    fq.use_db(session)
    out = {i: [] for i in ids}
    if not ids:
        return out
    in_list = ",".join(str(int(i)) for i in ids)
    rows = (fq.BoostQuery([])
                   .where(fq.pred("boost.message_id in [%s]" % in_list))
                   .project(["boost.message_id", "boost.content"])).rows()
    for r in rows:
        if r["message_id"] in out:
            out[r["message_id"]].append(r["content"])
    return out


def _mentions_by_message(session, ids: list) -> dict:
    fq.use_db(session)
    out = {i: [] for i in ids}
    if not ids:
        return out
    in_list = ",".join(str(int(i)) for i in ids)
    try:
        rows = (fq.MessageMentionQuery([])
                       .edge("user", fq.JoinOn("user_id", "id"))
                       .where(fq.pred("mm.message_id in [%s]" % in_list))
                       .project(["mm.message_id", "user.name"])).rows()
    except Exception:  # noqa: BLE001 - foreign schema without the table
        session.rollback()
        return out
    for r in rows:
        if r["message_id"] in out and r["name"]:
            out[r["message_id"]].append(r["name"])
    return out


def account_settings(account) -> dict:
    import json as _json
    if account is None or not account.settings:
        return {}
    try:
        parsed = _json.loads(account.settings)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _bodies_by_message(session, ids: list) -> dict:
    fq.use_db(session)
    out = {}
    if not ids:
        return out
    in_list = ",".join(str(int(i)) for i in ids)
    rows = (fq.RichTextQuery([])
                   .where(fq.pred(
                       "rich.record_id in [%s] and rich.name == param(\"n\")"
                       " and rich.record_type in [\"Message\","
                       " \"ActionText::RichText\"]" % in_list))
                   .order_by(fq.order("rich.id"))
                   .project(["rich.record_id", "rich.body"])).bind(**({"n": "body"})).rows()
    for r in rows:
        out[r["record_id"]] = r["body"] or ""
    return out


def message_dict(session, mid: int):
    """One message as a dict, or None."""
    fq.use_db(session)
    rows = (fq.MessageQuery([])
                   .where(fq.pred('message.id == param("mid")'))
                   .take(1).project(MSG_COLS)).bind(**({"mid": mid})).rows()
    return rows[0] if rows else None


def message_view(m: dict, names: dict, boosts: dict, mentions: dict,
                 bodies: dict) -> MessageView:
    from campfile.domain import campfire as c
    v = MessageView()
    v.id = m["id"]
    v.body = bodies.get(m["id"], "")
    v.creator_id = m["creator_id"]
    v.creator_name = names.get(m["creator_id"], "")
    v.created_at = m["created_at"]
    v.client_message_id = m["client_message_id"]
    v.attachment_name = ""
    has_att = False
    snd = c.sound_command(v.body)
    v.content_type = c.content_type_name(c.content_type_of(has_att, snd))
    v.boosts = boosts.get(m["id"], [])
    v.mentions = mentions.get(m["id"], [])
    return v


def views_for(session, msgs: list) -> list:
    ids = [m["id"] for m in msgs]
    creator_ids = list({m["creator_id"] for m in msgs})
    names = _users_by_id(session, creator_ids)
    boosts = _boosts_by_message(session, ids)
    mentions = _mentions_by_message(session, ids)
    bodies = _bodies_by_message(session, ids)
    return [message_view(m, names, boosts, mentions, bodies)
            for m in msgs]


def _page_window(session, room_id: int, op: str, anchor: dict, ascending: bool):
    fq.use_db(session)
    if ascending:
        against = ('message.created_at > param("ts") or '
                   '(message.created_at == param("ts")'
                   ' and message.id > param("mid"))')
        keys = "message.created_at, message.id"
    else:
        against = ('message.created_at < param("ts") or '
                   '(message.created_at == param("ts")'
                   ' and message.id < param("mid"))')
        keys = "desc(message.created_at), desc(message.id)"
    rows = (fq.MessageQuery([])
                   .where(fq.pred(
                       'message.room_id == param("rid") and (%s)' % against))
                   .order_by(fq.order(keys))
                   .take(PAGE_SIZE).project(MSG_COLS)).bind(**({"rid": room_id, "ts": anchor["created_at"],
                    "mid": anchor["id"]})).rows()
    return rows


def room_page(session, room_id: int, user_id: int) -> RoomPageResult:
    fq.use_db(session)
    if not _member(session, room_id, user_id):
        return RoomPageResult(ok=False, value=RoomPageView(), error="not a member")
    R = Room.__sqlmodel__
    room = session.get(R, room_id)
    if room is None:
        return RoomPageResult(ok=False, value=RoomPageView(), error="room not found")
    rows = (fq.MessageQuery([])
                   .where(fq.pred('message.room_id == param("rid")'))
                   .order_by(fq.order("desc(message.created_at), desc(message.id)"))
                   .take(PAGE_SIZE).project(MSG_COLS)).bind(**({"rid": room_id})).rows()
    total = (fq.MessageQuery([])
                    .where(fq.pred('message.room_id == param("rid")'))
                    .count()).bind(**({"rid": room_id})).rows()
    msgs = list(reversed(rows))
    view = RoomPageView()
    view.room_id = room.id
    view.room_name = room.name
    view.room_kind = ROOM_TYPE_TO_KIND.get(room.type, 1)
    view.has_more = (total[0]["COUNT(*)"] if total else 0) > PAGE_SIZE
    view.messages = views_for(session, msgs)
    return RoomPageResult(ok=True, value=view, error="")


def messages_page(session, room_id: int, user_id: int, before_id: int, after_id: int):
    fq.use_db(session)
    if not _member(session, room_id, user_id):
        return MessagesPageResult(ok=False, value=[], error="not a member")
    M = Message.__sqlmodel__
    if before_id > 0:
        anchor = session.get(M, before_id)
        if anchor is None or anchor.room_id != room_id:
            return MessagesPageResult(ok=False, value=[], error="message not found")
        rows = _page_window(session, room_id, "<",
                            {"created_at": anchor.created_at, "id": anchor.id},
                            False)
        msgs = list(reversed(rows))
    elif after_id > 0:
        anchor = session.get(M, after_id)
        if anchor is None or anchor.room_id != room_id:
            return MessagesPageResult(ok=False, value=[], error="message not found")
        msgs = _page_window(session, room_id, ">",
                            {"created_at": anchor.created_at, "id": anchor.id},
                            True)
    else:
        rows = (fq.MessageQuery([])
                       .where(fq.pred('message.room_id == param("rid")'))
                       .order_by(fq.order(
                           "desc(message.created_at), desc(message.id)"))
                       .take(PAGE_SIZE).project(MSG_COLS)).bind(**({"rid": room_id})).rows()
        msgs = list(reversed(rows))
    return MessagesPageResult(ok=True, value=views_for(session, msgs), error="")


def sidebar(session, user_id: int) -> SidebarResult:
    fq.use_db(session)
    U = User.__sqlmodel__
    if session.get(U, user_id) is None:
        return SidebarResult(ok=False, value=[], error="user not found")
    rows = (fq.MembershipQuery([])
                   .where(fq.pred(
                       'membership.user_id == param("uid")'
                       ' and membership.involvement != param("inv")'))
                   .edge("room", fq.JoinOn("room_id", "id"))
                   .order_by(fq.order("lower(room.name), room.id"))
                   .project(["membership.involvement", "membership.unread_at",
                             "room.id", "room.name", "room.type"])).bind(**({"uid": user_id, "inv": "invisible"})).rows()
    out = []
    for r in rows:
        e = SidebarEntry()
        e.room_id = r["id"]
        e.room_name = r["name"]
        e.room_kind = ROOM_TYPE_TO_KIND.get(r["type"], 1)
        e.unread = r["unread_at"] not in (None, 0)
        e.involvement = INVOLVEMENT_TO_ID.get(r["involvement"], 2)
        out.append(e)
    return SidebarResult(ok=True, value=out, error="")


def search_page(session, user_id: int, query: str, limit: int):
    fq.use_db(session)
    U = User.__sqlmodel__
    if session.get(U, user_id) is None:
        return SearchPageResult(ok=False, value=[], error="user not found")
    # Raw query to FTS5 like Rails (idx.body MATCH ?); the porter tokenizer
    # runs identically on indexed bodies and the query.
    if query.strip() == "":
        return SearchPageResult(ok=True, value=[], error="")
    room_rows = (fq.MembershipQuery([])
                        .where(fq.pred(
                            'membership.user_id == param("uid")'
                            ' and membership.involvement != param("inv")'))
                        .project(["membership.room_id"])).bind(**({"uid": user_id, "inv": "invisible"})).rows()
    room_ids = [r["room_id"] for r in room_rows]
    if not room_ids:
        return SearchPageResult(ok=True, value=[], error="")
    in_list = ",".join(str(int(i)) for i in room_ids)
    try:
        rows = (fq.FTSQuery([])
                       .edge("messages", fq.JoinOn("rowid", "id"))
                       .where(fq.pred(
                           "match(idx.body, param(\"q\"))"
                           " and message.room_id in [%s]" % in_list))
                       .order_by(fq.order("message.created_at"))
                       .take(limit)
                       .project(["message.id", "message.room_id",
                                 "message.creator_id",
                                 "message.client_message_id",
                                 "message.created_at"])).bind(**({"q": query.strip()})).rows()
    except Exception:  # noqa: BLE001 - FTS5 syntax in user input
        session.rollback()
        return SearchPageResult(ok=True, value=[], error="")
    name_rows = (fq.RoomQuery([]).project(["room.id", "room.name"])).rows()
    names = {r["id"]: r["name"] for r in name_rows}
    views = views_for(session, rows)
    out = []
    for v in views:
        hit = SearchHitView()
        hit.message = v
        mid_rows = [m for m in rows if m["id"] == v.id]
        if mid_rows:
            hit.room_name = names.get(mid_rows[0]["room_id"], "")
        out.append(hit)
    return SearchPageResult(ok=True, value=out, error="")


def _message_dict(row_id: int, room_id: int, creator_id: int,
                  client_message_id: str, stamp) -> dict:
    return {"id": row_id, "room_id": room_id, "creator_id": creator_id,
            "client_message_id": client_message_id, "created_at": stamp}


def post_message_view(session, room_id: int, creator_id: int, body: str,
                      client_message_id: str, now: int):
    fq.use_db(session)
    from campfile.domain import campfire as c
    M = Message.__sqlmodel__
    if session.get(Room.__sqlmodel__, room_id) is None:
        return c.MessageResult(ok=False, error="room not found")
    mem = (fq.MembershipQuery([])
                  .where(fq.pred(
                      'membership.room_id == param("rid")'
                      ' and membership.user_id == param("uid")'))
                  .take(1).project(["membership.id"])).bind(**({"rid": room_id, "uid": creator_id})).rows()
    if not mem:
        return c.MessageResult(ok=False, error="creator is not a room member")
    if body == "":
        return c.MessageResult(ok=False, error="body or attachment is required")
    from campfile.db import to_db_time
    stamp = to_db_time(now)
    row = M(room_id=room_id, creator_id=creator_id,
            client_message_id=client_message_id,
            created_at=stamp, updated_at=stamp)
    session.add(row)
    session.flush()
    session.add(RichText.__sqlmodel__(
        record_type="Message", record_id=row.id, name="body",
        body=body, created_at=now, updated_at=now))
    if not row.client_message_id:
        row.client_message_id = "client-" + str(row.id)
    cutoff = to_db_time(now - c.CONNECTION_TTL_SECS)
    session.exec(
        text(
            "UPDATE memberships SET unread_at = :now, updated_at = :now "
            "WHERE room_id = :rid AND user_id != :uid "
            "AND involvement != 'invisible' "
            "AND (connected_at IS NULL OR connected_at < :cutoff)"
        ).bindparams(now=stamp, rid=room_id, uid=creator_id, cutoff=cutoff)
    )
    session.exec(
        text("UPDATE rooms SET updated_at = :t WHERE id = :rid")
        .bindparams(t=stamp, rid=room_id)
    )
    session.commit()
    session.refresh(row)
    value = _message_dict(row.id, room_id, creator_id,
                          row.client_message_id, stamp)
    return c.MessageResult(ok=True, value=value)


# ---------------------------------------------------------------------------
# Session auth (bcrypt + token rows, Flask-signed cookie at the route layer)
# ---------------------------------------------------------------------------

SESSION_TTL_REFRESH = 3600


def authenticate(session, email: str, password: str):
    """Return the user dict when email+bcrypt verify and status allows."""
    fq.use_db(session)
    import bcrypt
    rows = (fq.UserQuery([])
                   .where(fq.pred('user.email_address == param("email")'))
                   .take(1)
                   .project(["user.id", "user.name", "user.email_address",
                             "user.password_digest", "user.role",
                             "user.status", "user.bio"])).bind(**({"email": email})).rows()
    if not rows:
        return None
    row = rows[0]
    if not row["password_digest"]:
        return None
    try:
        ok = bcrypt.checkpw(password.encode("utf-8"),
                            row["password_digest"].encode("utf-8"))
    except ValueError:
        return None
    if not ok:
        return None
    if row["status"] != 0:
        return None
    return row


def start_session(session, user_id: int, ip: str, agent: str, now: int) -> str:
    S = UserSession.__sqlmodel__
    from campfile.db import to_db_time as _t
    token = secrets.token_urlsafe(24)
    stamp = _t(now)
    session.add(S(user_id=user_id, token=token, ip_address=ip,
                  user_agent=agent, last_active_at=stamp, created_at=stamp,
                  updated_at=stamp))
    session.commit()
    return token


def user_from_token(session, token: str, now: int):
    """Resolve a session token, throttled-touching activity like Rails."""
    fq.use_db(session)
    if not token:
        return None
    S = UserSession.__sqlmodel__
    U = User.__sqlmodel__
    found = (fq.UserSessionQuery([])
                    .where(fq.pred('sess.token == param("tok")'))
                    .take(1).project(["sess.id", "sess.user_id",
                                      "sess.last_active_at"])).bind(**({"tok": token})).rows()
    if not found:
        return None
    row = session.get(S, found[0]["id"])
    if row is None:
        return None
    from campfile.db import from_db_time as _e, to_db_time as _t2
    if now - _e(row.last_active_at) > SESSION_TTL_REFRESH:
        stamp = _t2(now)
        row.last_active_at = stamp
        row.updated_at = stamp
        session.add(row)
        session.commit()
    user = session.get(U, row.user_id)
    if user is None or user.status != 0:
        return None
    return user


def end_session(session, token: str) -> None:
    fq.use_db(session)
    S = UserSession.__sqlmodel__
    found = (fq.UserSessionQuery([])
                    .where(fq.pred('sess.token == param("tok")'))
                    .take(1).project(["sess.id"])).bind(**({"tok": token})).rows()
    if found:
        row = session.get(S, found[0]["id"])
        if row is not None:
            session.delete(row)
            session.commit()
