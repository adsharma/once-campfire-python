"""Tests for the workload layer: porter, seed, pages, search, post."""

from campfile.domain import campfire as c
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


# --- porter -----------------------------------------------------------------
check("caresses", w.porter_stem("caresses") == "caress")
check("ponies", w.porter_stem("ponies") == "poni")
check("caress", w.porter_stem("caress") == "caress")
check("cats", w.porter_stem("cats") == "cat")
check("running", w.porter_stem("running") == "run")
check("happy", w.porter_stem("happy") == "happi")
check("relational", w.porter_stem("relational") == "relat")
check("coffee", w.porter_stem("coffee") == "coffe")
check("searches", w.porter_stem("searches") == "search")
check("rooms", w.porter_stem("rooms") == "room")
check("short", w.porter_stem("at") == "at")
check("tokenize", w.tokenize("Hi @Bob, coffee x2!") == ["hi", "bob", "coffee", "x2"])

# --- seed --------------------------------------------------------------------
s = w.seed_store(8, 200, 7)
check("users", len(s.users) == 8)
check("messages", len(s.messages) == 200)
check("rooms", len(s.rooms) == 2)
check("ordered times", all(
    s.messages[i].created_at <= s.messages[i + 1].created_at
    for i in range(len(s.messages) - 1)))
uid = s.users[0].id
gid = s.rooms[0].id
idx = w.build_search_index(s)
check("index terms", len(idx.postings) > 20)
check("index docs", idx.doc_count == 200)

# --- pages ---------------------------------------------------------------------
rp = w.room_page(s, gid, uid)
check("room page ok", rp.ok)
check("room page size", len(rp.value.messages) == 40)
check("room page more", rp.value.has_more)
check("presentation names", all(m.creator_name != "" for m in rp.value.messages))
mid = s.messages[100].id
mp = w.messages_page(s, gid, uid, mid, 0)
check("page before", mp.ok and len(mp.value) > 0 and mp.value[len(mp.value) - 1].id < mid)
mp2 = w.messages_page(s, gid, uid, 0, mid)
check("page after", mp2.ok and len(mp2.value) > 0 and mp2.value[0].id > mid)
check("non-member blocked", not w.room_page(s, gid, 999999).ok)
sb = w.sidebar(s, uid)
check("sidebar", sb.ok and len(sb.value) == 2)
check("sidebar ordered", sb.value[0].room_name <= sb.value[1].room_name)

# --- search ----------------------------------------------------------------------
sp = w.search_page(s, idx, uid, "coffee", 20)
check("search hits", sp.ok and len(sp.value) > 0)
check("search rooms", all(h.room_name != "" for h in sp.value))
sp2 = w.search_page(s, idx, uid, "zzzzqqqq", 20)
check("search empty", sp2.ok and len(sp2.value) == 0)
sp3 = w.search_page(s, idx, uid, "", 20)
check("search blank", sp3.ok and len(sp3.value) == 0)

# --- post --------------------------------------------------------------------------
import time as _time
posted = w.post_message_view(s, gid, uid, "hello coffee world", "t1", int(_time.time()))
check("post ok", posted.ok and posted.value.client_message_id == "t1")
v = w.build_message_view(s, posted.value)
check("post view", v.creator_name == "user0" and v.content_type == "text")
check("post unread", s.memberships[1].unread_at != 0)

print("passed: " + str(PASSED) + ", failed: " + str(FAILED))
if FAILED > 0:
    raise SystemExit(1)
