"""Write/admin operations (JSON-API mirrors of the Django domain module).

Reads live in queries.py; this module owns creates/updates/deletes plus
the admin surface (users, bots, bans, account). Rules mirror
once-campfire-django/campfire/domain.py and views.py: open-room grants on
user creation, membership recheck inside message writes, unread fan-out to
disconnected members, capped search history, bot token/key handling. Turbo
publishes, push delivery, media processing and jobs are intentionally not
mirrored (see README boundaries).
"""

import json
import secrets
import time

import bcrypt
from sqlalchemy import func, text
from sqlmodel import select

from campfile.db import (
    INVOLVEMENT_TO_ID,
    ROOM_KIND_TO_TYPE,
    Account,
    Ban,
    Boost,
    Membership,
    Message,
    MessageMention,
    PushSubscription,
    RichText,
    Room,
    SearchRecord,
    User,
    UserSession,
    Webhook,
    from_db_time,
    to_db_time,
)

TYPE_TO_KIND = {v: k for k, v in ROOM_KIND_TO_TYPE.items()}


def room_access(db, uid: int, rid: int):
    """(Room row, Membership row|None) scoped to a member, like get_room."""
    R = Room.__sqlmodel__
    M = Membership.__sqlmodel__
    room = db.get(R, rid)
    if room is None:
        return None, None
    mem = db.exec(select(M).where(M.room_id == rid,
                                 M.user_id == uid)).first()
    if mem is None:
        return None, None
    return room, mem


def bot_auth(db, key: str):
    """Bot row for a '<id>-<token>' key, else None (401 upstream)."""
    from campfile.domain import campfire as c
    U = User.__sqlmodel__
    if "-" not in (key or ""):
        return None
    parsed = c.parse_bot_key(key.strip())
    if not parsed.ok:
        return None
    row = db.get(U, parsed.value)
    if row is None or row.role != 2 or row.status != 0:
        return None
    if not row.bot_token or key.strip() != (str(row.id) + "-" + row.bot_token):
        return None
    return row


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72],
                         bcrypt.gensalt()).decode()


def grant_open_rooms(db, user_id: int):
    R = Room.__sqlmodel__
    M = Membership.__sqlmodel__
    for room in db.exec(select(R).where(R.type == "Rooms::Open")).all():
        if db.exec(select(func.count(M.id)).where(
                M.room_id == room.id, M.user_id == user_id)).one() == 0:
            db.add(M(room_id=room.id, user_id=user_id,
                     involvement="mentions"))


def create_user(db, name: str, email: str, password: str, role: int,
                bot_token: str, now: int):
    from campfile.domain import campfire as c
    U = User.__sqlmodel__
    stamp = to_db_time(now)
    row = U(name=name, email_address=email or None,
            password_digest=hash_password(password) if password else None,
            role=role, status=0, bot_token=bot_token or None,
            created_at=stamp, updated_at=stamp)
    db.add(row)
    try:
        db.commit()
    except Exception:
        db.rollback()
        return None
    db.refresh(row)
    if role != c.ROLE_BOT:
        grant_open_rooms(db, row.id)
        db.commit()
    return row


def update_profile(db, row, name, bio, email, password, now: int):
    if name is not None:
        row.name = name
    if bio is not None:
        row.bio = bio
    if email is not None:
        row.email_address = email
    if password:
        row.password_digest = hash_password(password)
    row.updated_at = to_db_time(now)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def set_role(db, row, role: int, now: int):
    row.role = role
    row.updated_at = to_db_time(now)
    db.add(row)
    db.commit()


def deactivate_user(db, row, now: int):
    """Mirrors Django deactivate: strip memberships (keep directs), drop
    push/searches/sessions, mark status, rewrite email."""
    M = Membership.__sqlmodel__
    R = Room.__sqlmodel__
    stamp = to_db_time(now)
    for mem in db.exec(select(M).where(M.user_id == row.id)).all():
        room = db.get(R, mem.room_id)
        if room is not None and room.type != "Rooms::Direct":
            db.delete(mem)
    for model in (PushSubscription, SearchRecord, UserSession):
        T = model.__sqlmodel__
        col = T.user_id if hasattr(T, "user_id") else T.user
        for old in db.exec(select(T).where(col == row.id)).all():
            db.delete(old)
    row.status = 1
    if row.email_address:
        row.email_address = row.email_address.replace(
            "@", "-deactivated-" + secrets.token_hex(8) + "@")
    row.updated_at = stamp
    db.add(row)
    db.commit()


