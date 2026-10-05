"""Prototype: sidebar read via fquery chains, byte-identical to db.exec.

Declares @node/@query bindings for Membership/Room, builds the sidebar
chain (filter + join + project + order), runs it with the new fquery
SQL visitor + to_rows runner, and diffs the SidebarEntry payloads
against queries.sidebar (the db.exec implementation).
"""

import ast
import sqlite3
import tempfile
from dataclasses import asdict, dataclass
from typing import List

from fquery.query import query
from fquery.view_model import edge, node
from fquery.walk import JoinOn

from campfile import queries as q
from campfile.db import (
    INVOLVEMENT_TO_ID,
    ROOM_TYPE_TO_KIND,
    create_schema,
    get_engine,
    load_store,
)
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
class MembershipNode:
    QUERY_NAME = "MembershipQuery"
    user_id: int = 0
    room_id: int = 0
    involvement: str = ""
    unread_at: str = ""

    @edge
    async def room(self) -> List["RoomNode"]:
        yield []


@node
@dataclass
class RoomNode:
    QUERY_NAME = "RoomQuery"
    name: str = ""
    type: str = ""

    @edge
    async def memberships(self) -> List["MembershipNode"]:
        yield []


@query
class MembershipQuery:
    TYPE = MembershipNode
    TABLE = "memberships"


@query
class RoomQuery:
    TYPE = RoomNode
    TABLE = "rooms"


path = tempfile.mktemp(suffix=".db")
engine = get_engine("sqlite:///" + path)
create_schema(engine)
load_store(engine, w.seed_store(6, 60, 11))

from sqlmodel import Session

with Session(engine) as db:
    expected = q.sidebar(db, 2)
    check("seed sidebar ok", expected.ok)
    want = [asdict(e) for e in expected.value]

conn = sqlite3.connect(path)
chain = (
    MembershipQuery([])
    .where(ast.Expr(
        "membership.user_id == 2 and membership.involvement != 'invisible'"))
    .edge("room", JoinOn("room_id", "id"))
    .project(["membership.involvement", "membership.unread_at", "room.id",
              "room.name", "room.type"])
    .order_by(ast.Expr("lower(room.name), room.id"))
)
print("SQL:", chain.to_sql_string())
rows = chain.to_rows(conn)
got = []
for r in rows:
    got.append({
        "room_id": r["id"],
        "room_name": r["name"],
        "room_kind": ROOM_TYPE_TO_KIND.get(r["type"], 1),
        "unread": r["unread_at"] not in (None, 0),
        "involvement": INVOLVEMENT_TO_ID.get(r["involvement"], 2),
    })

check("row count", len(got) == len(want))
check("byte-identical", got == want)
if got != want:
    print("want:", want[:2])
    print("got: ", got[:2])

print("passed: " + str(PASSED) + ", failed: " + str(FAILED))
if FAILED > 0:
    raise SystemExit(1)
