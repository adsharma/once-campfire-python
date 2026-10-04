""" runnable tests for campfire.py (CPython only, not transpiled). """

try:
    from py2many.spec import CHECKER  # noqa: F401
except ImportError:
    import sys
    import types

    class _Checker:
        pre = False
        post = False
        invariant = False

    _spec = types.ModuleType("py2many.spec")
    _spec.CHECKER = _Checker()
    _spec.result = None
    _pkg = types.ModuleType("py2many")
    _pkg.spec = _spec
    sys.modules["py2many"] = _pkg
    sys.modules["py2many.spec"] = _spec

import campfire as c

PASSED = 0
FAILED = 0


def check(label, cond):
    global PASSED, FAILED
    if cond:
        PASSED += 1
    else:
        FAILED += 1
        print("FAIL: " + label)


NOW = 1700000000


def fresh_account(store):
    r = c.create_account(store, "Acme", "AbcDef123456", NOW)
    check("account created", r.ok)
    return r.value


# --- account / join codes -------------------------------------------------
s = c.Store()
fresh_account(s)
check("join code format", s.accounts[0].join_code == "AbcD-ef12-3456")
bad = c.create_account(s, "Bad", "short", NOW)
check("bad join token rejected", not bad.ok)
check("bad join token msg", bad.error != "")
r = c.reset_account_join_code(s, s.accounts[0].id, "ZZZZZZ999999", NOW)
check("join code reset", r.ok and r.value == "ZZZZ-ZZ99-9999")
check("deactivated email", c.deactivated_email("amy@example.com", "STAMP") == "amy-deactivated-STAMP@example.com")
check("deactivated empty email", c.deactivated_email("", "STAMP") == "")
check("initials", c.user_initials("Ada M Byron") == "AMB")
check("title with bio", c.user_title("Ada", "writes code") == "Ada - writes code")
check("title no bio", c.user_title("Ada", "") == "Ada")

# --- users ----------------------------------------------------------------
s = c.Store()
fresh_account(s)
admin = c.create_user(s, "Admin", "admin@x.com", c.ROLE_ADMIN, NOW, "")
check("admin created", admin.ok)
check("bad role rejected", not c.create_user(s, "X", "x@x.com", 7, NOW, "").ok)
check("empty name rejected", not c.create_user(s, "", "y@x.com", c.ROLE_MEMBER, NOW, "").ok)
check("dup email rejected", not c.create_user(s, "Dup", "admin@x.com", c.ROLE_MEMBER, NOW, "").ok)
bot = c.create_user(s, "Helper", "", c.ROLE_BOT, NOW, "BotToken1234")
check("bot created", bot.ok and bot.value.bot_token == "BotToken1234")
check("bot bad token rejected", not c.create_user(s, "B2", "", c.ROLE_BOT, NOW, "short").ok)
check("bot key roundtrip", c.bot_key_of(bot.value.id, "BotToken1234") == str(bot.value.id) + "-BotToken1234")
check("parse bot key", c.parse_bot_key(str(bot.value.id) + "-BotToken1234").value == bot.value.id)
check("parse bad bot key", not c.parse_bot_key("nonsense").ok)
check("auth bot", c.authenticate_bot(s, str(bot.value.id) + "-BotToken1234").ok)
check("auth bot wrong token fails", not c.authenticate_bot(s, str(bot.value.id) + "-WrongToken12").ok)

# --- rooms ----------------------------------------------------------------
member = c.create_user(s, "Amy", "amy@x.com", c.ROLE_MEMBER, NOW, "")
general = c.create_room(s, c.ROOM_OPEN, "General", admin.value.id, [admin.value.id, member.value.id], NOW)
check("open room created", general.ok)
check("memberships granted", len(s.memberships) == 2)
# late joiner auto-granted to open rooms
late = c.create_user(s, "Late", "late@x.com", c.ROLE_MEMBER, NOW, "")
check("late joiner granted open room", c.find_membership_index(s, general.value.id, late.value.id) >= 0)
closed = c.create_room(s, c.ROOM_CLOSED, "Secret", admin.value.id, [admin.value.id], NOW)
check("closed room", closed.ok)
check("late joiner not in closed", c.find_membership_index(s, closed.value.id, late.value.id) < 0)
check("open needs name", not c.create_room(s, c.ROOM_OPEN, "", admin.value.id, [], NOW).ok)
dm = c.find_or_create_direct_room(s, admin.value.id, [admin.value.id, member.value.id], NOW)
check("direct created", dm.ok and dm.value.kind == c.ROOM_DIRECT)
dm2 = c.find_or_create_direct_room(s, admin.value.id, [member.value.id, admin.value.id], NOW)
check("direct singleton", dm2.ok and dm2.value.id == dm.value.id)
check("direct default involvement", s.memberships[c.find_membership_index(s, dm.value.id, member.value.id)].involvement == c.INVOLVEMENT_EVERYTHING)
check("open default involvement", s.memberships[c.find_membership_index(s, general.value.id, member.value.id)].involvement == c.INVOLVEMENT_MENTIONS)
blocked = c.convert_room_kind(s, dm.value.id, c.ROOM_OPEN, NOW)
check("direct type frozen", not blocked.ok)
conv = c.convert_room_kind(s, closed.value.id, c.ROOM_OPEN, NOW)
check("closed->open converts", conv.ok)
check("convert grants all active", c.find_membership_index(s, closed.value.id, late.value.id) >= 0)

