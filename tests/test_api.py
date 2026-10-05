"""Broad API coverage: management, bots, account, people, onboarding."""

import tempfile

from campfile import create_app
from campfile.domain import campfire as c

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
    USERS = 6
    MESSAGES = 60
    SEED = 11
    DB_URL = "sqlite:///%s" % tempfile.mktemp(suffix=".db")
    SECRET_KEY = "test-secret"
    SEED_PASSWORD = "password"


app = create_app(TestConfig)
client = app.test_client()
admin = app.test_client()
admin.post("/session", json={"email_address": "user0@example.com",
                             "password": "password"})
client.post("/session", json={"email_address": "user1@example.com",
                              "password": "password"})

entries = client.get("/users/me/sidebar").get_json()
wc = [e["room_id"] for e in entries if e["room_name"] == "Watercooler"][0]
first_msg = client.get("/rooms/%d/messages" % wc).get_json()[0]
mid = first_msg["id"]

# --- message show/edit/delete --------------------------------------------------
r = client.get("/rooms/%d/messages/%d" % (wc, mid))
check("show", r.status_code == 200 and r.get_json()["id"] == mid)
r = client.post("/rooms/%d/messages" % wc, json={"body": "mine to edit"})
mine = r.get_json()["id"]
r = client.patch("/rooms/%d/messages/%d" % (wc, mine),
                 json={"body": "edited body text"})
check("edit own", r.status_code == 200
      and r.get_json()["body"] == "edited body text")
r = client.post("/rooms/%d/messages" % wc, json={"body": "admin target"})
target = r.get_json()["id"]
r = client.patch("/rooms/%d/messages/%d" % (wc, target),
                 json={"body": "admin edits others"})
check("admin edits others", r.status_code == 200)
outsider = app.test_client()
outsider.post("/session", json={"email_address": "user5@example.com",
                                "password": "password"})
r = outsider.patch("/rooms/%d/messages/%d" % (wc, target),
                   json={"body": "hijack"})
check("non-admin edit forbidden", r.status_code == 403)
r = outsider.delete("/rooms/%d/messages/%d" % (wc, target))
check("non-admin delete forbidden", r.status_code == 403)
r = admin.delete("/rooms/%d/messages/%d" % (wc, target))
check("admin delete", r.status_code == 204)
r = client.get("/rooms/%d/messages/%d" % (wc, target))
check("deleted gone", r.status_code == 404)

# --- boosts ----------------------------------------------------------------------
r = client.post("/messages/%d/boosts" % mid, json={"content": "+1"})
check("boost", r.status_code == 201)
bid = r.get_json()["id"]
r = client.post("/messages/%d/boosts" % mid,
                json={"content": "x" * 17})
check("long boost 422", r.status_code == 422)
r = client.get("/messages/%d/boosts" % mid)
check("boost list", any(b["id"] == bid for b in r.get_json()))
r = outsider.delete("/messages/%d/boosts/%d" % (mid, bid))
check("foreign boost delete 404", r.status_code == 404)
r = client.delete("/messages/%d/boosts/%d" % (mid, bid))
check("boost delete", r.status_code == 204)

# --- involvement -------------------------------------------------------------------
r = client.put("/rooms/%d/involvement" % wc,
               json={"involvement": "everything"})
check("involvement", r.get_json()["involvement"] == "everything")
r = client.put("/rooms/%d/involvement" % wc, json={"involvement": "bogus"})
check("bad involvement 422", r.status_code == 422)
r = client.get("/rooms/%d/settings" % wc)
check("settings alias", r.status_code == 200)

# --- refresh -------------------------------------------------------------------------
r = client.get("/rooms/%d/refresh?since=1" % wc)
check("refresh", r.status_code == 200 and "new" in r.get_json())

# --- rooms CRUD ------------------------------------------------------------------------
r = client.post("/rooms/closeds", json={"name": "Secret",
                                        "user_ids": [2, 3]})
check("room create", r.status_code == 201)
new_rid = r.get_json()["room_id"] if "room_id" in r.get_json() else None
if new_rid is None:
    new_rid = r.get_json().get("room", {}).get("id", 0)
check("room payload", new_rid > 0)
r = client.patch("/rooms/closeds/%d" % new_rid,
                   json={"name": "Renamed", "user_ids": [2, 3]})
check("room rename", r.status_code == 200
      and r.get_json()["room_name"] == "Renamed")
r = outsider.delete("/rooms/closeds/%d" % new_rid)
check("non-admin room delete forbidden", r.status_code in (403, 404))
r = admin.delete("/rooms/closeds/%d" % new_rid)
check("room delete", r.status_code == 200)
r = client.post("/rooms/directs", json={"user_ids": [3]})
check("direct create", r.status_code == 201)
r = client.post("/rooms/directs", json={"user_ids": [3]})
check("direct dedupe", r.status_code == 201)

# --- autocomplete ------------------------------------------------------------------------
r = client.get("/autocompletable/users?filter=user")
check("autocomplete", r.status_code == 200 and len(r.get_json()) > 0)

# --- profile -------------------------------------------------------------------------------
r = client.patch("/users/me/profile", json={"user": {"bio": "hello bio"}})
check("profile update", r.get_json()["bio"] == "hello bio")
r = client.get("/users/2")
check("user show", r.get_json()["id"] == 2)

