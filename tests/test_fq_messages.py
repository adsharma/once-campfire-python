"""Prototype round 2: messages paging, LIKE, COUNT, IN, IS NULL via chains."""

import ast
import sqlite3
import tempfile

from fquery.query import query
from fquery.view_model import edge, node
from fquery.walk import JoinOn
from dataclasses import dataclass
from typing import List

from campfile import queries as q
from campfile.db import create_schema, get_engine, load_store
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


@node
@dataclass
class MessageNode:
    QUERY_NAME = "MessageQuery"
    room_id: int = 0
    creator_id: int = 0
    created_at: str = ""
    client_message_id: str = ""


@node
@dataclass
class UserNode:
    QUERY_NAME = "UserQuery"
    name: str = ""
    status: int = 0


@node
@dataclass
class MembershipNode2:
    QUERY_NAME = "MembershipQuery2"
    connected_at: str = ""


@query
class MessageQuery:
    TYPE = MessageNode
    TABLE = "messages"


@query
class UserQuery:
    TYPE = UserNode
    TABLE = "users"


@query
class MembershipQuery2:
    TYPE = MembershipNode2
    TABLE = "memberships"
    ALIAS = "mm"


path = tempfile.mktemp(suffix=".db")
engine = get_engine("sqlite:///" + path)
create_schema(engine)
load_store(engine, w.seed_store(6, 200, 11))

from sqlmodel import Session

with Session(engine) as db:
    sb = q.sidebar(db, 2)
    RID = [e.room_id for e in sb.value if e.room_name == "Watercooler"][0]
    res = q.messages_page(db, RID, 2, 0, 0)
    check("seed page ok", res.ok)
    want_ids = [m.id for m in res.value]
    anchor = want_ids[10]
    res_before = q.messages_page(db, RID, 2, anchor, 0)
    want_before = [m.id for m in res_before.value]
    cnt = q.search_page(db, 2, "coffee", 100)
    n_hits = len(cnt.value)

conn = sqlite3.connect(path)

# latest window, DESC keyset
rows = (MessageQuery([])
        .where(ast.Expr("message.room_id == " + str(RID)))
        .order_by(ast.Expr("desc(message.created_at), desc(message.id)"))
        .take(40)
        .project(["message.id"])
        .to_rows(conn))
got_ids = list(reversed([r["id"] for r in rows]))
check("latest window", got_ids == want_ids)

# before-anchor with OR keyset
anchor_row = conn.execute(
    "SELECT created_at FROM messages WHERE id = ?", (anchor,)).fetchone()
rows = (MessageQuery([])
        .where(ast.Expr(
            "message.room_id == " + str(RID) + " and (message.created_at < '%s' or "
            "(message.created_at == '%s' and message.id < %d))" % (
                anchor_row[0], anchor_row[0], anchor)))
        .order_by(ast.Expr("desc(message.created_at), desc(message.id)"))
        .take(40)
        .project(["message.id"])
        .to_rows(conn))
check("before keyset", list(reversed([r["id"] for r in rows])) == want_before)

# LIKE autocomplete
rows = (UserQuery([])
        .where(ast.Expr("like(user.name, '%user%') and user.status == 0"))
        .order_by(ast.Expr("user.name"))
        .take(20)
        .project(["user.id", "user.name"])
        .to_rows(conn))
check("like count", len(rows) == 6)
check("like order", [r["name"] for r in rows] == sorted(
    r["name"] for r in rows))

# COUNT
n = (MessageQuery([])
     .where(ast.Expr("message.room_id == " + str(RID)))
     .count()
     .to_rows(conn))
check("count", n[0]["COUNT(*)"] == 200)

# IN + empty IN + IS NULL
rows = (MessageQuery([])
        .where(ast.Expr("message.room_id in [" + str(RID) + ", " + str(RID + 1) + "]"))
        .project(["message.id"])
        .to_rows(conn))
check("in", len(rows) == 200)
rows = (MessageQuery([])
        .where(ast.Expr("message.room_id in []"))
        .project(["message.id"])
        .to_rows(conn))
check("empty in", rows == [])
rows = (MembershipQuery2([])
        .where(ast.Expr("mm.connected_at is None"))
        .project(["mm.id"])
        .to_rows(conn))
total_mm = conn.execute("SELECT COUNT(*) FROM memberships").fetchone()[0]
check("is null", len(rows) == total_mm)

print("passed: " + str(PASSED) + ", failed: " + str(FAILED))
if FAILED > 0:
    raise SystemExit(1)
