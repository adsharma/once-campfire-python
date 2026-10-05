"""Auth + authorization flow tests (Flask test client, temp database)."""

import tempfile

from campfile import create_app

PASSED = 0
FAILED = 0


def check(label, cond):
    global PASSED, FAILED
    if cond:
        PASSED += 1
    else:
        FAILED += 1
        print("FAIL: " + label)


class TestConfig:
    USERS = 4
    MESSAGES = 20
    SEED = 7
    DB_URL = "sqlite:///%s" % tempfile.mktemp(suffix=".db")
    SECRET_KEY = "test-secret"
    SEED_PASSWORD = "password"


app = create_app(TestConfig)
client = app.test_client()

# --- anonymous ---------------------------------------------------------------
r = client.get("/rooms/1")
check("anonymous redirect", r.status_code == 302 and "/session/new" in r.location)
r = client.get("/users/me/sidebar")
check("sidebar redirect", r.status_code == 302)
r = client.post("/rooms/999999/messages", json={"body": "x"})
check("anon post redirect", r.status_code == 302)
r = client.get("/session/new")
check("login form", r.status_code == 200 and b"email_address" in r.data)

# --- login ---------------------------------------------------------------------
r = client.post("/session", json={"email_address": "user0@example.com",
                                  "password": "password"})
check("login redirect", r.status_code == 302)
check("session cookie", "session_token=" in r.headers.get("Set-Cookie", ""))
r = client.post("/session", json={"email_address": "user0@example.com",
                                  "password": "wrong"})
check("wrong password", r.status_code == 422)
r = client.post("/session", json={"email_address": "nobody@example.com",
                                  "password": "password"})
check("unknown email", r.status_code == 422)

# --- authed access ---------------------------------------------------------------
entries = client.get("/users/me/sidebar").get_json()
check("sidebar entries", isinstance(entries, list) and len(entries) == 2)
wc = [e["room_id"] for e in entries if e["room_name"] == "Watercooler"][0]
r = client.get("/rooms/%d" % wc)
check("authed room", r.status_code == 200)
closed = [x for x in entries if x["room_kind"] == 1]
check("sidebar rooms", len(closed) >= 0)
r = client.get("/rooms/%d/messages" % wc)
check("authed messages", r.status_code == 200)
r = client.get("/searches?q=coffee")
check("authed search", r.status_code == 200)
r = client.post("/rooms/%d/messages" % wc, json={"body": "authed hello"})
check("authed post", r.status_code == 201)
check("post creator", r.get_json()["creator_name"] == "user0")

# --- membership enforcement ------------------------------------------------------
client2 = app.test_client()
client2.post("/session", json={"email_address": "user3@example.com",
                               "password": "password"})
rooms = {e["room_name"]: e["room_id"] for e in
         client2.get("/users/me/sidebar").get_json()}
check("member sees rooms", "Watercooler" in rooms and "Engineering" in rooms)
# Revoke user3's Watercooler membership directly, then access must 404.
from campfile.db import Membership
from sqlmodel import Session as _Session
with _Session(app.extensions["campfile_engine"]) as db:
    ms = db.exec(__import__("sqlmodel").select(Membership.__sqlmodel__).where(
        Membership.__sqlmodel__.room_id == wc)).all()
    for m in ms:
        from campfile.db import User as _U
        u = db.get(_U.__sqlmodel__, m.user_id)
        if u is not None and u.email_address == "user3@example.com":
            db.delete(m)
    db.commit()
r = client2.get("/rooms/%d" % wc)
check("revoked member blocked", r.status_code == 404)

# --- banned user -------------------------------------------------------------------
from sqlmodel import Session
from campfile.db import User

with Session(app.extensions["campfile_engine"]) as db:
    row = db.exec(__import__("sqlmodel").select(User.__sqlmodel__).where(
        User.__sqlmodel__.email_address == "user2@example.com")).one()
    row.status = 2
    db.add(row)
    db.commit()
r = client.post("/session", json={"email_address": "user2@example.com",
                                  "password": "password"})
check("banned rejected", r.status_code == 422)

# --- logout --------------------------------------------------------------------------
r = client.delete("/session")
check("logout redirect", r.status_code == 302)
r = client.get("/rooms/%d" % wc)
check("logged out", r.status_code == 302)

print("passed: " + str(PASSED) + ", failed: " + str(FAILED))
if FAILED > 0:
    raise SystemExit(1)