# --- account (admin) ---------------------------------------------------------------------------
r = client.get("/account")
check("account view", r.status_code == 200 and "members" in r.get_json())
r = client.patch("/account", json={"account": {"name": "Hacked"}})
check("non-admin account write forbidden", r.status_code == 403)
r = admin.patch("/account", json={"account": {"name": "Acme"}})
check("account rename", r.get_json()["name"] == "Acme")
r = admin.patch("/account",
                json={"account": {"settings": {
                    "restrict_room_creation_to_administrators": True}}})
check("settings write", r.get_json()["settings"][
    "restrict_room_creation_to_administrators"] is True)
r = client.post("/rooms/closeds", json={"name": "Nope", "user_ids": []})
check("restricted creation", r.status_code == 403)
r = admin.patch("/account", json={"account": {"settings": {}}})
r = admin.post("/account/join_code")
code = r.get_json()["join_code"]
check("join code reset", len(code) > 10)

# --- users admin -----------------------------------------------------------------------------
r = admin.patch("/account/users/3", json={"user": {"role": "administrator"}})
check("promote", r.get_json()["role"] == 1)
r = admin.delete("/account/users/4")
check("deactivate", r.get_json()["status"] == 1)
r = app.test_client().post(
    "/session", json={"email_address": "user2@example.com",
                      "password": "password"})
check("deactivated cannot login", r.status_code == 401)

# --- bots ------------------------------------------------------------------------------------
r = outsider.post("/account/bots", json={"user": {"name": "Helper"}})
check("non-admin bot create forbidden", r.status_code == 403)
r = admin.post("/account/bots", json={"user": {"name": "Helper"}})
check("bot create", r.status_code == 201)
bot_id = r.get_json()["id"]
bot_key = r.get_json()["key"]
r = admin.get("/account/bots")
check("bot list", any(b["id"] == bot_id for b in r.get_json()))
r = admin.put("/account/bots/%d/key" % bot_id)
check("bot key reset", r.get_json()["key"] != bot_key)
bot_key = r.get_json()["key"]
r = admin.patch("/rooms/opens/%d" % wc, json={"name": "Watercooler"})
check("open revise grants all", r.status_code == 200)
r = app.test_client().get("/rooms/%d/%s/messages" % (wc, "bad-key"))
check("bad bot key 401", r.status_code == 401)
r = app.test_client().get("/rooms/%d/%s/messages" % (wc, bot_key))
check("bot list 204/200", r.status_code in (200, 204))
r = app.test_client().post("/rooms/%d/%s/messages" % (wc, bot_key),
                           data="beep from bot",
                           content_type="text/plain")
check("bot post", r.status_code == 201 and "Location" in r.headers)
posted_id = int(r.headers["Location"].rsplit("/", 1)[-1])
r = app.test_client().post(
    "/rooms/%d/%s/messages/%d/boosts" % (wc, bot_key, posted_id),
    data="+1", content_type="text/plain")
check("bot boost", r.status_code == 201
      and r.get_json()["booster"]["role"] == "bot")
bbid = r.get_json()["id"]
r = app.test_client().delete(
    "/rooms/%d/%s/messages/%d/boosts/%d" % (wc, bot_key, posted_id, bbid))
check("bot boost delete", r.status_code == 204)
r = admin.delete("/account/bots/%d" % bot_id)
check("bot delete", r.get_json()["status"] == 1)

# --- ban ---------------------------------------------------------------------------------------
r = outsider.post("/users/5/ban")
check("non-admin ban forbidden", r.status_code == 403)
r = admin.post("/users/5/ban")
check("ban", r.get_json()["status"] == 2)
r = app.test_client().post("/session", json={"email_address":
                                             "user3@example.com",
                                             "password": "password"})
check("banned cannot login", r.status_code == 401)
r = admin.delete("/users/5/ban")
check("unban", r.get_json()["status"] == 0)

# --- searches ------------------------------------------------------------------------------------
r = client.post("/searches", json={"q": "coffee"})
check("record search", "coffee" in r.get_json()["recent"])
r = client.get("/searches?q=coffee")
check("search recent", "coffee" in r.get_json()["recent"])
r = client.post("/searches/clear")
check("clear searches", r.get_json()["recent"] == [])

# --- push ------------------------------------------------------------------------------------------
r = client.post("/users/me/push_subscriptions",
                json={"endpoint": "https://push.example/x"})
check("push store", r.status_code == 200)
sid = r.get_json()["id"]
r = client.get("/users/me/push_subscriptions")
check("push list", any(p["id"] == sid for p in r.get_json()))
r = client.delete("/users/me/push_subscriptions/%d" % sid)
check("push delete", r.get_json()["deleted"] == sid)

# --- custom styles -----------------------------------------------------------------------------------
r = admin.put("/account/custom_styles",
              json={"account": {"custom_styles": "body{}"}})
check("styles", r.get_json()["custom_styles"] == "body{}")

# --- join + first run ----------------------------------------------------------------------------------
joiner = app.test_client()
r = joiner.post("/join/%s" % code, json={"name": "Newbie",
                                         "email_address": "newbie@example.com",
                                         "password": "password"})
check("join", r.status_code == 201)
r = joiner.get("/users/me/sidebar")
check("joiner sees open rooms", r.status_code == 200
      and len(r.get_json()) >= 1)
r = joiner.post("/join/bad-code", json={"name": "X",
                                        "email_address": "x@example.com",
                                        "password": "password"})
check("bad join code 404", r.status_code == 404)

print("passed: " + str(PASSED) + ", failed: " + str(FAILED))
if FAILED > 0:
    raise SystemExit(1)