# --- administer -------------------------------------------------------------
check("admin can administer anything", c.can_administer(c.ROLE_ADMIN, 99, 100, False))
check("owner can administer own", c.can_administer(c.ROLE_MEMBER, 5, 5, False))
check("non-owner blocked", not c.can_administer(c.ROLE_MEMBER, 5, 6, False))
check("anyone on new record", c.can_administer(c.ROLE_MEMBER, 5, 6, True))
check("room creation restricted", not c.can_create_room(c.ROLE_MEMBER, True))
check("admin bypasses restriction", c.can_create_room(c.ROLE_ADMIN, True))
check("open creation allowed", c.can_create_room(c.ROLE_MEMBER, False))

# --- messages + unread -------------------------------------------------------
s2 = c.Store()
fresh_account(s2)
a = c.create_user(s2, "A", "a@x.com", c.ROLE_ADMIN, NOW, "").value
b = c.create_user(s2, "B", "b@x.com", c.ROLE_MEMBER, NOW, "").value
g = c.create_room(s2, c.ROOM_OPEN, "General", a.id, [a.id, b.id], NOW).value
m1 = c.post_message(s2, g.id, a.id, "hello @B", "", [b.id], "c1", NOW)
check("message posted", m1.ok and m1.value.client_message_id == "c1")
check("push recorded", "push:" + str(g.id) + ":" + str(m1.value.id) in s2.outbox)
bi = c.find_membership_index(s2, g.id, b.id)
ai = c.find_membership_index(s2, g.id, a.id)
check("disconnected member unread", s2.memberships[bi].unread_at == NOW)
check("creator not unread", s2.memberships[ai].unread_at == 0)
# connected member stays read
c.present_membership(s2, g.id, b.id, 1, NOW + 10)
m2 = c.post_message(s2, g.id, a.id, "again", "", [], "c2", NOW + 20)
check("connected member not unread", s2.memberships[bi].unread_at == 0)
check("read clears", c.read_membership(s2, g.id, b.id, NOW + 30))
# invisible member never unread
c.set_involvement(s2, g.id, b.id, c.INVOLVEMENT_INVISIBLE, NOW + 30)
m3 = c.post_message(s2, g.id, a.id, "third", "", [], "c3", NOW + 40)
check("invisible member not unread", s2.memberships[bi].unread_at == 0)
check("non-member cannot post", not c.post_message(s2, g.id, 9999, "x", "", [], "c9", NOW).ok)
check("empty message rejected", not c.post_message(s2, g.id, a.id, "", "", [], "ce", NOW).ok)
att = c.post_message(s2, g.id, a.id, "", "photo.png", [], "c4", NOW + 50)
check("attachment message", att.ok)
check("plain body falls back to filename", c.message_plain_body(att.value.body, att.value.attachment_name) == "photo.png")
check("mentionees intersect members", c.message_mentionees(s2, m1.value) == [b.id])
check("strip mention", c.strip_mention("hi @B there", "B") == "hi  there")

# --- pagination ---------------------------------------------------------------
s3 = c.Store()
fresh_account(s3)
u = c.create_user(s3, "U", "u@x.com", c.ROLE_MEMBER, NOW, "").value
r3 = c.create_room(s3, c.ROOM_OPEN, "Big", u.id, [u.id], NOW).value
t = NOW
for i in range(45):
    t += 1
    rr = c.post_message(s3, r3.id, u.id, "msg" + str(i), "", [], "cc" + str(i), t)
    check("msg posted " + str(i), rr.ok)
