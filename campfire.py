"""Campfire core domain in static python (see README.md for the full spec)."""
# A port of the business rules in ../once-campfire (Basecamp ONCE Campfire,
# a Rails app) into a subset of Python that transpiles to Rust and Go:
#   uvx py2many --rust campfire.py --outdir out_rust
#   uvx py2many --go campfire.py --outdir out_go
# Rules: int is the fixed-width integer (i32 Rust, int Go); composition
# over inheritance (Rails concerns are plain functions over dataclasses,
# STI room types are one Room struct plus a kind tag); Result structs
# instead of exceptions; bare asserts are pre/post contracts; no pattern
# matching, no isinstance, no slicing, no regex, no IO, no randomness.
# Not ported (not transpilable): ActiveRecord (in-memory Store instead),
# ActionCable (Store.outbox entries), ActiveStorage (filename strings),
# ActionText (body strings plus mention id lists), password hashing,
# signed ids, token generation, HTTP clients, web-push delivery.

from dataclasses import dataclass, field

from py2many.spec import CHECKER, result


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROLE_MEMBER: int = 0
ROLE_ADMIN: int = 1
ROLE_BOT: int = 2

STATUS_ACTIVE: int = 0
STATUS_DEACTIVATED: int = 1
STATUS_BANNED: int = 2

INVOLVEMENT_INVISIBLE: int = 0
INVOLVEMENT_NOTHING: int = 1
INVOLVEMENT_MENTIONS: int = 2
INVOLVEMENT_EVERYTHING: int = 3

ROOM_OPEN: int = 0
ROOM_CLOSED: int = 1
ROOM_DIRECT: int = 2

CONTENT_TEXT: int = 0
CONTENT_ATTACHMENT: int = 1
CONTENT_SOUND: int = 2

PAGE_SIZE: int = 40
CONNECTION_TTL_SECS: int = 60
SESSION_REFRESH_SECS: int = 3600
MAX_RECENT_SEARCHES: int = 10
BOOST_MAX_LEN: int = 16
ZERO_CODE: int = 48
BOT_TOKEN_LEN: int = 12
JOIN_CODE_LEN: int = 12
WEBHOOK_TIMEOUT_SECS: int = 7


# ---------------------------------------------------------------------------
# Entities (zero values are valid: Entity() means "none")
# ---------------------------------------------------------------------------

@dataclass
class User:
    id: int = 0
    name: str = ""
    email: str = ""
    bio: str = ""
    role: int = 0
    status: int = 0
    bot_token: str = ""
    created_at: int = 0


@dataclass
class Room:
    id: int = 0
    name: str = ""
    kind: int = 0
    creator_id: int = 0
    created_at: int = 0


@dataclass
class RoomMembership:
    id: int = 0
    room_id: int = 0
    user_id: int = 0
    involvement: int = 2
    connections: int = 0
    connected_at: int = 0
    unread_at: int = 0
    updated_at: int = 0


@dataclass
class Message:
    id: int = 0
    room_id: int = 0
    creator_id: int = 0
    body: str = ""
    client_message_id: str = ""
    attachment_name: str = ""
    mention_ids: list[int] = field(default_factory=list)
    created_at: int = 0


@dataclass
class Boost:
    id: int = 0
    message_id: int = 0
    booster_id: int = 0
    content: str = ""
    created_at: int = 0


@dataclass
class Ban:
    id: int = 0
    user_id: int = 0
    ip_address: str = ""
    created_at: int = 0


@dataclass
class Session:
    id: int = 0
    user_id: int = 0
    token: str = ""
    ip_address: str = ""
    user_agent: str = ""
    last_active_at: int = 0
    created_at: int = 0


@dataclass
class SearchRecord:
    id: int = 0
    user_id: int = 0
    query: str = ""
    updated_at: int = 0


@dataclass
class PushSubscription:
    id: int = 0
    user_id: int = 0
    endpoint: str = ""
    created_at: int = 0


@dataclass
class Webhook:
    id: int = 0
    user_id: int = 0
    url: str = ""
    created_at: int = 0


@dataclass
class Account:
    id: int = 0
    name: str = ""
    join_code: str = ""
    restrict_rooms_to_admins: bool = False


@dataclass
class SoundEntry:
    name: str = ""
    text: str = ""
    image: str = ""


@dataclass
class Store:
    users: list[User] = field(default_factory=list)
    rooms: list[Room] = field(default_factory=list)
    memberships: list[RoomMembership] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)
    boosts: list[Boost] = field(default_factory=list)
    bans: list[Ban] = field(default_factory=list)
    sessions: list[Session] = field(default_factory=list)
    searches: list[SearchRecord] = field(default_factory=list)
    push_subs: list[PushSubscription] = field(default_factory=list)
    webhooks: list[Webhook] = field(default_factory=list)
    accounts: list[Account] = field(default_factory=list)
    outbox: list[str] = field(default_factory=list)
    next_id: int = 1


# ---------------------------------------------------------------------------
# Result types (returned instead of raising)
# ---------------------------------------------------------------------------

@dataclass
class UserResult:
    ok: bool = False
    value: User = field(default_factory=User)
    error: str = ""


@dataclass
class RoomResult:
    ok: bool = False
    value: Room = field(default_factory=Room)
    error: str = ""


@dataclass
class RoomRoomMembershipResult:
    ok: bool = False
    value: RoomMembership = field(default_factory=RoomMembership)
    error: str = ""


@dataclass
class MessageResult:
    ok: bool = False
    value: Message = field(default_factory=Message)
    error: str = ""


@dataclass
class BoostResult:
    ok: bool = False
    value: Boost = field(default_factory=Boost)
    error: str = ""


@dataclass
class BanResult:
    ok: bool = False
    value: Ban = field(default_factory=Ban)
    error: str = ""


@dataclass
class SessionResult:
    ok: bool = False
    value: Session = field(default_factory=Session)
    error: str = ""


@dataclass
class SearchResult:
    ok: bool = False
    value: SearchRecord = field(default_factory=SearchRecord)
    error: str = ""


@dataclass
class WebhookResult:
    ok: bool = False
    value: Webhook = field(default_factory=Webhook)
    error: str = ""


@dataclass
class SoundResult:
    ok: bool = False
    value: SoundEntry = field(default_factory=SoundEntry)
    error: str = ""


@dataclass
class StrResult:
    ok: bool = False
    value: str = ""
    error: str = ""


@dataclass
class IntResult:
    ok: bool = False
    value: int = 0
    error: str = ""


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------

def alloc_id(store: Store) -> int:
    fresh: int = store.next_id
    store.next_id = store.next_id + 1
    assert fresh > 0
    return fresh


def is_digit_char(ch: str) -> bool:
    return ch >= "0" and ch <= "9"


def is_hex_char(ch: str) -> bool:
    if is_digit_char(ch):
        return True
    if ch >= "a" and ch <= "f":
        return True
    if ch >= "A" and ch <= "F":
        return True
    return False


def is_name_char(ch: str) -> bool:
    if ch >= "a" and ch <= "z":
        return True
    if ch >= "A" and ch <= "Z":
        return True
    if is_digit_char(ch):
        return True
    return ch == "_"


def parse_decimal(text: str) -> IntResult:
    if CHECKER.post:
        not result.ok or result.value >= 0
    if text == "":
        return IntResult(ok=False, value=0, error="not a number")
    total: int = 0
    for ch in text:
        if not is_digit_char(ch):
            return IntResult(ok=False, value=0, error="not a number")
        total = total * 10 + (ord(ch) - ZERO_CODE)
    return IntResult(ok=True, value=total, error="")