def create_room(db, kind: int, name, creator_id: int, member_ids: list,
                now: int):
    from campfile.domain import campfire as c
    R = Room.__sqlmodel__
    M = Membership.__sqlmodel__
    stamp = to_db_time(now)
    if kind == c.ROOM_DIRECT:
        wanted = set(member_ids) | {creator_id}
        for cand in db.exec(select(R).where(R.type == "Rooms::Direct")).all():
            have = {m.user_id for m in db.exec(
                select(M).where(M.room_id == cand.id)).all()}
            if have == wanted:
                return cand
        name = None
    row = R(name=name, type=ROOM_KIND_TO_TYPE[kind], creator_id=creator_id,
            created_at=stamp, updated_at=stamp)
    db.add(row)
    db.commit()
    db.refresh(row)
    involve = ("everything" if kind == c.ROOM_DIRECT else "mentions")
    for uid in (set(member_ids) | {creator_id}):
        db.add(M(room_id=row.id, user_id=uid, involvement=involve))
    db.commit()
    return row


def revise_room(db, room, name, kind: int, member_ids, is_open_kind: bool,
                now: int):
    from campfile.domain import campfire as c
    M = Membership.__sqlmodel__
    U = User.__sqlmodel__
    if room.type != "Rooms::Direct":
        room.name = name
        room.type = ROOM_KIND_TO_TYPE[kind]
    room.updated_at = to_db_time(now)
    db.add(room)
    if is_open_kind:
        wanted = {u.id for u in db.exec(
            select(U).where(U.status == 0)).all()}
    else:
        wanted = set(member_ids)
    for mem in db.exec(select(M).where(M.room_id == room.id)).all():
        if mem.user_id not in wanted:
            db.delete(mem)
    have = {m.user_id for m in db.exec(
        select(M).where(M.room_id == room.id)).all()}
    involve = ("everything" if room.type == "Rooms::Direct" else "mentions")
    for uid in wanted - have:
        db.add(M(room_id=room.id, user_id=uid, involvement=involve))
    db.commit()
    return room


def delete_room_cascade(db, room_id: int):
    M = Membership.__sqlmodel__
    R = Room.__sqlmodel__
    rows = db.exec(select(Message.__sqlmodel__).where(
        Message.__sqlmodel__.room_id == room_id)).all()
    for m in rows:
        delete_message_cascade(db, m.id)
    for mem in db.exec(select(M).where(M.room_id == room_id)).all():
        db.delete(mem)
    room = db.get(R, room_id)
    if room is not None:
        db.delete(room)
    db.commit()


def set_involvement(db, mem, choice: str, now: int):
    mem.involvement = choice
    mem.updated_at = to_db_time(now)
    db.add(mem)
    db.commit()


def touch_room(db, room_id: int, now: int):
    db.exec(text("UPDATE rooms SET updated_at = :t WHERE id = :rid")
            .bindparams(t=to_db_time(now), rid=room_id))


def update_message_body(db, mid: int, body: str, now: int) -> bool:
    RT = RichText.__sqlmodel__
    stamp = to_db_time(now)
    rich = db.exec(select(RT).where(
        RT.record_type == "Message", RT.record_id == mid,
        RT.name == "body")).first()
    if rich is None:
        db.add(RT(record_type="Message", record_id=mid, name="body",
                  body=body, created_at=stamp, updated_at=stamp))
    else:
        rich.body = body
        rich.updated_at = stamp
        db.add(rich)
    db.exec(text("UPDATE messages SET updated_at = :t WHERE id = :mid")
            .bindparams(t=stamp, mid=mid))
    db.commit()
    return True


def delete_message_cascade(db, mid: int):
    B = Boost.__sqlmodel__
    RT = RichText.__sqlmodel__
    M = Message.__sqlmodel__
    for b in db.exec(select(B).where(B.message_id == mid)).all():
        db.delete(b)
    for rich in db.exec(select(RT).where(
            RT.record_type == "Message",
            RT.record_id == mid)).all():
        db.delete(rich)
    row = db.get(M, mid)
    if row is not None:
        room_id = row.room_id
        db.delete(row)
        db.commit()
        return room_id
    db.commit()
    return None


def create_boost(db, mid: int, uid: int, content: str, now: int):
    from campfile.domain import campfire as c
    B = Boost.__sqlmodel__
    text_value = (content or "").strip()
    if not text_value or len(text_value) > c.BOOST_MAX_LEN:
        return None
    stamp = to_db_time(now)
    row = B(message_id=mid, booster_id=uid, content=text_value,
            created_at=stamp, updated_at=stamp)
    db.add(row)
    db.exec(text("UPDATE messages SET updated_at = :t WHERE id = :mid")
            .bindparams(t=stamp, mid=mid))
    db.commit()
    db.refresh(row)
    return row


def delete_boost(db, bid: int, mid: int, uid: int) -> bool:
    B = Boost.__sqlmodel__
    row = db.exec(select(B).where(B.id == bid, B.message_id == mid,
                                 B.booster_id == uid)).first()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def record_search(db, uid: int, query: str, now: int):
    from campfile.domain import campfire as c
    S = SearchRecord.__sqlmodel__
    stamp = to_db_time(now)
    row = db.exec(select(S).where(S.user_id == uid,
                                 S.query == query)).first()
    if row is None:
        db.add(S(user_id=uid, query=query, created_at=stamp,
                 updated_at=stamp))
    else:
        row.updated_at = stamp
        db.add(row)
    db.commit()
    ids = [r.id for r in db.exec(select(S).where(S.user_id == uid).order_by(
        text("updated_at DESC"))).all()]
    for stale in ids[c.MAX_RECENT_SEARCHES:]:
        old = db.get(S, stale)
        if old is not None:
            db.delete(old)
    db.commit()