msgs = c.room_messages(s3, r3.id)
check("45 messages", len(msgs) == 45)
check("paged", c.is_paged(msgs))
lp = c.last_page(msgs)
check("last page size", len(lp) == 40 and lp[0].body == "msg5")
fp = c.first_page(msgs)
check("first page size", len(fp) == 40 and fp[0].body == "msg0")
anchor = msgs[20]
bef = c.page_before(msgs, anchor.created_at, anchor.id)
check("page before", len(bef) == 20 and bef[len(bef) - 1].body == "msg19")
aft = c.page_after(msgs, anchor.created_at, anchor.id)
check("page after", len(aft) == 24 and aft[0].body == "msg21")
ar = c.page_around(msgs, anchor)
check("page around", len(ar) == 45 and ar[20].body == "msg20")

# --- sounds -------------------------------------------------------------------
check("play cmd", c.sound_command("/play tada") == "tada")
check("play trailing junk", c.sound_command("/play tada now") == "")
check("play empty", c.sound_command("/play ") == "")
check("not a command", c.sound_command("hello") == "")
sounds = c.builtin_sounds()
check("sound catalog nonempty", len(sounds) > 40)
check("find tada", c.find_sound(sounds, "tada").ok)
check("unknown sound", not c.find_sound(sounds, "nope").ok)
check("text type", c.content_type_of(False, "") == c.CONTENT_TEXT)
check("attachment type", c.content_type_of(True, "") == c.CONTENT_ATTACHMENT)
check("sound type", c.content_type_of(False, "tada") == c.CONTENT_SOUND)

# --- boosts ---------------------------------------------------------------------
bo = c.boost_message(s2, m1.value.id, b.id, "tada", NOW + 60)
check("boost ok", bo.ok)
check("boost too long", not c.boost_message(s2, m1.value.id, b.id, "0123456789abcdefg", NOW).ok)
check("boost missing msg", not c.boost_message(s2, 424242, b.id, "tada", NOW).ok)

# --- bans -------------------------------------------------------------------------
check("public v4 ok", c.validate_ban_ip("8.8.8.8").ok)
check("loopback rejected", c.validate_ban_ip("127.0.0.1").error == "cannot be a private or internal IP address")
check("private10 rejected", not c.validate_ban_ip("10.1.2.3").ok)
check("private172 rejected", not c.validate_ban_ip("172.20.5.4").ok)
check("public172 ok", c.validate_ban_ip("172.32.0.1").ok)
check("private192 rejected", not c.validate_ban_ip("192.168.1.1").ok)
check("linklocal rejected", not c.validate_ban_ip("169.254.9.9").ok)
check("garbage rejected", c.validate_ban_ip("nope").error == "is not a valid IP address")
check("short quad rejected", not c.validate_ban_ip("1.2.3").ok)
check("quad overflow rejected", not c.validate_ban_ip("1.2.3.999").ok)
check("v6 loopback rejected", not c.validate_ban_ip("::1").ok)
check("v6 linklocal rejected", not c.validate_ban_ip("fe80::1").ok)
check("v6 ulua rejected", not c.validate_ban_ip("fd00::5").ok)
check("v6 public ok", c.validate_ban_ip("2001:4860:4860::8888").ok)
ban = c.create_ban(s2, b.id, "8.8.8.8", NOW + 70)
check("ban created", ban.ok)
check("private ban rejected", not c.create_ban(s2, b.id, "10.0.0.1", NOW).ok)
check("is banned", c.is_banned_ip(s2, "8.8.8.8"))
check("not banned", not c.is_banned_ip(s2, "9.9.9.9"))

# --- sessions -----------------------------------------------------------------------
sess = c.start_session(s2, b.id, "tok-1", "8.8.8.8", "agent", NOW + 80)
check("session started", sess.ok)
check("no refresh yet", not c.touch_session(s2, sess.value.id, "agent2", "9.9.9.9", NOW + 90))
check("refresh after hour", c.touch_session(s2, sess.value.id, "agent2", "9.9.9.9", NOW + 80 + 3601))
si = c.find_session_index(s2, sess.value.id)
check("session updated", s2.sessions[si].ip_address == "9.9.9.9")

# --- searches --------------------------------------------------------------------------
for i in range(12):
    c.record_search(s2, b.id, "q" + str(i), NOW + 100 + i)
mine = 0
for sr in s2.searches:
    if sr.user_id == b.id:
        mine += 1
check("searches trimmed to 10", mine == 10)

