"""DB parity tests: SQLite/sqlmodel stack vs the in-memory workload."""

from sqlmodel import Session, func, select
from sqlalchemy import text

from campfile import queries as q
from campfile.db import Message, Room, User, create_schema, get_engine, load_store
from campfile.domain import workload as w

PASSED = 0
FAILED = 0


def check(label, cond):
    global PASSED, FAILED
    if cond:
        PASSED += 1
    else:
        FAILED += 1
        print("FAIL: " + label)


store = w.seed_store(8, 200, 7)
engine = get_engine("sqlite:///:memory:")
create_schema(engine)
counts = load_store(engine, store)
check("messages loaded", counts["messages"] == 200)
check("fts rows", counts["fts"] == 200)

uid = store.users[0].id
gid = store.rooms[0].id

with Session(engine) as db:
    # --- room page parity --------------------------------------------------
    mem = w.room_page(store, gid, uid)
    got = q.room_page(db, gid, uid)
    check("room page ok", got.ok and mem.ok)
    check("room page ids", [m.id for m in got.value.messages] ==
          [m.id for m in mem.value.messages])
    check("room page names", all(
        a.creator_name == b.creator_name
        for a, b in zip(got.value.messages, mem.value.messages)))
    check("room page boosts", all(
        sorted(a.boosts) == sorted(b.boosts)
        for a, b in zip(got.value.messages, mem.value.messages)))
    check("has_more", got.value.has_more == mem.value.has_more)

    # --- messages page parity ----------------------------------------------
    anchor = store.messages[100].id
    mem2 = w.messages_page(store, gid, uid, anchor, 0)
    got2 = q.messages_page(db, gid, uid, anchor, 0)
    check("page before ids", [m.id for m in got2.value] ==
          [m.id for m in mem2.value])
    mem3 = w.messages_page(store, gid, uid, 0, anchor)
    got3 = q.messages_page(db, gid, uid, 0, anchor)
    check("page after ids", [m.id for m in got3.value] ==
          [m.id for m in mem3.value])

    # --- sidebar parity ------------------------------------------------------
    mem4 = w.sidebar(store, uid)
    got4 = q.sidebar(db, uid)
    check("sidebar rooms", [(e.room_id, e.unread) for e in got4.value] ==
          [(e.room_id, e.unread) for e in mem4.value])

    # --- search parity (same id SET; ranking may differ TF vs BM25) ---------
    mem5 = w.search_page(store, w.build_search_index(store), uid, "coffee", 20)
    got5 = q.search_page(db, uid, "coffee", 20)
    check("search ok", got5.ok)
    # Same id set (ranking differs: TF-count vs BM25); top-20 order may vary.
    full_mem = {h.message.id for h in w.search_page(
        store, w.build_search_index(store), uid, "coffee", 500).value}
    full_db = {h.message.id for h in q.search_page(db, uid, "coffee", 500).value}
    check("search full set", full_mem == full_db and len(full_db) > 0)
    got6 = q.search_page(db, uid, "zzzzqqqq", 20)
    check("search empty", got6.ok and got6.value == [])

    # --- post ------------------------------------------------------------------
    import time as _time
    res = q.post_message_view(db, gid, uid, "hello coffee world", "db1",
                              int(_time.time()))
    check("post ok", res.ok and res.value["client_message_id"] == "db1")
    from campfile.db import RichText
    bodies = {r.record_id: r.body for r in db.exec(select(RichText.__sqlmodel__)).all()
              if r.name == "body"}
    check("post body", bodies.get(res.value["id"]) == "hello coffee world")
    got7 = q.search_page(db, uid, "hello", 20)
    check("post indexed", any(h.message.id == res.value["id"] for h in got7.value))
    from campfile.db import Membership
    others = db.exec(select(Membership.__sqlmodel__).where(
        Membership.__sqlmodel__.room_id == gid)).all()
    marked = [m.user_id for m in others
              if m.user_id != uid and m.unread_at not in (None, 0)]
    check("unread fanned", len(marked) == len(others) - 1)

    # --- triggers --------------------------------------------------------------
    mid = res.value["id"]
    row = db.get(Message.__sqlmodel__, mid)
    rt = db.exec(select(RichText.__sqlmodel__).where(
        RichText.__sqlmodel__.record_type == "Message",
        RichText.__sqlmodel__.record_id == mid,
        RichText.__sqlmodel__.name == "body")).one()
    rt.body = "totally unrelated zebra xylophone"
    db.add(rt)
    db.commit()
    check("update reindexed",
          q.search_page(db, uid, "xylophone", 20).ok and any(
              h.message.id == mid
              for h in q.search_page(db, uid, "xylophone", 20).value))
    check("old term gone", all(
        h.message.id != mid
        for h in q.search_page(db, uid, "hello", 100).value))
    db.delete(row)
    db.commit()
    check("delete deindexed", all(
        h.message.id != mid
        for h in q.search_page(db, uid, "xylophone", 100).value))

print("passed: " + str(PASSED) + ", failed: " + str(FAILED))
if FAILED > 0:
    raise SystemExit(1)