def str_len(text: str) -> int:
    count: int = 0
    for _ch in text:
        count += 1
    return count


def has_prefix(text: str, pref: str) -> bool:
    if CHECKER.post:
        result == text.startswith(pref)
    return text.startswith(pref)


def remove_all(body: str, needle: str) -> str:
    if CHECKER.post:
        len(result) <= len(body)
    if needle == "":
        return body
    parts: list[str] = body.split(needle)
    out: str = ""
    for p in parts:
        out += p
    return out


def json_escape(text: str) -> str:
    # Note: backslash escapes are built with chr() because py2many 0.9
    # mangles backslash string literals in its Rust/Go output.
    out: str = ""
    for ch in text:
        if ch == '"':
            out += chr(92)
            out += '"'
        elif ch == chr(92):
            out += chr(92)
            out += chr(92)
        elif ch == chr(10):
            out += chr(92)
            out += "n"
        elif ch == chr(9):
            out += chr(92)
            out += "t"
        elif ch == chr(13):
            out += chr(92)
            out += "r"
        else:
            out += ch
    return out


# ---------------------------------------------------------------------------
# User rules (User::Role, avatar initials, title)
# ---------------------------------------------------------------------------

def can_administer(role: int, self_id: int, creator_id: int, is_new_record: bool) -> bool:
    if CHECKER.post:
        result == (role == ROLE_ADMIN or (self_id == creator_id and self_id != 0) or is_new_record)
    if role == ROLE_ADMIN:
        return True
    elif self_id == creator_id and self_id != 0:
        return True
    elif is_new_record:
        return True
    else:
        return False


def can_create_room(role: int, restrict_to_admins: bool) -> bool:
    if CHECKER.post:
        result == (role == ROLE_ADMIN or not restrict_to_admins)
    if restrict_to_admins and role != ROLE_ADMIN:
        return False
    else:
        return True


def user_initials(name: str) -> str:
    out: str = ""
    words: list[str] = name.split(" ")
    for w in words:
        if w != "":
            for ch in w:
                out += ch
                break
    return out


def user_title(name: str, bio: str) -> str:
    if CHECKER.post:
        (bio == "" and result == name) or (name == "" and result == bio) or (len(result) > len(name) and len(result) > len(bio))
    if bio == "":
        return name
    if name == "":
        return bio
    title: str = name
    title += " - "
    title += bio
    return title


# ---------------------------------------------------------------------------
# Room rules (Room, Rooms::Open/Closed/Direct)
# ---------------------------------------------------------------------------

def default_involvement(kind: int) -> int:
    if CHECKER.post:
        (kind != ROOM_DIRECT and result == INVOLVEMENT_MENTIONS) or (kind == ROOM_DIRECT and result == INVOLVEMENT_EVERYTHING)
    if kind == ROOM_DIRECT:
        return INVOLVEMENT_EVERYTHING
    else:
        return INVOLVEMENT_MENTIONS


def is_valid_room_kind(kind: int) -> bool:
    return kind == ROOM_OPEN or kind == ROOM_CLOSED or kind == ROOM_DIRECT


def direct_type_change_blocked(old_kind: int, new_kind: int) -> bool:
    if CHECKER.post:
        result == (old_kind == ROOM_DIRECT and new_kind != ROOM_DIRECT)
    # A direct room's participants agreed to a private conversation, not to
    # one whose audience someone else widens afterwards.
    if old_kind == ROOM_DIRECT and new_kind != ROOM_DIRECT:
        return True
    else:
        return False


def room_kind_name(kind: int) -> str:
    if kind == ROOM_OPEN:
        return "open"
    elif kind == ROOM_CLOSED:
        return "closed"
    elif kind == ROOM_DIRECT:
        return "direct"
    else:
        return "unknown"


def involvement_name(involvement: int) -> str:
    if involvement == INVOLVEMENT_INVISIBLE:
        return "invisible"
    elif involvement == INVOLVEMENT_NOTHING:
        return "nothing"
    elif involvement == INVOLVEMENT_EVERYTHING:
        return "everything"
    else:
        return "mentions"


def is_visible_membership(involvement: int) -> bool:
    if CHECKER.post:
        result == (involvement != INVOLVEMENT_INVISIBLE)
    return involvement != INVOLVEMENT_INVISIBLE


def same_id_set(a: list[int], b: list[int]) -> bool:
    if CHECKER.post:
        not result or len(a) == len(b)
    if len(a) != len(b):
        return False
    for x in a:
        found: bool = False
        for y in b:
            if x == y:
                found = True
        if not found:
            return False
    return True


# ---------------------------------------------------------------------------
# RoomMembership connection rules (RoomMembership::Connectable)
# ---------------------------------------------------------------------------

def is_connected(connected_at: int, now: int) -> bool:
    if CHECKER.pre:
        now >= 0 and connected_at >= 0
    if CHECKER.post:
        not result or (connected_at != 0 and now - connected_at <= CONNECTION_TTL_SECS)
    if connected_at == 0:
        return False
    else:
        return now - connected_at <= CONNECTION_TTL_SECS


def connect_step(connected_at: int, connections: int, now: int) -> RoomMembership:
    # Models present/connect: record the connection and clear unread.
    assert now > 0
    return RoomMembership(
        room_id=0, user_id=0, involvement=0,
        connections=connections, connected_at=now,
        unread_at=0, updated_at=now,
    )


def increment_connections(connected_at: int, connections: int, now: int) -> RoomMembership:
    if is_connected(connected_at, now):
        return RoomMembership(
            room_id=0, user_id=0, involvement=0,
            connections=connections + 1, connected_at=connected_at,
            unread_at=0, updated_at=now,
        )
    return RoomMembership(
        room_id=0, user_id=0, involvement=0,
        connections=1, connected_at=connected_at,
        unread_at=0, updated_at=now,
    )


def decrement_connections(connected_at: int, connections: int, now: int) -> RoomMembership:
    if is_connected(connected_at, now):
        left: int = connections - 1
        if left < 0:
            left = 0
        if left < 1:
            return RoomMembership(
                room_id=0, user_id=0, involvement=0,
                connections=left, connected_at=0,
                unread_at=0, updated_at=now,
            )
        return RoomMembership(
            room_id=0, user_id=0, involvement=0,
            connections=left, connected_at=connected_at,
            unread_at=0, updated_at=now,
        )
    return RoomMembership(
        room_id=0, user_id=0, involvement=0,
        connections=0, connected_at=0,
        unread_at=0, updated_at=now,
    )


# ---------------------------------------------------------------------------
# Message rules (body, sound commands, content types, mentions)
# ---------------------------------------------------------------------------

def message_plain_body(body: str, attachment_name: str) -> str:
    if CHECKER.post:
        (body != "" and result == body) or (body == "" and result == attachment_name)
    if body != "":
        return body
    else:
        return attachment_name


def sound_command(body: str) -> str:
    if CHECKER.post:
        result == "" or has_prefix(body, "/play ")
    # Matches /\A\/play (?<name>\w+)\z/: exactly "/play <word>".
    if not has_prefix(body, "/play "):
        return ""
    name: str = ""
    rest: list[str] = body.split("/play ")
    first_part: bool = True
    for part in rest:
        if first_part:
            first_part = False
        else:
            if name != "":
                return ""
            name = part
    if name == "":
        return ""
    for ch in name:
        if not is_name_char(ch):
            return ""
    return name