def clear_searches(db, uid: int):
    S = SearchRecord.__sqlmodel__
    for row in db.exec(select(S).where(S.user_id == uid)).all():
        db.delete(row)
    db.commit()


def recent_searches(db, uid: int) -> list:
    S = SearchRecord.__sqlmodel__
    return [r.query for r in db.exec(select(S).where(
        S.user_id == uid).order_by(text("updated_at DESC")).limit(10)).all()]


def pushsub_upsert(db, uid: int, endpoint: str, p256dh: str, auth: str,
                   agent: str, now: int):
    P = PushSubscription.__sqlmodel__
    if not (endpoint or "").strip():
        return None
    stamp = to_db_time(now)
    row = db.exec(select(P).where(P.user_id == uid,
                                 P.endpoint == endpoint)).first()
    if row is None:
        row = P(user_id=uid, endpoint=endpoint, p256dh_key=p256dh or "",
                auth_key=auth or "", user_agent=agent or "",
                created_at=stamp, updated_at=stamp)
    else:
        row.p256dh_key = p256dh or ""
        row.auth_key = auth or ""
        row.user_agent = agent or ""
        row.updated_at = stamp
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def pushsub_list(db, uid: int) -> list:
    P = PushSubscription.__sqlmodel__
    return db.exec(select(P).where(P.user_id == uid)).all()


def pushsub_delete(db, uid: int, sid: int) -> bool:
    P = PushSubscription.__sqlmodel__
    row = db.exec(select(P).where(P.id == sid,
                                 P.user_id == uid)).first()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def account_row(db):
    A = Account.__sqlmodel__
    return db.exec(select(A)).first()


def update_account(db, row, name, settings: dict, now: int):
    if name is not None:
        row.name = name
    if settings is not None:
        row.settings = json.dumps(settings)
    row.updated_at = to_db_time(now)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_styles(db, row, styles: str, now: int):
    row.custom_styles = styles or ""
    row.updated_at = to_db_time(now)
    db.add(row)
    db.commit()


def reset_join_code(db, row, now: int):
    row.join_code = secrets.token_urlsafe(18)
    row.updated_at = to_db_time(now)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.join_code


def ban_user(db, row, now: int) -> int:
    S = UserSession.__sqlmodel__
    B = Ban.__sqlmodel__
    stamp = to_db_time(now)
    ips = {s.ip_address for s in db.exec(
        select(S).where(S.user_id == row.id)).all()
        if s.ip_address}
    for s in db.exec(select(S).where(S.user_id == row.id)).all():
        db.delete(s)
    for old in db.exec(select(B).where(B.user_id == row.id)).all():
        db.delete(old)
    for ip in ips:
        db.add(B(user_id=row.id, ip_address=ip, created_at=stamp,
                 updated_at=stamp))
    row.status = 2
    row.updated_at = stamp
    db.add(row)
    db.commit()
    return len(ips)


def unban_user(db, row, now: int):
    B = Ban.__sqlmodel__
    for old in db.exec(select(B).where(B.user_id == row.id)).all():
        db.delete(old)
    row.status = 0
    row.updated_at = to_db_time(now)
    db.add(row)
    db.commit()


def bot_upsert_webhook(db, bot_id: int, url: str, now: int):
    W = Webhook.__sqlmodel__
    row = db.exec(select(W).where(W.user_id == bot_id)).first()
    if url:
        if row is None:
            row = W(user_id=bot_id, url=url,
                    created_at=to_db_time(now),
                    updated_at=to_db_time(now))
        else:
            row.url = url
            row.updated_at = to_db_time(now)
        db.add(row)
    elif row is not None:
        db.delete(row)
    db.commit()


def bot_webhook(db, bot_id: int) -> str:
    W = Webhook.__sqlmodel__
    row = db.exec(select(W).where(W.user_id == bot_id)).first()
    return row.url if row is not None else ""


def first_run_create(db, name: str, email: str, password: str, now: int):
    from campfile.domain import campfire as c
    A = Account.__sqlmodel__
    stamp = to_db_time(now)
    account = A(name="Campfire", join_code=secrets.token_urlsafe(18),
                created_at=stamp, updated_at=stamp)
    db.add(account)
    db.commit()
    user = create_user(db, name, email, password, c.ROLE_ADMIN, "", now)
    room = create_room(db, c.ROOM_OPEN, "All Talk", user.id, [user.id], now)
    return account, user, room
