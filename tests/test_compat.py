"""Schema interchange: this port reads/writes the Rails/Django database.

Builds an empty database from ../once-campfire-django/campfire/schema.sql
(the Rails schema verbatim), inserts rows in Rails storage form (datetime
strings, string enums), and drives the campfile queries over it. Proves the
table/column contract both directions (see also test_db.py for ours).
"""

from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session

from campfile.db import create_schema, get_engine

PASSED = 0
FAILED = 0


def check(label, cond):
    global PASSED, FAILED
    if cond:
        PASSED += 1
    else:
        FAILED += 1
        print("FAIL: " + label)


SCHEMA = (Path("/Users/arun/src/once-campfire-django/campfire/schema.sql")
          .read_text())

T0 = "2026-10-04 12:00:00.000000"
T1 = "2026-10-04 12:00:01.000000"

engine = get_engine("sqlite:///:memory:")
with engine.connect() as conn:
    for stmt in SCHEMA.split(";"):
        stmt = stmt.strip()
        if stmt and not stmt.startswith("--"):
            try:
                conn.exec_driver_sql(stmt)
            except Exception as e:  # noqa: BLE001
                if "already exists" not in str(e):
                    raise
    # Our FTS triggers against their exact table definitions.
    from campfile.db import TRIGGER_SQL
    for trigger in TRIGGER_SQL:
        conn.exec_driver_sql(trigger)
    conn.commit()

with Session(engine) as db:
    db.exec(text(
        "INSERT INTO accounts (id, created_at, join_code, name, updated_at)"
        " VALUES (1, '%s', 'AbcD-ef12-3456', 'Acme', '%s')" % (T0, T0)))
    db.exec(text(
        "INSERT INTO users (id, name, email_address, password_digest, role,"
        " status, created_at, updated_at)"
        " VALUES (1, 'amy', 'amy@x.com', 'digest', 1, 0, '%s', '%s'),"
        "        (2, 'bob', 'bob@x.com', 'digest', 0, 0, '%s', '%s')" % (T0, T0, T0, T0)))
    db.exec(text(
        "INSERT INTO rooms (id, name, type, creator_id, created_at,"
        " updated_at) VALUES (1, 'Watercooler', 'Rooms::Open', 1, '%s', '%s')" % (T0, T0)))
    db.exec(text(
        "INSERT INTO memberships (room_id, user_id, involvement,"
        " connections, created_at, updated_at)"
        " VALUES (1, 1, 'mentions', 0, '%s', '%s'),"
        "        (1, 2, 'mentions', 0, '%s', '%s')" % (T0, T0, T0, T0)))
    db.exec(text(
        "INSERT INTO messages (id, room_id, creator_id,"
        " client_message_id, created_at, updated_at)"
        " VALUES (1, 1, 1, 'c1', '%s', '%s'),"
        "        (2, 1, 2, 'c2', '%s', '%s')" % (T0, T0, T1, T1)))
    db.exec(text(
        "INSERT INTO action_text_rich_texts (record_type, record_id, name,"
        " body, created_at, updated_at)"
        " VALUES ('Message', 1, 'body', 'need coffee beans', '%s', '%s'),"
        "        ('Message', 2, 'body', 'tea instead', '%s', '%s')" % (T0, T0, T1, T1)))

    db.commit()

    from campfile import queries as q

    rp = q.room_page(db, 1, 1)
    check("room page", rp.ok and len(rp.value.messages) == 2)
    check("room kind mapped", rp.value.room_kind == 0)
    check("creator names", [m.creator_name for m in rp.value.messages] ==
          ["amy", "bob"])
    check("order", [m.id for m in rp.value.messages] == [1, 2])

    sb = q.sidebar(db, 2)
    check("sidebar", sb.ok and len(sb.value) == 1 and
          sb.value[0].involvement == 2)

    sp = q.search_page(db, 2, "coffee", 20)
    check("search", sp.ok and [h.message.id for h in sp.value] == [1])

    import time as _time
    posted = q.post_message_view(db, 1, 2, "more coffee please", "c3",
                                 int(_time.time()))
    check("post", posted.ok)
    sp2 = q.search_page(db, 2, "coffee", 20)
    check("post searchable", {h.message.id for h in sp2.value} >= {1, posted.value["id"]})

    mp = q.messages_page(db, 1, 1, posted.value["id"], 0)
    check("page before post", mp.ok and
          [m.id for m in mp.value] == [1, 2])

print("passed: " + str(PASSED) + ", failed: " + str(FAILED))
if FAILED > 0:
    raise SystemExit(1)