def content_type_of(has_attachment: bool, sound_name: str) -> int:
    if CHECKER.post:
        result >= CONTENT_TEXT and result <= CONTENT_SOUND
    if has_attachment:
        return CONTENT_ATTACHMENT
    elif sound_name != "":
        return CONTENT_SOUND
    else:
        return CONTENT_TEXT


def content_type_name(content_type: int) -> str:
    if content_type == CONTENT_ATTACHMENT:
        return "attachment"
    elif content_type == CONTENT_SOUND:
        return "sound"
    else:
        return "text"


def mention_text(user_name: str) -> str:
    return "@" + user_name


def strip_mention(body: str, user_name: str) -> str:
    cleaned: str = remove_all(body, mention_text(user_name))
    return cleaned.strip()


# ---------------------------------------------------------------------------
# Ban rules (Ban: only public IPs may be banned)
# ---------------------------------------------------------------------------

def parse_ipv4(text: str) -> IntResult:
    if CHECKER.post:
        not result.ok or (result.value >= 0 and result.value <= 4294967295)
    parts: list[str] = text.split(".")
    if len(parts) != 4:
        return IntResult(ok=False, value=0, error="is not a valid IP address")
    total: int = 0
    for part in parts:
        if part == "":
            return IntResult(ok=False, value=0, error="is not a valid IP address")
        if str_len(part) > 3:
            return IntResult(ok=False, value=0, error="is not a valid IP address")
        parsed: IntResult = parse_decimal(part)
        if not parsed.ok:
            return IntResult(ok=False, value=0, error="is not a valid IP address")
        if parsed.value > 255:
            return IntResult(ok=False, value=0, error="is not a valid IP address")
        total = total * 256 + parsed.value
    assert total >= 0
    return IntResult(ok=True, value=total, error="")


