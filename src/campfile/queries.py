"""DB-backed hot paths + session auth (SQL mirrors of workload.py over Store).

Same view dataclasses (bench JSON unchanged); same rules (membership
scoping, 40/page pagination, unread fan-out, visibility). Enum strings
live in the DB (Rails form); the int enums stay in Python views.
Preloads batch creators/boosts/mentions in single IN queries, mirroring
Rails' with_presentation preloads instead of N+1s.

Auth mirrors the Rails/Django session model: bcrypt password check on
POST /session, a sessions row keyed by token, and a signed
session_token cookie. Cookie crypto is Flask-native (itsdangerous), not
Rails-compatible — see README for the boundary.
"""

import secrets
import time

from sqlalchemy import func, text
from sqlmodel import select

from campfile.db import (
    INVOLVEMENT_TO_ID,
    ROOM_TYPE_TO_KIND,
    Boost,
    Membership,
    Message,
    MessageMention,
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


def _member(session, room_id: int, user_id: int) -> bool:
    M = Membership.__sqlmodel__
    row = session.exec(
        select(M).where(M.room_id == room_id, M.user_id == user_id)
    ).first()
    return row is not None


def _users_by_id(session, ids: list) -> dict:
    U = User.__sqlmodel__
    out = {}
    if not ids:
        return out
    for u in session.exec(select(U).where(U.id.in_(ids))).all():
        out[u.id] = u.name
    return out


def _boosts_by_message(session, ids: list) -> dict:
    B = Boost.__sqlmodel__
    out = {i: [] for i in ids}
    if not ids:
        return out
    for b in session.exec(select(B).where(B.message_id.in_(ids))).all():
        if b.message_id in out:
            out[b.message_id].append(b.content)
    return out


def _mentions_by_message(session, ids: list) -> dict:
    MM = MessageMention.__sqlmodel__
    U = User.__sqlmodel__
    out = {i: [] for i in ids}
    if not ids:
        return out
    try:
        rows = session.exec(
            select(MM.message_id, U.name)
            .join(U, U.id == MM.user_id)
            .where(MM.message_id.in_(ids))
        ).all()
    except Exception:  # noqa: BLE001 - foreign schema without the table
        session.rollback()
        return out
    for mid, name in rows:
        if mid in out and name:
            out[mid].append(name)
    return out


def _bodies_by_message(session, ids: list) -> dict:
    RT = RichText.__sqlmodel__
    out = {}
    if not ids:
        return out
    for r in session.exec(select(RT).where(
        RT.record_id.in_(ids),
        RT.name == "body",
        RT.record_type.in_(["Message", "ActionText::RichText"]),
    ).order_by(RT.id)).all():
        out[r.record_id] = r.body or ""
    return out


def message_view(session, m, names: dict, boosts: dict, mentions: dict,
                 bodies: dict) -> MessageView:
    from campfile.domain import campfire as c
    v = MessageView()
    v.id = m.id
    v.body = bodies.get(m.id, "")
    v.creator_id = m.creator_id
    v.creator_name = names.get(m.creator_id, "")
    v.created_at = m.created_at
    v.client_message_id = m.client_message_id
    v.attachment_name = ""
    has_att = False
    snd = c.sound_command(v.body)
    v.content_type = c.content_type_name(c.content_type_of(has_att, snd))
    v.boosts = boosts.get(m.id, [])
    v.mentions = mentions.get(m.id, [])
    return v


def views_for(session, msgs: list) -> list:
    ids = [m.id for m in msgs]
    creator_ids = list({m.creator_id for m in msgs})
    names = _users_by_id(session, creator_ids)
    boosts = _boosts_by_message(session, ids)
    mentions = _mentions_by_message(session, ids)
    bodies = _bodies_by_message(session, ids)
    return [message_view(session, m, names, boosts, mentions, bodies)
            for m in msgs]


def room_page(session, room_id: int, user_id: int) -> RoomPageResult:
    if not _member(session, room_id, user_id):
        return RoomPageResult(ok=False, value=RoomPageView(), error="not a member")
    R = Room.__sqlmodel__
    room = session.get(R, room_id)
    if room is None:
        return RoomPageResult(ok=False, value=RoomPageView(), error="room not found")
    M = Message.__sqlmodel__
    rows = session.exec(
        select(M)
        .where(M.room_id == room_id)
        .order_by(M.created_at.desc(), M.id.desc())
        .limit(PAGE_SIZE)
    ).all()
    total = session.exec(
        select(func.count(M.id)).where(M.room_id == room_id)
    ).one()
    msgs = list(reversed(rows))
    view = RoomPageView()
    view.room_id = room.id
    view.room_name = room.name
    view.room_kind = ROOM_TYPE_TO_KIND.get(room.type, 1)
    view.has_more = total > PAGE_SIZE
    view.messages = views_for(session, msgs)
    return RoomPageResult(ok=True, value=view, error="")


def messages_page(session, room_id: int, user_id: int, before_id: int, after_id: int):
    if not _member(session, room_id, user_id):
        return MessagesPageResult(ok=False, value=[], error="not a member")
    M = Message.__sqlmodel__
    if before_id > 0:
        anchor = session.get(M, before_id)
        if anchor is None or anchor.room_id != room_id:
            return MessagesPageResult(ok=False, value=[], error="message not found")
        rows = session.exec(
            select(M)
            .where(
                M.room_id == room_id,
                ((M.created_at < anchor.created_at)
                 | ((M.created_at == anchor.created_at) & (M.id < anchor.id))),
            )
            .order_by(M.created_at.desc(), M.id.desc())
            .limit(PAGE_SIZE)
        ).all()
        msgs = list(reversed(rows))
    elif after_id > 0:
        anchor = session.get(M, after_id)
        if anchor is None or anchor.room_id != room_id:
            return MessagesPageResult(ok=False, value=[], error="message not found")
        msgs = list(session.exec(
            select(M)
            .where(
                M.room_id == room_id,
                ((M.created_at > anchor.created_at)
                 | ((M.created_at == anchor.created_at) & (M.id > anchor.id))),
            )
            .order_by(M.created_at.asc(), M.id.asc())
            .limit(PAGE_SIZE)
        ).all())
    else:
        rows = session.exec(
            select(M)
            .where(M.room_id == room_id)
            .order_by(M.created_at.desc(), M.id.desc())
            .limit(PAGE_SIZE)
        ).all()
        msgs = list(reversed(rows))
    return MessagesPageResult(ok=True, value=views_for(session, msgs), error="")


def sidebar(session, user_id: int) -> SidebarResult:
    U = User.__sqlmodel__
    if session.get(U, user_id) is None:
        return SidebarResult(ok=False, value=[], error="user not found")
    MM = Membership.__sqlmodel__
    R = Room.__sqlmodel__
    rows = session.exec(
        select(MM, R)
        .join(R, R.id == MM.room_id)
        .where(MM.user_id == user_id, MM.involvement != "invisible")
        .order_by(func.lower(R.name), R.id)
    ).all()
    out = []
    for m, r in rows:
        e = SidebarEntry()
        e.room_id = r.id
        e.room_name = r.name
        e.room_kind = ROOM_TYPE_TO_KIND.get(r.type, 1)
        e.unread = m.unread_at not in (None, 0)
        e.involvement = INVOLVEMENT_TO_ID.get(m.involvement, 2)
        out.append(e)
    return SidebarResult(ok=True, value=out, error="")


def search_page(session, user_id: int, query: str, limit: int):
    U = User.__sqlmodel__
    if session.get(U, user_id) is None:
        return SearchPageResult(ok=False, value=[], error="user not found")
    # Raw query to FTS5 like Rails (idx.body MATCH ?); the porter tokenizer
    # runs identically on indexed bodies and the query.
    if query.strip() == "":
        return SearchPageResult(ok=True, value=[], error="")
    MM = Membership.__sqlmodel__
    room_ids = list(session.exec(
        select(MM.room_id).where(
            MM.user_id == user_id,
            MM.involvement != "invisible",
        )
    ).all())
    if not room_ids:
        return SearchPageResult(ok=True, value=[], error="")
    M = Message.__sqlmodel__
    placeholders = ", ".join(str(r) for r in room_ids)
    sql = (
        "SELECT messages.* FROM messages "
        "JOIN message_search_index ON messages.id = message_search_index.rowid "
        "WHERE message_search_index MATCH :q AND messages.room_id IN (%s) "
        "ORDER BY messages.created_at LIMIT :n" % placeholders
    )
    try:
        rows = session.exec(
            text(sql).bindparams(q=query.strip(), n=limit)).mappings().all()
    except Exception:  # noqa: BLE001 - FTS5 syntax in user input
        session.rollback()
        return SearchPageResult(ok=True, value=[], error="")
    R = Room.__sqlmodel__
    names = {r.id: r.name for r in session.exec(select(R)).all()}
    msgs = []
    for row in rows:
        m = M(
            id=row["id"], room_id=row["room_id"],
            creator_id=row["creator_id"],
            client_message_id=row["client_message_id"],
            created_at=row["created_at"],
        )
        msgs.append(m)
    views = views_for(session, msgs)
    out = []
    for v in views:
        hit = SearchHitView()
        hit.message = v
        mid_rows = [m for m in msgs if m.id == v.id]
        if mid_rows:
            hit.room_name = names.get(mid_rows[0].room_id, "")
        out.append(hit)
    return SearchPageResult(ok=True, value=out, error="")


def post_message_view(session, room_id: int, creator_id: int, body: str,
                      client_message_id: str, now: int):
    from campfile.domain import campfire as c
    M = Message.__sqlmodel__
    MM = Membership.__sqlmodel__
    if session.get(Room.__sqlmodel__, room_id) is None:
        return c.MessageResult(ok=False, error="room not found")
    mem = session.exec(
        select(MM).where(MM.room_id == room_id, MM.user_id == creator_id)
    ).first()
    if mem is None:
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
            "AND (connected_at IS NULL OR connected_at <= :cutoff)"
        ).bindparams(now=stamp, rid=room_id, uid=creator_id, cutoff=cutoff)
    )
    session.commit()
    session.refresh(row)
    return c.MessageResult(ok=True, value=row)


# ---------------------------------------------------------------------------
# Session auth (bcrypt + token rows, Flask-signed cookie at the route layer)
# ---------------------------------------------------------------------------

SESSION_TTL_REFRESH = 3600


def authenticate(session, email: str, password: str):
    """Return the user row when email+bcrypt verify and status allows."""
    import bcrypt
    U = User.__sqlmodel__
    row = session.exec(
        select(U).where(U.email_address == email)
    ).first()
    if row is None or not row.password_digest:
        return None
    try:
        ok = bcrypt.checkpw(password.encode("utf-8"),
                            row.password_digest.encode("utf-8"))
    except ValueError:
        return None
    if not ok:
        return None
    if row.status != 0:
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
    if not token:
        return None
    S = UserSession.__sqlmodel__
    U = User.__sqlmodel__
    row = session.exec(select(S).where(S.token == token)).first()
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
    S = UserSession.__sqlmodel__
    row = session.exec(select(S).where(S.token == token)).first()
    if row is not None:
        session.delete(row)
        session.commit()