# --- connections --------------------------------------------------------------------------
c.present_membership(s2, g.id, a.id, 2, NOW + 200)
ai2 = c.find_membership_index(s2, g.id, a.id)
check("present sets conns", s2.memberships[ai2].connections == 2)
check("present clears unread", s2.memberships[ai2].unread_at == 0)
c.disconnect_membership(s2, g.id, a.id, NOW + 201)
check("disconnect decrements", s2.memberships[ai2].connections == 1)
c.disconnect_membership(s2, g.id, a.id, NOW + 202)
c.disconnect_membership(s2, g.id, a.id, NOW + 203)
check("disconnect zeroes", s2.memberships[ai2].connections == 0 and s2.memberships[ai2].connected_at == 0)
c.disconnect_all(s2, NOW + 300)
still = False
for m in s2.memberships:
    if m.connected_at != 0:
        still = True
check("disconnect all", not still)

# --- ban user / unban / deactivate ----------------------------------------------------------
n = c.ban_user(s2, b.id, NOW + 400)
check("ban user bans sessions ips", n.ok and n.value >= 1)
check("user banned status", s2.users[c.find_user_index(s2, b.id)].status == c.STATUS_BANNED)
check("sessions cleared", len(s2.sessions) == 0)
check("unban", c.unban_user(s2, b.id, NOW + 500).ok)
check("unbanned status", s2.users[c.find_user_index(s2, b.id)].status == c.STATUS_ACTIVE)
c.start_session(s2, b.id, "tok-2", "1.1.1.1", "ag", NOW + 510)
c.record_search(s2, b.id, "zzz", NOW + 520)
dm_s2 = c.find_or_create_direct_room(s2, a.id, [a.id, b.id], NOW + 525)
check("direct room in s2", dm_s2.ok)
dmail = c.deactivate_user(s2, b.id, "STAMP9", NOW + 530)
check("deactivate ok", dmail.ok)
bu = s2.users[c.find_user_index(s2, b.id)]
check("deactivated status", bu.status == c.STATUS_DEACTIVATED)
check("email anonymized", bu.email == "b-deactivated-STAMP9@x.com")
check("non-direct memberships gone", c.find_membership_index(s2, g.id, b.id) < 0)
check("direct membership kept", c.find_membership_index(s2, dm_s2.value.id, b.id) >= 0)

# --- webhooks -------------------------------------------------------------------------------
wb = c.set_bot_webhook(s2, bot.value.id if 'bot' in dir() else 1, "https://bots.example/hook", NOW)
s4 = c.Store()
fresh_account(s4)
ba = c.create_user(s4, "BA", "ba@x.com", c.ROLE_ADMIN, NOW, "").value
bb = c.create_user(s4, "BB", "bb@x.com", c.ROLE_BOT, NOW, "Tok123456789").value
c.set_bot_webhook(s4, bb.id, "https://bots.example/hook", NOW)
gr = c.create_room(s4, c.ROOM_OPEN, "G", ba.id, [ba.id, bb.id], NOW).value
bm = c.post_message(s4, gr.id, ba.id, "hi @BB", "", [bb.id], "w1", NOW + 1)
check("bot webhook queued", ("webhook:" + str(bb.id) + ":" + str(bm.value.id)) in s4.outbox)
payload = c.build_webhook_payload(bb.id, bb.name, gr.id, gr.name, "/rooms/1", bm.value.id, "/m/1", "<p>hi</p>", "hi")
check("payload mentions user", '"id":' + str(bb.id) in payload)
check("text reply kind", c.webhook_reply_kind("text/plain") == "text")
check("attachment reply kind", c.webhook_reply_kind("image/png") == "attachment")
check("none reply kind", c.webhook_reply_kind("application/octet-stream") == "none")
tr = c.apply_webhook_reply(s4, gr.id, bb.id, "text/plain", "got it", NOW + 2, "w2")
check("text reply posted", tr.ok and tr.value.body == "got it" and tr.value.creator_id == bb.id)
ar2 = c.apply_webhook_reply(s4, gr.id, bb.id, "image/png", "bytes", NOW + 3, "w3")
check("attachment reply posted", ar2.ok and ar2.value.attachment_name == "attachment.png")
check("timeout text", c.webhook_timeout_text() == "Failed to respond within 7 seconds")
check("attachment ext", c.webhook_attachment_ext("image/jpeg") == "jpg")

print("passed: " + str(PASSED) + ", failed: " + str(FAILED))
if FAILED > 0:
    raise SystemExit(1)