def ipv4_is_public(addr: int) -> bool:
    if CHECKER.pre:
        addr >= 0
    first: int = addr // 16777216
    second: int = (addr // 65536) % 256
    if first == 127:
        return False
    if first == 10:
        return False
    if first == 172 and second >= 16 and second <= 31:
        return False
    if first == 192 and second == 168:
        return False
    if first == 169 and second == 254:
        return False
    return True


def ipv6_tail_after_last_colon(text: str) -> str:
    tail: str = ""
    for ch in text:
        if ch == ":":
            tail = ""
        else:
            tail += ch
    return tail


def ipv6_is_well_formed(text: str) -> bool:
    if text == "":
        return False
    has_colon: bool = False
    for ch in text:
        if ch == ":":
            has_colon = True
        elif ch == ".":
            pass
        elif is_hex_char(ch):
            pass
        else:
            return False
    return has_colon


def ipv6_is_public(text: str, lower: str) -> bool:
    if lower == "::1":
        return False
    if has_prefix(lower, "fe8"):
        return False
    if has_prefix(lower, "fe9"):
        return False
    if has_prefix(lower, "fea"):
        return False
    if has_prefix(lower, "feb"):
        return False
    if has_prefix(lower, "fc"):
        return False
    if has_prefix(lower, "fd"):
        return False
    return True


def validate_ban_ip(ip_address: str) -> StrResult:
    if CHECKER.post:
        not result.ok or result.value == ip_address
    assert ip_address != ""
    parsed: IntResult = parse_ipv4(ip_address)
    if parsed.ok:
        if ipv4_is_public(parsed.value):
            return StrResult(ok=True, value=ip_address, error="")
        return StrResult(ok=False, value="", error="cannot be a private or internal IP address")
    has_dot: bool = False
    for ch in ip_address:
        if ch == ".":
            has_dot = True
    if has_dot:
        tail: str = ipv6_tail_after_last_colon(ip_address)
        mapped: IntResult = parse_ipv4(tail)
        if mapped.ok:
            if ipv4_is_public(mapped.value):
                return StrResult(ok=True, value=ip_address, error="")
            return StrResult(ok=False, value="", error="cannot be a private or internal IP address")
        return StrResult(ok=False, value="", error="is not a valid IP address")
    lowered: str = ip_address.lower()
    if not ipv6_is_well_formed(lowered):
        return StrResult(ok=False, value="", error="is not a valid IP address")
    if ipv6_is_public(ip_address, lowered):
        return StrResult(ok=True, value=ip_address, error="")
    return StrResult(ok=False, value="", error="cannot be a private or internal IP address")


# ---------------------------------------------------------------------------
# Bot rules (User::Bot key handling)
# ---------------------------------------------------------------------------

def bot_key_of(user_id: int, token: str) -> str:
    if CHECKER.pre:
        user_id > 0 and token != ""
    if CHECKER.post:
        len(result) > len(token)
    assert user_id > 0
    assert token != ""
    return str(user_id) + "-" + token


def parse_bot_key(key: str) -> IntResult:
    # Splits "id-token" on the first dash; value is the id when the token
    # part is nonempty.
    left: str = ""
    right: str = ""
    seen_dash: bool = False
    for ch in key:
        if ch == "-" and not seen_dash:
            seen_dash = True
        elif not seen_dash:
            left += ch
        else:
            right += ch
    if CHECKER.post:
        not result.ok or result.value > 0
    if not seen_dash:
        return IntResult(ok=False, value=0, error="invalid bot key")
    elif right == "":
        return IntResult(ok=False, value=0, error="invalid bot key")
    else:
        parsed: IntResult = parse_decimal(left)
        if not parsed.ok:
            return IntResult(ok=False, value=0, error="invalid bot key")
        elif parsed.value <= 0:
            return IntResult(ok=False, value=0, error="invalid bot key")
        else:
            return IntResult(ok=True, value=parsed.value, error="")


def bot_key_token(key: str) -> str:
    right: str = ""
    seen_dash: bool = False
    for ch in key:
        if ch == "-" and not seen_dash:
            seen_dash = True
        elif seen_dash:
            right += ch
    return right


def is_valid_bot_token(token: str) -> bool:
    return str_len(token) == BOT_TOKEN_LEN


# ---------------------------------------------------------------------------
# Account rules (Account::Joinable)
# ---------------------------------------------------------------------------

def is_valid_join_token(token: str) -> bool:
    if str_len(token) != JOIN_CODE_LEN:
        return False
    for ch in token:
        ok_ch: bool = False
        if ch >= "a" and ch <= "z":
            ok_ch = True
        if ch >= "A" and ch <= "Z":
            ok_ch = True
        if is_digit_char(ch):
            ok_ch = True
        if not ok_ch:
            return False
    return True


def format_join_code(token: str) -> StrResult:
    if CHECKER.post:
        not result.ok or len(result.value) == 14
    if not is_valid_join_token(token):
        return StrResult(ok=False, value="", error="join token must be 12 alphanumeric characters")
    out: str = ""
    i: int = 0
    for ch in token:
        if i == 4 or i == 8:
            out += "-"
        out += ch
        i += 1
    assert str_len(out) == 14
    return StrResult(ok=True, value=out, error="")


def deactivated_email(email: str, stamp: str) -> str:
    if CHECKER.post:
        (email == "" and result == "") or (email != "" and len(result) >= len(email))
    if email == "":
        return ""
    else:
        assert stamp != ""
        parts: list[str] = email.split("@")
        if len(parts) != 2:
            return email
        else:
            head: str = parts[0]
            tail: str = parts[1]
            masked: str = head
            masked += "-deactivated-"
            masked += stamp
            masked += "@"
            masked += tail
            return masked


# ---------------------------------------------------------------------------
# Session rules
# ---------------------------------------------------------------------------

def session_needs_refresh(last_active_at: int, now: int) -> bool:
    if CHECKER.post:
        result == (now - last_active_at > SESSION_REFRESH_SECS)
    assert now >= last_active_at
    return now - last_active_at > SESSION_REFRESH_SECS


# ---------------------------------------------------------------------------
# Webhook rules (payload building + reply classification; no HTTP)
# ---------------------------------------------------------------------------

def webhook_timeout_text() -> str:
    return "Failed to respond within " + str(WEBHOOK_TIMEOUT_SECS) + " seconds"


def build_webhook_payload(
    bot_user_id: int,
    bot_user_name: str,
    room_id: int,
    room_name: str,
    room_path: str,
    message_id: int,
    message_path: str,
    html_body: str,
    plain_body: str,
) -> str:
    assert bot_user_id > 0
    assert room_id > 0
    assert message_id > 0
    out: str = '{"user":{"id":' + str(bot_user_id)
    out += ',"name":"' + json_escape(bot_user_name) + '"}'
    out += ',"room":{"id":' + str(room_id)
    out += ',"name":"' + json_escape(room_name) + '"'
    out += ',"path":"' + json_escape(room_path) + '"}'
    out += ',"message":{"id":' + str(message_id)
    out += ',"body":{"html":"' + json_escape(html_body) + '"'
    out += ',"plain":"' + json_escape(plain_body) + '"}'
    out += ',"path":"' + json_escape(message_path) + '"}}'
    return out


def webhook_reply_kind(content_type: str) -> str:
    if CHECKER.post:
        result == "text" or result == "attachment" or result == "none"
    if content_type == "text/html":
        return "text"
    if content_type == "text/plain":
        return "text"
    if content_type == "image/png":
        return "attachment"
    if content_type == "image/jpeg":
        return "attachment"
    if content_type == "image/webp":
        return "attachment"
    if content_type == "image/gif":
        return "attachment"
    if content_type == "application/pdf":
        return "attachment"
    return "none"


def webhook_attachment_ext(content_type: str) -> str:
    if content_type == "image/png":
        return "png"
    if content_type == "image/jpeg":
        return "jpg"
    if content_type == "image/webp":
        return "webp"
    if content_type == "image/gif":
        return "gif"
    if content_type == "application/pdf":
        return "pdf"
    return ""


# ---------------------------------------------------------------------------
# Sound catalog (Sound::BUILTIN: name + text or image)
# ---------------------------------------------------------------------------

def builtin_sounds() -> list[SoundEntry]:
    sounds: list[SoundEntry] = []
    sounds.append(SoundEntry(name="56k", text="", image="56k.webp"))
    sounds.append(SoundEntry(name="ballmer", text="developers!", image=""))
    sounds.append(SoundEntry(name="bell", text="bell", image=""))
    sounds.append(SoundEntry(name="bezos", text="laughing", image=""))
    sounds.append(SoundEntry(name="bueller", text="anyone?", image=""))
    sounds.append(SoundEntry(name="butts", text="butts", image=""))
    sounds.append(SoundEntry(name="clowntown", text="", image="clowntown.webp"))
    sounds.append(SoundEntry(name="cottoneyejoe", text="cottoneyejoe", image=""))
    sounds.append(SoundEntry(name="crickets", text="hears crickets chirping", image=""))
    sounds.append(SoundEntry(name="curb", text="", image="curb.webp"))
    sounds.append(SoundEntry(name="dadgummit", text="dad gummit!!", image=""))
    sounds.append(SoundEntry(name="dangerzone", text="", image="dangerzone.webp"))
    sounds.append(SoundEntry(name="danielsan", text="danielsan", image=""))
    sounds.append(SoundEntry(name="deeper", text="", image="top.webp"))
    sounds.append(SoundEntry(name="donotwant", text="", image="donotwant.webp"))
    sounds.append(SoundEntry(name="drama", text="", image="drama.webp"))
    sounds.append(SoundEntry(name="flawless", text="#flawless", image=""))
    sounds.append(SoundEntry(name="glados", text="glados", image=""))
    sounds.append(SoundEntry(name="gogogo", text="Go, go, go!", image=""))
    sounds.append(SoundEntry(name="greatjob", text="", image="greatjob.webp"))
    sounds.append(SoundEntry(name="greyjoy", text="greyjoy", image=""))
    sounds.append(SoundEntry(name="guarantee", text="guarantees it", image=""))
    sounds.append(SoundEntry(name="heygirl", text="heygirl", image=""))
    sounds.append(SoundEntry(name="honk", text="HONK", image=""))
    sounds.append(SoundEntry(name="horn", text="horn", image=""))
    sounds.append(SoundEntry(name="horror", text="horror", image=""))
    sounds.append(SoundEntry(name="inconceivable", text="doesn't think it means what you think it means", image=""))
    sounds.append(SoundEntry(name="letitgo", text="letitgo", image=""))
    sounds.append(SoundEntry(name="live", text="is DOING IT LIVE", image=""))
    sounds.append(SoundEntry(name="loggins", text="", image="loggins.webp"))
    sounds.append(SoundEntry(name="makeitso", text="make it so", image=""))
    sounds.append(SoundEntry(name="noooo", text="noooo", image=""))
    sounds.append(SoundEntry(name="nyan", text="", image="nyan.webp"))
    sounds.append(SoundEntry(name="ohmy", text="raises an eyebrow", image=""))
    sounds.append(SoundEntry(name="ohyeah", text="isn't playing by the rules", image=""))
    sounds.append(SoundEntry(name="pushit", text="", image="pushit.webp"))
    sounds.append(SoundEntry(name="rimshot", text="plays a rimshot", image=""))
    sounds.append(SoundEntry(name="rollout", text="is rolling out", image=""))
    sounds.append(SoundEntry(name="rumble", text="", image="rumble.webp"))
    sounds.append(SoundEntry(name="sax", text="sax", image=""))
    sounds.append(SoundEntry(name="secret", text="found a secret area", image=""))
    sounds.append(SoundEntry(name="sexyback", text="sexyback", image=""))
    sounds.append(SoundEntry(name="story", text="and now you know", image=""))
    sounds.append(SoundEntry(name="tada", text="plays a fanfare", image=""))
    sounds.append(SoundEntry(name="tmyk", text="The More You Know", image=""))
    sounds.append(SoundEntry(name="totes", text="totes", image=""))
    sounds.append(SoundEntry(name="trololo", text="trololo", image=""))
    sounds.append(SoundEntry(name="trombone", text="plays a sad trombone", image=""))
    sounds.append(SoundEntry(name="unix", text="knows this", image=""))
    sounds.append(SoundEntry(name="vuvuzela", text="vuvuzela", image=""))
    sounds.append(SoundEntry(name="what", text="", image="what.webp"))
    sounds.append(SoundEntry(name="whoomp", text="whoomp", image=""))
    sounds.append(SoundEntry(name="wups", text="wups!", image=""))
    sounds.append(SoundEntry(name="yay", text="", image="yay.webp"))
    sounds.append(SoundEntry(name="yeah", text="", image="yeah.webp"))
    sounds.append(SoundEntry(name="yodel", text="yodel", image=""))
    return sounds


def find_sound(sounds: list[SoundEntry], name: str) -> SoundResult:
    if CHECKER.pre:
        name != ""
    if CHECKER.post:
        not result.ok or result.value.name == name
    assert name != ""
    for s in sounds:
        if s.name == name:
            return SoundResult(ok=True, value=s, error="")
    return SoundResult(ok=False, value=SoundEntry(), error="unknown sound")


# ---------------------------------------------------------------------------
# Store lookups (linear scans; index assignment keeps transpiled Go valid)
# ---------------------------------------------------------------------------

def find_user_index(store: Store, user_id: int) -> int:
    i: int = 0
    for u in store.users:
        if u.id == user_id:
            return i
        i += 1
    return -1


def find_room_index(store: Store, room_id: int) -> int:
    i: int = 0
    for r in store.rooms:
        if r.id == room_id:
            return i
        i += 1
    return -1


def find_membership_index(store: Store, room_id: int, user_id: int) -> int:
    i: int = 0
    for m in store.memberships:
        if m.room_id == room_id and m.user_id == user_id:
            return i
        i += 1
    return -1


def find_message_index(store: Store, message_id: int) -> int:
    i: int = 0
    for m in store.messages:
        if m.id == message_id:
            return i
        i += 1
    return -1


def find_session_index(store: Store, session_id: int) -> int:
    i: int = 0
    for s in store.sessions:
        if s.id == session_id:
            return i
        i += 1
    return -1


def find_webhook_index_for_user(store: Store, user_id: int) -> int:
    i: int = 0
    for w in store.webhooks:
        if w.user_id == user_id:
            return i
        i += 1
    return -1


def is_banned_ip(store: Store, ip_address: str) -> bool:
    for b in store.bans:
        if b.ip_address == ip_address:
            return True
    return False


def member_user_ids(store: Store, room_id: int) -> list[int]:
    ids: list[int] = []
    for m in store.memberships:
        if m.room_id == room_id:
            ids.append(m.user_id)
    return ids


def room_messages(store: Store, room_id: int) -> list[Message]:
    out: list[Message] = []
    for m in store.messages:
        if m.room_id == room_id:
            out.append(m)
    return out


def message_is_before(msg: Message, anchor_created: int, anchor_id: int) -> bool:
    if msg.created_at < anchor_created:
        return True
    if msg.created_at == anchor_created and msg.id < anchor_id:
        return True
    return False


def message_is_after(msg: Message, anchor_created: int, anchor_id: int) -> bool:
    if msg.created_at > anchor_created:
        return True
    if msg.created_at == anchor_created and msg.id > anchor_id:
        return True
    return False


def last_page(messages: list[Message]) -> list[Message]:
    if CHECKER.post:
        len(result) <= PAGE_SIZE
    out: list[Message] = []
    start: int = len(messages) - PAGE_SIZE
    if start < 0:
        start = 0
    i: int = start
    while i < len(messages):
        out.append(messages[i])
        i += 1
    return out


def first_page(messages: list[Message]) -> list[Message]:
    if CHECKER.post:
        len(result) <= PAGE_SIZE
    out: list[Message] = []
    i: int = 0
    while i < len(messages) and i < PAGE_SIZE:
        out.append(messages[i])
        i += 1
    return out


def page_before(messages: list[Message], anchor_created: int, anchor_id: int) -> list[Message]:
    older: list[Message] = []
    for m in messages:
        if message_is_before(m, anchor_created, anchor_id):
            older.append(m)
    return last_page(older)


def page_after(messages: list[Message], anchor_created: int, anchor_id: int) -> list[Message]:
    newer: list[Message] = []
    for m in messages:
        if message_is_after(m, anchor_created, anchor_id):
            newer.append(m)
    return first_page(newer)


def page_around(messages: list[Message], anchor: Message) -> list[Message]:
    if CHECKER.post:
        len(result) >= 1
    out: list[Message] = page_before(messages, anchor.created_at, anchor.id)
    out.append(anchor)
    tail: list[Message] = page_after(messages, anchor.created_at, anchor.id)
    for m in tail:
        out.append(m)
    return out


def is_paged(messages: list[Message]) -> bool:
    if CHECKER.post:
        result == (len(messages) > PAGE_SIZE)
    return len(messages) > PAGE_SIZE


# ---------------------------------------------------------------------------
# Store operations: users and rooms
# ---------------------------------------------------------------------------

def create_user(store: Store, name: str, email: str, role: int, now: int, token: str) -> UserResult:
    if CHECKER.post:
        not result.ok or result.value.id > 0
    if name == "":
        return UserResult(ok=False, value=User(), error="name is required")
    if role != ROLE_MEMBER and role != ROLE_ADMIN and role != ROLE_BOT:
        return UserResult(ok=False, value=User(), error="unknown role")
    if email != "":
        for u in store.users:
            if u.email == email:
                return UserResult(ok=False, value=User(), error="email already taken")
    bot_token: str = ""
    if role == ROLE_BOT:
        if not is_valid_bot_token(token):
            return UserResult(ok=False, value=User(), error="bot token must be 12 characters")
        bot_token = token
    user: User = User(
        id=alloc_id(store), name=name, email=email, bio="",
        role=role, status=STATUS_ACTIVE, bot_token=bot_token,
        created_at=now,
    )
    store.users.append(user)
    # New users are automatically granted membership to every open room.
    for r in store.rooms:
        if r.kind == ROOM_OPEN:
            store.memberships.append(RoomMembership(
                id=alloc_id(store), room_id=r.id, user_id=user.id,
                involvement=default_involvement(r.kind), connections=0,
                connected_at=0, unread_at=0, updated_at=now,
            ))
    assert user.id > 0
    return UserResult(ok=True, value=user, error="")


def create_room(store: Store, kind: int, name: str, creator_id: int, member_ids: list[int], now: int) -> RoomResult:
    if CHECKER.post:
        not result.ok or result.value.id > 0
    if not is_valid_room_kind(kind):
        return RoomResult(ok=False, value=Room(), error="unknown room kind")
    if kind != ROOM_DIRECT and name == "":
        return RoomResult(ok=False, value=Room(), error="name is required")
    if find_user_index(store, creator_id) < 0:
        return RoomResult(ok=False, value=Room(), error="creator not found")
    room: Room = Room(id=alloc_id(store), name=name, kind=kind, creator_id=creator_id, created_at=now)
    store.rooms.append(room)
    for uid in member_ids:
        if find_user_index(store, uid) < 0:
            continue
        if find_membership_index(store, room.id, uid) >= 0:
            continue
        store.memberships.append(RoomMembership(
            id=alloc_id(store), room_id=room.id, user_id=uid,
            involvement=default_involvement(kind), connections=0,
            connected_at=0, unread_at=0, updated_at=now,
        ))
    assert room.id > 0
    return RoomResult(ok=True, value=room, error="")


def find_direct_room(store: Store, user_ids: list[int]) -> RoomResult:
    for r in store.rooms:
        if r.kind == ROOM_DIRECT:
            members: list[int] = member_user_ids(store, r.id)
            if same_id_set(members, user_ids):
                return RoomResult(ok=True, value=r, error="")
    return RoomResult(ok=False, value=Room(), error="no direct room for these users")


def find_or_create_direct_room(store: Store, creator_id: int, user_ids: list[int], now: int) -> RoomResult:
    existing: RoomResult = find_direct_room(store, user_ids)
    if existing.ok:
        return existing
    return create_room(store, ROOM_DIRECT, "", creator_id, user_ids, now)


def convert_room_kind(store: Store, room_id: int, new_kind: int, now: int) -> RoomResult:
    if not is_valid_room_kind(new_kind):
        return RoomResult(ok=False, value=Room(), error="unknown room kind")
    idx: int = find_room_index(store, room_id)
    if idx < 0:
        return RoomResult(ok=False, value=Room(), error="room not found")
    old: Room = store.rooms[idx]
    if direct_type_change_blocked(old.kind, new_kind):
        return RoomResult(ok=False, value=Room(), error="can't be changed for a direct room")
    updated: Room = Room(id=old.id, name=old.name, kind=new_kind, creator_id=old.creator_id, created_at=old.created_at)
    store.rooms[idx] = updated
    if new_kind == ROOM_OPEN and old.kind != ROOM_OPEN:
        # Converting to open grants access to every active user.
        for u in store.users:
            if u.status == STATUS_ACTIVE:
                if find_membership_index(store, room_id, u.id) < 0:
                    store.memberships.append(RoomMembership(
                        id=alloc_id(store), room_id=room_id, user_id=u.id,
                        involvement=default_involvement(new_kind), connections=0,
                        connected_at=0, unread_at=0, updated_at=now,
                    ))
    return RoomResult(ok=True, value=updated, error="")


def grant_memberships(store: Store, room_id: int, user_ids: list[int], now: int) -> int:
    if CHECKER.post:
        result >= 0
    idx: int = find_room_index(store, room_id)
    assert idx >= 0
    added: int = 0
    for uid in user_ids:
        if find_user_index(store, uid) < 0:
            continue
        if find_membership_index(store, room_id, uid) >= 0:
            continue
        store.memberships.append(RoomMembership(
            id=alloc_id(store), room_id=room_id, user_id=uid,
            involvement=default_involvement(store.rooms[idx].kind), connections=0,
            connected_at=0, unread_at=0, updated_at=now,
        ))
        added += 1
    assert added >= 0
    return added


def remove_memberships(store: Store, room_id: int, user_ids: list[int]) -> int:
    removed: int = 0
    kept: list[RoomMembership] = []
    for m in store.memberships:
        drop: bool = False
        if m.room_id == room_id:
            for uid in user_ids:
                if m.user_id == uid:
                    drop = True
        if drop:
            removed += 1
        else:
            kept.append(m)
    store.memberships = kept
    assert removed >= 0
    return removed


def revise_memberships(store: Store, room_id: int, granted: list[int], revoked: list[int], now: int) -> int:
    added: int = grant_memberships(store, room_id, granted, now)
    removed: int = remove_memberships(store, room_id, revoked)
    return added + removed


def set_involvement(store: Store, room_id: int, user_id: int, involvement: int, now: int) -> bool:
    if involvement < 0 or involvement > 3:
        return False
    idx: int = find_membership_index(store, room_id, user_id)
    if idx < 0:
        return False
    old: RoomMembership = store.memberships[idx]
    store.memberships[idx] = RoomMembership(
        id=old.id, room_id=old.room_id, user_id=old.user_id,
        involvement=involvement, connections=old.connections,
        connected_at=old.connected_at, unread_at=old.unread_at, updated_at=now,
    )
    return True


def read_membership(store: Store, room_id: int, user_id: int, now: int) -> bool:
    idx: int = find_membership_index(store, room_id, user_id)
    if idx < 0:
        return False
    old: RoomMembership = store.memberships[idx]
    store.memberships[idx] = RoomMembership(
        id=old.id, room_id=old.room_id, user_id=old.user_id,
        involvement=old.involvement, connections=old.connections,
        connected_at=old.connected_at, unread_at=0, updated_at=now,
    )
    return True


def present_membership(store: Store, room_id: int, user_id: int, connections: int, now: int) -> bool:
    assert now > 0
    idx: int = find_membership_index(store, room_id, user_id)
    if idx < 0:
        return False
    old: RoomMembership = store.memberships[idx]
    store.memberships[idx] = RoomMembership(
        id=old.id, room_id=old.room_id, user_id=old.user_id,
        involvement=old.involvement, connections=connections,
        connected_at=now, unread_at=0, updated_at=now,
    )
    return True


def disconnect_membership(store: Store, room_id: int, user_id: int, now: int) -> bool:
    idx: int = find_membership_index(store, room_id, user_id)
    if idx < 0:
        return False
    old: RoomMembership = store.memberships[idx]
    step: RoomMembership = decrement_connections(old.connected_at, old.connections, now)
    store.memberships[idx] = RoomMembership(
        id=old.id, room_id=old.room_id, user_id=old.user_id,
        involvement=old.involvement, connections=step.connections,
        connected_at=step.connected_at, unread_at=old.unread_at, updated_at=now,
    )
    return True


def disconnect_all(store: Store, now: int) -> int:
    count: int = 0
    i: int = 0
    while i < len(store.memberships):
        old: RoomMembership = store.memberships[i]
        if old.connected_at != 0:
            store.memberships[i] = RoomMembership(
                id=old.id, room_id=old.room_id, user_id=old.user_id,
                involvement=old.involvement, connections=0,
                connected_at=0, unread_at=old.unread_at, updated_at=now,
            )
            count += 1
        i += 1
    assert count >= 0
    return count


def mark_room_unread(store: Store, room_id: int, creator_id: int, created_at: int, now: int) -> int:
    if CHECKER.post:
        result >= 0
    assert created_at > 0
    marked: int = 0
    i: int = 0
    while i < len(store.memberships):
        old: RoomMembership = store.memberships[i]
        if old.room_id == room_id:
            if old.user_id != creator_id:
                if is_visible_membership(old.involvement):
                    if not is_connected(old.connected_at, now):
                        store.memberships[i] = RoomMembership(
                            id=old.id, room_id=old.room_id, user_id=old.user_id,
                            involvement=old.involvement, connections=old.connections,
                            connected_at=old.connected_at, unread_at=created_at, updated_at=now,
                        )
                        marked += 1
        i += 1
    assert marked >= 0
    return marked


def eligible_webhook_bots(store: Store, room_id: int, message: Message) -> list[int]:
    bots: list[int] = []
    ridx: int = find_room_index(store, room_id)
    assert ridx >= 0
    if store.rooms[ridx].kind == ROOM_DIRECT:
        for uid in member_user_ids(store, room_id):
            uidx: int = find_user_index(store, uid)
            if uidx >= 0:
                if store.users[uidx].role == ROLE_BOT:
                    if store.users[uidx].status == STATUS_ACTIVE:
                        if uid != message.creator_id:
                            bots.append(uid)
    else:
        for mid in message.mention_ids:
            uidx2: int = find_user_index(store, mid)
            if uidx2 >= 0:
                if store.users[uidx2].role == ROLE_BOT:
                    if store.users[uidx2].status == STATUS_ACTIVE:
                        if mid != message.creator_id:
                            bots.append(mid)
    return bots


def post_message(store: Store, room_id: int, creator_id: int, body: str, attachment_name: str, mention_ids: list[int], client_message_id: str, now: int) -> MessageResult:
    assert now > 0
    if find_room_index(store, room_id) < 0:
        return MessageResult(ok=False, value=Message(), error="room not found")
    if find_user_index(store, creator_id) < 0:
        return MessageResult(ok=False, value=Message(), error="creator not found")
    if find_membership_index(store, room_id, creator_id) < 0:
        return MessageResult(ok=False, value=Message(), error="creator is not a room member")
    if body == "" and attachment_name == "":
        return MessageResult(ok=False, value=Message(), error="body or attachment is required")
    kept_mentions: list[int] = []
    for mid in mention_ids:
        if find_membership_index(store, room_id, mid) >= 0:
            dup: bool = False
            for k in kept_mentions:
                if k == mid:
                    dup = True
            if not dup:
                kept_mentions.append(mid)
    msg_id: int = alloc_id(store)
    cid: str = client_message_id
    if cid == "":
        cid = "client-" + str(msg_id)
    message: Message = Message(
        id=msg_id, room_id=room_id, creator_id=creator_id, body=body,
        client_message_id=cid, attachment_name=attachment_name,
        mention_ids=kept_mentions, created_at=now,
    )
    if CHECKER.post:
        not result.ok or result.value.id > 0
    store.messages.append(message)
    mark_room_unread(store, room_id, creator_id, now, now)
    store.outbox.append("push:" + str(room_id) + ":" + str(msg_id))
    for bot_id in eligible_webhook_bots(store, room_id, message):
        if find_webhook_index_for_user(store, bot_id) >= 0:
            store.outbox.append("webhook:" + str(bot_id) + ":" + str(msg_id))
    assert message.id > 0
    return MessageResult(ok=True, value=message, error="")


def message_mentionees(store: Store, message: Message) -> list[int]:
    out: list[int] = []
    for mid in message.mention_ids:
        if find_membership_index(store, message.room_id, mid) >= 0:
            out.append(mid)
    return out


def boost_message(store: Store, message_id: int, booster_id: int, content: str, now: int) -> BoostResult:
    assert now > 0
    if find_message_index(store, message_id) < 0:
        return BoostResult(ok=False, value=Boost(), error="message not found")
    if find_user_index(store, booster_id) < 0:
        return BoostResult(ok=False, value=Boost(), error="booster not found")
    if content == "":
        return BoostResult(ok=False, value=Boost(), error="boost content is required")
    if str_len(content) > BOOST_MAX_LEN:
        return BoostResult(ok=False, value=Boost(), error="boost content is too long")
    boost: Boost = Boost(
        id=alloc_id(store), message_id=message_id, booster_id=booster_id,
        content=content, created_at=now,
    )
    if CHECKER.post:
        not result.ok or result.value.id > 0
    store.boosts.append(boost)
    return BoostResult(ok=True, value=boost, error="")


def start_session(store: Store, user_id: int, token: str, ip_address: str, user_agent: str, now: int) -> SessionResult:
    assert now > 0
    if find_user_index(store, user_id) < 0:
        return SessionResult(ok=False, value=Session(), error="user not found")
    if token == "":
        return SessionResult(ok=False, value=Session(), error="token is required")
    if CHECKER.post:
        not result.ok or result.value.id > 0
    session: Session = Session(
        id=alloc_id(store), user_id=user_id, token=token,
        ip_address=ip_address, user_agent=user_agent,
        last_active_at=now, created_at=now,
    )
    store.sessions.append(session)
    return SessionResult(ok=True, value=session, error="")


def touch_session(store: Store, session_id: int, user_agent: str, ip_address: str, now: int) -> bool:
    idx: int = find_session_index(store, session_id)
    if idx < 0:
        return False
    old: Session = store.sessions[idx]
    assert now >= old.last_active_at
    if session_needs_refresh(old.last_active_at, now):
        store.sessions[idx] = Session(
            id=old.id, user_id=old.user_id, token=old.token,
            ip_address=ip_address, user_agent=user_agent,
            last_active_at=now, created_at=old.created_at,
        )
        return True
    return False


def find_search_index(store: Store, search_id: int) -> int:
    i: int = 0
    for s in store.searches:
        if s.id == search_id:
            return i
        i += 1
    return -1


def trim_searches(store: Store, user_id: int) -> int:
    removed: int = 0
    while True:
        count: int = 0
        oldest_idx: int = -1
        oldest_time: int = 0
        first_seen: bool = True
        i: int = 0
        for s in store.searches:
            if s.user_id == user_id:
                count += 1
                if first_seen:
                    oldest_time = s.updated_at
                    oldest_idx = i
                    first_seen = False
                elif s.updated_at < oldest_time:
                    oldest_time = s.updated_at
                    oldest_idx = i
            i += 1
        if count <= MAX_RECENT_SEARCHES:
            break
        if oldest_idx < 0:
            break
        kept: list[SearchRecord] = []
        j: int = 0
        for s in store.searches:
            if j != oldest_idx:
                kept.append(s)
            j += 1
        store.searches = kept
        removed += 1
    assert removed >= 0
    return removed

def record_search(store: Store, user_id: int, query: str, now: int) -> SearchResult:
    assert now > 0
    if query == "":
        return SearchResult(ok=False, value=SearchRecord(), error="query is required")
    if find_user_index(store, user_id) < 0:
        return SearchResult(ok=False, value=SearchRecord(), error="user not found")
    for s in store.searches:
        if s.user_id == user_id and s.query == query:
            idx: int = find_search_index(store, s.id)
            store.searches[idx] = SearchRecord(id=s.id, user_id=s.user_id, query=s.query, updated_at=now)
            return SearchResult(ok=True, value=store.searches[idx], error="")
    if CHECKER.post:
        not result.ok or result.value.query == query
    # Constructed twice (once to store, once to return) so the returned
    # literal is visible to the verifier; both share one allocated id.
    new_id: int = alloc_id(store)
    store.searches.append(SearchRecord(id=new_id, user_id=user_id, query=query, updated_at=now))
    trim_searches(store, user_id)
    return SearchResult(ok=True, value=SearchRecord(id=new_id, user_id=user_id, query=query, updated_at=now), error="")



def set_bot_webhook(store: Store, user_id: int, url: str, now: int) -> WebhookResult:
    assert now > 0
    if find_user_index(store, user_id) < 0:
        return WebhookResult(ok=False, value=Webhook(), error="user not found")
    idx: int = find_webhook_index_for_user(store, user_id)
    if url == "":
        if idx >= 0:
            kept: list[Webhook] = []
            j: int = 0
            for w in store.webhooks:
                if j != idx:
                    kept.append(w)
                j += 1
            store.webhooks = kept
        return WebhookResult(ok=True, value=Webhook(), error="")
    if idx >= 0:
        old: Webhook = store.webhooks[idx]
        store.webhooks[idx] = Webhook(id=old.id, user_id=user_id, url=url, created_at=old.created_at)
        return WebhookResult(ok=True, value=store.webhooks[idx], error="")
    hook: Webhook = Webhook(id=alloc_id(store), user_id=user_id, url=url, created_at=now)
    store.webhooks.append(hook)
    return WebhookResult(ok=True, value=hook, error="")


def apply_webhook_reply(store: Store, room_id: int, bot_user_id: int, content_type: str, body: str, now: int, client_id: str) -> MessageResult:
    kind: str = webhook_reply_kind(content_type)
    if CHECKER.post:
        not result.ok or result.value.creator_id == bot_user_id
    no_mentions: list[int] = []
    if kind == "text":
        if body == "":
            return MessageResult(ok=False, value=Message(), error="empty webhook reply")
        return post_message(store, room_id, bot_user_id, body, "", no_mentions, client_id, now)
    if kind == "attachment":
        ext: str = webhook_attachment_ext(content_type)
        return post_message(store, room_id, bot_user_id, "", "attachment." + ext, no_mentions, client_id, now)
    return MessageResult(ok=False, value=Message(), error="unsupported webhook reply")


def create_bot(store: Store, name: str, token: str, webhook_url: str, now: int) -> UserResult:
    created: UserResult = create_user(store, name, "", ROLE_BOT, now, token)
    if not created.ok:
        return created
    if webhook_url != "":
        set_bot_webhook(store, created.value.id, webhook_url, now)
    return created


def authenticate_bot(store: Store, key: str) -> UserResult:
    if CHECKER.post:
        not result.ok or result.value.role == ROLE_BOT
    parsed: IntResult = parse_bot_key(key)
    if not parsed.ok:
        return UserResult(ok=False, value=User(), error=parsed.error)
    token: str = bot_key_token(key)
    for u in store.users:
        if u.id == parsed.value:
            if u.role == ROLE_BOT and u.status == STATUS_ACTIVE and u.bot_token == token:
                return UserResult(ok=True, value=u, error="")
            return UserResult(ok=False, value=User(), error="invalid bot credentials")
    return UserResult(ok=False, value=User(), error="bot not found")


def reset_bot_token(store: Store, user_id: int, new_token: str) -> UserResult:
    if not is_valid_bot_token(new_token):
        return UserResult(ok=False, value=User(), error="bot token must be 12 characters")
    idx: int = find_user_index(store, user_id)
    if idx < 0:
        return UserResult(ok=False, value=User(), error="user not found")
    old: User = store.users[idx]
    if old.role != ROLE_BOT:
        return UserResult(ok=False, value=User(), error="not a bot")
    store.users[idx] = User(
        id=old.id, name=old.name, email=old.email, bio=old.bio,
        role=old.role, status=old.status, bot_token=new_token,
        created_at=old.created_at,
    )
    return UserResult(ok=True, value=store.users[idx], error="")


def create_ban(store: Store, user_id: int, ip_address: str, now: int) -> BanResult:
    assert now > 0
    if find_user_index(store, user_id) < 0:
        return BanResult(ok=False, value=Ban(), error="user not found")
    checked: StrResult = validate_ban_ip(ip_address)
    if not checked.ok:
        return BanResult(ok=False, value=Ban(), error=checked.error)
    if CHECKER.post:
        not result.ok or result.value.ip_address == ip_address
    # Constructed twice (once to store, once to return) so the returned
    # literal is visible to the verifier; both share one allocated id.
    new_id: int = alloc_id(store)
    store.bans.append(Ban(id=new_id, user_id=user_id, ip_address=ip_address, created_at=now))
    return BanResult(ok=True, value=Ban(id=new_id, user_id=user_id, ip_address=ip_address, created_at=now), error="")


def ban_user(store: Store, user_id: int, now: int) -> IntResult:
    assert now > 0
    uidx: int = find_user_index(store, user_id)
    if uidx < 0:
        return IntResult(ok=False, value=0, error="user not found")
    seen: list[str] = []
    for s in store.sessions:
        if s.user_id == user_id and s.ip_address != "":
            dup: bool = False
            for ip in seen:
                if ip == s.ip_address:
                    dup = True
            if not dup:
                seen.append(s.ip_address)
    if CHECKER.post:
        not result.ok or result.value >= 0
    count: int = 0
    for ip in seen:
        res: BanResult = create_ban(store, user_id, ip, now)
        if res.ok:
            count += 1
    kept_sessions: list[Session] = []
    for s in store.sessions:
        if s.user_id != user_id:
            kept_sessions.append(s)
    store.sessions = kept_sessions
    old: User = store.users[uidx]
    store.users[uidx] = User(
        id=old.id, name=old.name, email=old.email, bio=old.bio,
        role=old.role, status=STATUS_BANNED, bot_token=old.bot_token,
        created_at=old.created_at,
    )
    for m in store.messages:
        if m.creator_id == user_id:
            store.outbox.append("remove:" + str(m.id))
    kept_msgs: list[Message] = []
    for m in store.messages:
        if m.creator_id != user_id:
            kept_msgs.append(m)
    store.messages = kept_msgs
    assert count >= 0
    return IntResult(ok=True, value=count, error="")


def unban_user(store: Store, user_id: int, now: int) -> UserResult:
    assert now > 0
    uidx: int = find_user_index(store, user_id)
    if uidx < 0:
        return UserResult(ok=False, value=User(), error="user not found")
    kept: list[Ban] = []
    for b in store.bans:
        if b.user_id != user_id:
            kept.append(b)
    store.bans = kept
    old: User = store.users[uidx]
    store.users[uidx] = User(
        id=old.id, name=old.name, email=old.email, bio=old.bio,
        role=old.role, status=STATUS_ACTIVE, bot_token=old.bot_token,
        created_at=old.created_at,
    )
    return UserResult(ok=True, value=store.users[uidx], error="")


def deactivate_user(store: Store, user_id: int, stamp: str, now: int) -> StrResult:
    assert now > 0
    uidx: int = find_user_index(store, user_id)
    if uidx < 0:
        return StrResult(ok=False, value="", error="user not found")
    i: int = 0
    while i < len(store.memberships):
        m: RoomMembership = store.memberships[i]
        if m.user_id == user_id:
            store.memberships[i] = RoomMembership(
                id=m.id, room_id=m.room_id, user_id=m.user_id,
                involvement=m.involvement, connections=0,
                connected_at=0, unread_at=m.unread_at, updated_at=now,
            )
        i += 1
    kept_m: list[RoomMembership] = []
    for m in store.memberships:
        drop: bool = False
        if m.user_id == user_id:
            ridx: int = find_room_index(store, m.room_id)
            drop = ridx < 0 or store.rooms[ridx].kind != ROOM_DIRECT
        if not drop:
            kept_m.append(m)
    store.memberships = kept_m
    kept_p: list[PushSubscription] = []
    for p in store.push_subs:
        if p.user_id != user_id:
            kept_p.append(p)
    store.push_subs = kept_p
    kept_q: list[SearchRecord] = []
    for q in store.searches:
        if q.user_id != user_id:
            kept_q.append(q)
    store.searches = kept_q
    kept_s: list[Session] = []
    for s in store.sessions:
        if s.user_id != user_id:
            kept_s.append(s)
    store.sessions = kept_s
    old: User = store.users[uidx]
    new_email: str = deactivated_email(old.email, stamp)
    store.users[uidx] = User(
        id=old.id, name=old.name, email=new_email, bio=old.bio,
        role=old.role, status=STATUS_DEACTIVATED, bot_token=old.bot_token,
        created_at=old.created_at,
    )
    return StrResult(ok=True, value=new_email, error="")


def create_account(store: Store, name: str, join_token: str, now: int) -> StrResult:
    assert now > 0
    if name == "":
        return StrResult(ok=False, value="", error="name is required")
    code: StrResult = format_join_code(join_token)
    if not code.ok:
        return code
    if CHECKER.post:
        not result.ok or len(result.value) == 14
    account: Account = Account(id=alloc_id(store), name=name, join_code=code.value, restrict_rooms_to_admins=False)
    store.accounts.append(account)
    return StrResult(ok=True, value=code.value, error="")


def reset_account_join_code(store: Store, account_id: int, join_token: str, now: int) -> StrResult:
    assert now > 0
    code: StrResult = format_join_code(join_token)
    if not code.ok:
        return code
    i: int = 0
    for a in store.accounts:
        if a.id == account_id:
            store.accounts[i] = Account(id=a.id, name=a.name, join_code=code.value, restrict_rooms_to_admins=a.restrict_rooms_to_admins)
            return StrResult(ok=True, value=code.value, error="")
        i += 1
    return StrResult(ok=False, value="", error="account not found")