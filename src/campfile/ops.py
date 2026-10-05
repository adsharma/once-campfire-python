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

import bcrypt
from sqlalchemy import text

from campfile import fq as _fq

from campfile.db import (
    
    ROOM_KIND_TO_TYPE,
    Account,
    Ban,
    Boost,
    Membership,
    Message,
    PushSubscription,
    RichText,
    Room,
    SearchRecord,
    User,
    UserSession,
    Webhook,
    to_db_time,
)

TYPE_TO_KIND = {v: k for k, v in ROOM_KIND_TO_TYPE.items()}


def room_access(db, uid: int, rid: int):
    """(Room row, Membership row|None) scoped to a member, like get_room."""
    _fq.use_db(db)
    R = Room.__sqlmodel__
    M = Membership.__sqlmodel__
    room = db.get(R, rid)
    if room is None:
        return None, None
    mem = (_fq.MembershipQuery([])
                     .where(_fq.pred(
                         'membership.room_id == param("rid")'
                         ' and membership.user_id == param("uid")'))
                     .take(1).project(["membership.id"])).bind(**({"rid": rid, "uid": uid})).rows()
    if not mem:
        return None, None
    return room, db.get(M, mem[0]["id"])


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
    _fq.use_db(db)
    R = Room.__sqlmodel__
    M = Membership.__sqlmodel__
    rooms = (_fq.RoomQuery([])
                     .where(_fq.pred('room.type == param("t")'))
                     .project(["room.id"])).bind(**({"t": "Rooms::Open"})).rows()
    for room in rooms:
        have = (_fq.MembershipQuery([])
                         .where(_fq.pred(
                             'membership.room_id == param("rid")'
                             ' and membership.user_id == param("uid")'))
                         .count()).bind(**({"rid": room["id"], "uid": user_id})).rows()
        if not have or have[0]["COUNT(*)"] == 0:
            db.add(M(room_id=room["id"], user_id=user_id,
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
    _fq.use_db(db)
    M = Membership.__sqlmodel__
    R = Room.__sqlmodel__
    stamp = to_db_time(now)
    mems = (_fq.MembershipQuery([])
                       .where(_fq.pred('membership.user_id == param("uid")'))
                       .project(["membership.id", "membership.room_id"])).bind(**({"uid": row.id})).rows()
    for mem in mems:
        room = db.get(R, mem["room_id"])
        if room is not None and room.type != "Rooms::Direct":
            old = db.get(M, mem["id"])
            if old is not None:
                db.delete(old)
    for model, qcls in ((PushSubscription, _fq.PushSubscriptionQuery),
                         (SearchRecord, _fq.SearchRecordQuery),
                         (UserSession, _fq.UserSessionQuery)):
        T = model.__sqlmodel__
        prefix = _fq.alias(qcls)
        olds = (qcls([])
                         .where(_fq.pred('%s.user_id == param("uid")' % prefix))
                         .project(["%s.id" % prefix])).bind(**({"uid": row.id})).rows()
        for old in olds:
            gone = db.get(T, old["id"])
            if gone is not None:
                db.delete(gone)
    row.status = 1
    if row.email_address:
        row.email_address = row.email_address.replace(
            "@", "-deactivated-" + secrets.token_hex(8) + "@")
    row.updated_at = stamp
    db.add(row)
    db.commit()


def create_room(db, kind: int, name, creator_id: int, member_ids: list,
                now: int):
    _fq.use_db(db)
    from campfile.domain import campfire as c
    R = Room.__sqlmodel__
    M = Membership.__sqlmodel__
    stamp = to_db_time(now)
    if kind == c.ROOM_DIRECT:
        wanted = set(member_ids) | {creator_id}
        cands = (_fq.RoomQuery([])
                         .where(_fq.pred('room.type == param("t")'))
                         .project(["room.id"])).bind(**({"t": "Rooms::Direct"})).rows()
        for cand in cands:
            have = {m["user_id"] for m in (_fq.MembershipQuery([])
                .where(_fq.pred('membership.room_id == param("rid")'))
                .project(["membership.user_id"])).bind(**({"rid": cand["id"]})).rows()}
            if have == wanted:
                found = db.get(R, cand["id"])
                return {"id": found.id} if found is not None else None
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
    return {"id": row.id}


def revise_room(db, room, name, kind: int, member_ids, is_open_kind: bool,
                now: int):
    _fq.use_db(db)
    from campfile.domain import campfire as c
    M = Membership.__sqlmodel__
    U = User.__sqlmodel__
    if room.type != "Rooms::Direct":
        room.name = name
        room.type = ROOM_KIND_TO_TYPE[kind]
    room.updated_at = to_db_time(now)
    db.add(room)
    if is_open_kind:
        actives = (_fq.UserQuery([])
                           .where(_fq.pred("user.status == 0"))
                           .project(["user.id"])).rows()
        wanted = {u["id"] for u in actives}
    else:
        wanted = set(member_ids)
    for mem in (_fq.MembershipQuery([])
                        .where(_fq.pred('membership.room_id == param("rid")'))
                        .project(["membership.id", "membership.user_id"])).bind(**({"rid": room.id})).rows():
        if mem["user_id"] not in wanted:
            old = db.get(M, mem["id"])
            if old is not None:
                db.delete(old)
    have = {m["user_id"] for m in (_fq.MembershipQuery([])
        .where(_fq.pred('membership.room_id == param("rid")'))
        .project(["membership.user_id"])).bind(**({"rid": room.id})).rows()}
    involve = ("everything" if room.type == "Rooms::Direct" else "mentions")
    for uid in wanted - have:
        db.add(M(room_id=room.id, user_id=uid, involvement=involve))
    db.commit()
    return room


def delete_room_cascade(db, room_id: int):
    _fq.use_db(db)
    M = Membership.__sqlmodel__
    R = Room.__sqlmodel__
    rows = (_fq.MessageQuery([])
                    .where(_fq.pred('message.room_id == param("rid")'))
                    .project(["message.id"])).bind(**({"rid": room_id})).rows()
    for m in rows:
        delete_message_cascade(db, m["id"])
    for mem in (_fq.MembershipQuery([])
                        .where(_fq.pred('membership.room_id == param("rid")'))
                        .project(["membership.id"])).bind(**({"rid": room_id})).rows():
        old = db.get(M, mem["id"])
        if old is not None:
            db.delete(old)
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
    _fq.use_db(db)
    RT = RichText.__sqlmodel__
    stamp = to_db_time(now)
    found = (_fq.RichTextQuery([])
                     .where(_fq.pred(
                         'rich.record_type == param("t")'
                         ' and rich.record_id == param("mid")'
                         ' and rich.name == param("n")'))
                     .take(1).project(["rich.id"])).bind(**({"t": "Message", "mid": mid, "n": "body"})).rows()
    rich = db.get(RT, found[0]["id"]) if found else None
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
    _fq.use_db(db)
    B = Boost.__sqlmodel__
    RT = RichText.__sqlmodel__
    M = Message.__sqlmodel__
    for b in (_fq.BoostQuery([])
                       .where(_fq.pred('boost.message_id == param("mid")'))
                       .project(["boost.id"])).bind(**({"mid": mid})).rows():
        old_b = db.get(B, b["id"])
        if old_b is not None:
            db.delete(old_b)
    for rich in (_fq.RichTextQuery([])
                         .where(_fq.pred(
                             'rich.record_type == param("t")'
                             ' and rich.record_id == param("mid")'))
                         .project(["rich.id"])).bind(**({"t": "Message", "mid": mid})).rows():
        old_r = db.get(RT, rich["id"])
        if old_r is not None:
            db.delete(old_r)
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
    _fq.use_db(db)
    B = Boost.__sqlmodel__
    found = (_fq.BoostQuery([])
                     .where(_fq.pred(
                         'boost.id == param("bid")'
                         ' and boost.message_id == param("mid")'
                         ' and boost.booster_id == param("uid")'))
                     .take(1).project(["boost.id"])).bind(**({"bid": bid, "mid": mid, "uid": uid})).rows()
    if not found:
        return False
    row = db.get(B, found[0]["id"])
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def record_search(db, uid: int, query: str, now: int):
    _fq.use_db(db)
    from campfile.domain import campfire as c
    S = SearchRecord.__sqlmodel__
    stamp = to_db_time(now)
    found = (_fq.SearchRecordQuery([])
                     .where(_fq.pred(
                         'search.user_id == param("uid")'
                         ' and search.query == param("q")'))
                     .take(1).project(["search.id"])).bind(**({"uid": uid, "q": query})).rows()
    if not found:
        db.add(S(user_id=uid, query=query, created_at=stamp,
                 updated_at=stamp))
    else:
        row = db.get(S, found[0]["id"])
        if row is not None:
            row.updated_at = stamp
            db.add(row)
    db.commit()
    ids = [r["id"] for r in (_fq.SearchRecordQuery([])
        .where(_fq.pred('search.user_id == param("uid")'))
        .order_by(_fq.order("desc(search.updated_at)"))
        .project(["search.id"])).bind(**({"uid": uid})).rows()]
    for stale in ids[c.MAX_RECENT_SEARCHES:]:
        old = db.get(S, stale)
        if old is not None:
            db.delete(old)
    db.commit()


def clear_searches(db, uid: int):
    _fq.use_db(db)
    S = SearchRecord.__sqlmodel__
    for r in (_fq.SearchRecordQuery([])
                      .where(_fq.pred('search.user_id == param("uid")'))
                      .project(["search.id"])).bind(**({"uid": uid})).rows():
        row = db.get(S, r["id"])
        if row is not None:
            db.delete(row)
    db.commit()


def recent_searches(db, uid: int) -> list:
    _fq.use_db(db)
    return [r["query"] for r in (_fq.SearchRecordQuery([])
        .where(_fq.pred('search.user_id == param("uid")'))
        .order_by(_fq.order("desc(search.updated_at)"))
        .take(10).project(["search.query"])).bind(**({"uid": uid})).rows()]


def pushsub_upsert(db, uid: int, endpoint: str, p256dh: str, auth: str,
                   agent: str, now: int):
    _fq.use_db(db)
    P = PushSubscription.__sqlmodel__
    if not (endpoint or "").strip():
        return None
    stamp = to_db_time(now)
    found = (_fq.PushSubscriptionQuery([])
                     .where(_fq.pred(
                         'push.user_id == param("uid")'
                         ' and push.endpoint == param("ep")'))
                     .take(1).project(["push.id"])).bind(**({"uid": uid, "ep": endpoint})).rows()
    row = db.get(P, found[0]["id"]) if found else None
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
    _fq.use_db(db)
    return (_fq.PushSubscriptionQuery([])
                    .where(_fq.pred('push.user_id == param("uid")'))
                    .project(["push.id", "push.endpoint", "push.user_agent"])).bind(**({"uid": uid})).rows()


def pushsub_delete(db, uid: int, sid: int) -> bool:
    _fq.use_db(db)
    P = PushSubscription.__sqlmodel__
    found = (_fq.PushSubscriptionQuery([])
                     .where(_fq.pred(
                         'push.id == param("sid")'
                         ' and push.user_id == param("uid")'))
                     .take(1).project(["push.id"])).bind(**({"sid": sid, "uid": uid})).rows()
    if not found:
        return False
    row = db.get(P, found[0]["id"])
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def account_row(db):
    _fq.use_db(db)
    A = Account.__sqlmodel__
    found = (_fq.AccountQuery([]).take(1).project(["account.id"])).rows()
    if not found:
        return None
    return db.get(A, found[0]["id"])


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
    _fq.use_db(db)
    S = UserSession.__sqlmodel__
    B = Ban.__sqlmodel__
    stamp = to_db_time(now)
    sess = (_fq.UserSessionQuery([])
                    .where(_fq.pred('sess.user_id == param("uid")'))
                    .project(["sess.id", "sess.ip_address"])).bind(**({"uid": row.id})).rows()
    ips = {x["ip_address"] for x in sess if x["ip_address"]}
    for x in sess:
        old_s = db.get(S, x["id"])
        if old_s is not None:
            db.delete(old_s)
    for old in (_fq.BanQuery([])
                        .where(_fq.pred('ban.user_id == param("uid")'))
                        .project(["ban.id"])).bind(**({"uid": row.id})).rows():
        gone = db.get(B, old["id"])
        if gone is not None:
            db.delete(gone)
    for ip in ips:
        db.add(B(user_id=row.id, ip_address=ip, created_at=stamp,
                 updated_at=stamp))
    row.status = 2
    row.updated_at = stamp
    db.add(row)
    db.commit()
    return len(ips)


def unban_user(db, row, now: int):
    _fq.use_db(db)
    B = Ban.__sqlmodel__
    for old in (_fq.BanQuery([])
                        .where(_fq.pred('ban.user_id == param("uid")'))
                        .project(["ban.id"])).bind(**({"uid": row.id})).rows():
        gone = db.get(B, old["id"])
        if gone is not None:
            db.delete(gone)
    row.status = 0
    row.updated_at = to_db_time(now)
    db.add(row)
    db.commit()


def bot_upsert_webhook(db, bot_id: int, url: str, now: int):
    _fq.use_db(db)
    W = Webhook.__sqlmodel__
    found = (_fq.WebhookQuery([])
                     .where(_fq.pred('webhook.user_id == param("uid")'))
                     .take(1).project(["webhook.id"])).bind(**({"uid": bot_id})).rows()
    row = db.get(W, found[0]["id"]) if found else None
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
    _fq.use_db(db)
    found = (_fq.WebhookQuery([])
                     .where(_fq.pred('webhook.user_id == param("uid")'))
                     .take(1).project(["webhook.url"])).bind(**({"uid": bot_id})).rows()
    return found[0]["url"] if found else ""


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
