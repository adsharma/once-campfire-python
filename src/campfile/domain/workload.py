"""Benchmark workload over the campfire domain (static-python style).

Implements the five hot paths from ../once-campfire/bench (room page,
messages page, sidebar, search, post a message) as pure functions over
campfire.Store, plus a deterministic seeder and an inverted search index
with Porter stemming (mirroring the Rails FTS5 porter tokenizer).

Like campfire.py this avoids pattern matching, exceptions, slicing,
regex and IO so it can be merged into the transpilable core later. It
imports campfire.py, so today it runs under Python (Flask); the single
transpilable unit remains campfire.py.
"""

from dataclasses import dataclass, field

from . import campfire as c


# ---------------------------------------------------------------------------
# Deterministic RNG (LCG; same stream in every language)
# ---------------------------------------------------------------------------

@dataclass
class Rng:
    state: int = 0


RNG_A: int = 1103515245
RNG_C: int = 12345
RNG_M: int = 2147483648


def rng_next(rng: Rng, modulus: int) -> int:
    assert modulus > 0
    rng.state = (RNG_A * rng.state + RNG_C) % RNG_M
    return rng.state % modulus


# ---------------------------------------------------------------------------
# Porter stemmer (static-python subset: index loops, no slicing, no regex)
# ---------------------------------------------------------------------------

def is_vowel_char(ch: str) -> bool:
    if ch == "a" or ch == "e" or ch == "i" or ch == "o" or ch == "u":
        return True
    return False


def is_consonant_at(word: str, i: int, n: int) -> bool:
    assert n >= 0
    ch: str = ""
    k: int = 0
    for c in word:
        if k == i:
            ch = c
        k += 1
    if is_vowel_char(ch):
        return False
    if ch == "y":
        if i == 0:
            return True
        return not is_consonant_at(word, i - 1, n)
    return True


def word_len(word: str) -> int:
    n: int = 0
    for _c in word:
        n += 1
    return n


def char_at(word: str, i: int) -> str:
    k: int = 0
    for ch in word:
        if k == i:
            return ch
        k += 1
    return ""


def starts_at(word: str, pos: int, suffix: str) -> bool:
    k: int = 0
    for ch in suffix:
        if char_at(word, pos + k) != ch:
            return False
        k += 1
    return True


def ends_with(word: str, n: int, suffix: str) -> bool:
    m: int = word_len(suffix)
    if m > n:
        return False
    return starts_at(word, n - m, suffix)


def head_upto(word: str, n: int) -> str:
    out: str = ""
    k: int = 0
    for ch in word:
        if k < n:
            out += ch
        k += 1
    return out


def measure(word: str, n: int) -> int:
    m: int = 0
    i: int = 0
    while i < n:
        while i < n and is_consonant_at(word, i, n):
            i += 1
        if i >= n:
            break
        while i < n and not is_consonant_at(word, i, n):
            i += 1
        if i < n:
            m += 1
    assert m >= 0
    return m


def has_vowel(word: str, n: int) -> bool:
    i: int = 0
    while i < n:
        if not is_consonant_at(word, i, n):
            return True
        i += 1
    return False


def ends_double_consonant(word: str, n: int) -> bool:
    if n < 2:
        return False
    if char_at(word, n - 1) != char_at(word, n - 2):
        return False
    return is_consonant_at(word, n - 1, n)


def ends_cvc(word: str, n: int) -> bool:
    if n < 3:
        return False
    if not is_consonant_at(word, n - 3, n):
        return False
    if is_consonant_at(word, n - 2, n):
        return False
    if not is_consonant_at(word, n - 1, n):
        return False
    last: str = char_at(word, n - 1)
    if last == "w" or last == "x" or last == "y":
        return False
    return True


def step_1a(word: str) -> str:
    n: int = word_len(word)
    if ends_with(word, n, "sses"):
        return head_upto(word, n - 2)
    if ends_with(word, n, "ies"):
        return head_upto(word, n - 2)
    if ends_with(word, n, "ss"):
        return word
    if ends_with(word, n, "s"):
        return head_upto(word, n - 1)
    return word


def step_1b_helper(word: str) -> str:
    n: int = word_len(word)
    if ends_with(word, n, "at") or ends_with(word, n, "bl") or ends_with(word, n, "iz"):
        return word + "e"
    if ends_double_consonant(word, n):
        last: str = char_at(word, n - 1)
        if last == "l" or last == "s" or last == "z":
            return word
        return head_upto(word, n - 1)
    if measure(word, n) == 1 and ends_cvc(word, n):
        return word + "e"
    return word


def step_1b(word: str) -> str:
    n: int = word_len(word)
    if ends_with(word, n, "eed"):
        stem: str = head_upto(word, n - 3)
        if measure(stem, word_len(stem)) > 0:
            return head_upto(word, n - 1)
        return word
    if ends_with(word, n, "ed"):
        stem2: str = head_upto(word, n - 2)
        if has_vowel(stem2, word_len(stem2)):
            return step_1b_helper(stem2)
        return word
    if ends_with(word, n, "ing"):
        stem3: str = head_upto(word, n - 3)
        if has_vowel(stem3, word_len(stem3)):
            return step_1b_helper(stem3)
        return word
    return word


def step_1c(word: str) -> str:
    n: int = word_len(word)
    if ends_with(word, n, "y"):
        stem: str = head_upto(word, n - 1)
        if has_vowel(stem, word_len(stem)):
            return stem + "i"
    return word


def step_2(word: str) -> str:
    n: int = word_len(word)
    pairs: list[str] = [
        "ational", "ate", "tional", "tion", "enci", "ence", "anci", "ance",
        "izer", "ize", "bli", "ble", "alli", "al", "entli", "ent",
        "eli", "e", "ousli", "ous", "ization", "ize", "ation", "ate",
        "ator", "ate", "alism", "al", "iveness", "ive", "fulness", "ful",
        "ousness", "ous", "aliti", "al", "iviti", "ive", "biliti", "ble",
        "logi", "log",
    ]
    k: int = 0
    while k < len(pairs):
        sfx: str = pairs[k]
        rep: str = pairs[k + 1]
        if ends_with(word, n, sfx):
            stem: str = head_upto(word, n - word_len(sfx))
            if measure(stem, word_len(stem)) > 0:
                return stem + rep
            return word
        k += 2
    return word


def step_3(word: str) -> str:
    n: int = word_len(word)
    pairs: list[str] = [
        "icate", "ic", "ative", "", "alize", "al",
        "iciti", "ic", "ical", "ic", "ful", "", "ness", "",
    ]
    k: int = 0
    while k < len(pairs):
        sfx: str = pairs[k]
        rep: str = pairs[k + 1]
        if ends_with(word, n, sfx):
            stem: str = head_upto(word, n - word_len(sfx))
            if measure(stem, word_len(stem)) > 0:
                return stem + rep
            return word
        k += 2
    return word


def step_4(word: str) -> str:
    n: int = word_len(word)
    suffixes: list[str] = [
        "al", "ance", "ence", "er", "ic", "able", "ible", "ant",
        "ement", "ment", "ent", "ou", "ism", "ate", "iti", "ous",
        "ive", "ize",
    ]
    for sfx in suffixes:
        if ends_with(word, n, sfx):
            stem: str = head_upto(word, n - word_len(sfx))
            if measure(stem, word_len(stem)) > 1:
                return stem
            return word
    if ends_with(word, n, "sion") or ends_with(word, n, "tion"):
        stem2: str = head_upto(word, n - 3)
        if measure(stem2, word_len(stem2)) > 1:
            return stem2
        return word
    return word


def step_5(word: str) -> str:
    n: int = word_len(word)
    if ends_with(word, n, "e"):
        stem: str = head_upto(word, n - 1)
        m: int = measure(stem, word_len(stem))
        if m > 1:
            return stem
        if m == 1 and not ends_cvc(stem, word_len(stem)):
            return stem
    if ends_with(word, n, "ll"):
        stem2: str = head_upto(word, n - 1)
        if measure(stem2, word_len(stem2)) > 1:
            return stem2
    return word


def porter_stem(raw: str) -> str:
    if word_len(raw) <= 2:
        return raw
    w: str = step_1a(raw)
    w = step_1b(w)
    w = step_1c(w)
    w = step_2(w)
    w = step_3(w)
    w = step_4(w)
    w = step_5(w)
    return w


# ---------------------------------------------------------------------------
# Tokenizer + inverted index
# ---------------------------------------------------------------------------

def is_token_char(ch: str) -> bool:
    if ch >= "a" and ch <= "z":
        return True
    if ch >= "A" and ch <= "Z":
        return True
    if ch >= "0" and ch <= "9":
        return True
    return False


def lower_char(ch: str) -> str:
    if ch >= "A" and ch <= "Z":
        out: str = ""
        for plain in "abcdefghijklmnopqrstuvwxyz":
            out += plain
        idx: int = 0
        for upper in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            if upper == ch:
                return char_at(out, idx)
            idx += 1
    return ch


def tokenize(text: str) -> list[str]:
    toks: list[str] = []
    cur: str = ""
    for ch in text:
        if is_token_char(ch):
            cur += lower_char(ch)
        else:
            if cur != "":
                toks.append(cur)
                cur = ""
    if cur != "":
        toks.append(cur)
    return toks


def stem_tokens(toks: list[str]) -> list[str]:
    out: list[str] = []
    for t in toks:
        out.append(porter_stem(t))
    return out


@dataclass
class SearchIndex:
    postings: dict = field(default_factory=dict)
    doc_room: dict = field(default_factory=dict)
    doc_count: int = 0


def index_add(index: SearchIndex, term: str, msg_id: int) -> None:
    # Postings are flat [id, count, id, count, ...] pairs in increasing id
    # order (messages are indexed in id order), so intersections merge in
    # one linear pass instead of rescanning per candidate.
    if term in index.postings:
        pairs: list = index.postings[term]
        if len(pairs) >= 2 and pairs[len(pairs) - 2] == msg_id:
            pairs[len(pairs) - 1] = pairs[len(pairs) - 1] + 1
        else:
            pairs.append(msg_id)
            pairs.append(1)
    else:
        index.postings[term] = [msg_id, 1]


def build_search_index(store: c.Store) -> SearchIndex:
    index: SearchIndex = SearchIndex()
    for m in store.messages:
        toks: list[str] = stem_tokens(tokenize(m.body))
        for t in toks:
            index_add(index, t, m.id)
        index.doc_room[m.id] = m.room_id
    index.doc_count = len(store.messages)
    return index


def index_message(index: SearchIndex, room_id: int, msg_id: int, body: str) -> int:
    assert room_id > 0
    assert msg_id > 0
    added: int = 0
    for t in stem_tokens(tokenize(body)):
        index_add(index, t, msg_id)
        added += 1
    index.doc_room[msg_id] = room_id
    index.doc_count += 1
    assert added >= 0
    return added


def postings_for(index: SearchIndex, term: str) -> list[int]:
    if term in index.postings:
        return index.postings[term]
    empty: list[int] = []
    return empty


def pair_id(pairs: list[int], pos: int) -> int:
    return pairs[pos * 2]


def pair_count(pairs: list[int], pos: int) -> int:
    return pairs[pos * 2 + 1]


def pair_len(pairs: list[int]) -> int:
    n: int = 0
    i: int = 0
    while i < len(pairs):
        n += 1
        i += 2
    return n


def search_messages(
    store: c.Store, index: SearchIndex, user_id: int, query: str, limit: int
) -> list[int]:
    assert limit > 0
    terms: list[str] = stem_tokens(tokenize(query))
    if len(terms) == 0:
        return []
    rooms: list[int] = []
    for m in store.memberships:
        if m.user_id == user_id and m.involvement != c.INVOLVEMENT_INVISIBLE:
            rooms.append(m.room_id)
    lists: list[list[int]] = []
    for t in terms:
        hits: list[int] = postings_for(index, t)
        if pair_len(hits) == 0:
            return []
        lists.append(hits)
    pos: list[int] = []
    lens: list[int] = []
    for _l in lists:
        pos.append(0)
        lens.append(pair_len(_l))
    scored_ids: list[int] = []
    scored_vals: list[int] = []
    while True:
        done: bool = False
        top: int = 0
        li: int = 0
        while li < len(lists):
            if pos[li] >= lens[li]:
                done = True
            elif pair_id(lists[li], pos[li]) > top:
                top = pair_id(lists[li], pos[li])
            li += 1
        if done:
            break
        aligned: bool = True
        score: int = 0
        li2: int = 0
        while li2 < len(lists):
            if pair_id(lists[li2], pos[li2]) < top:
                aligned = False
                pos[li2] = pos[li2] + 1
            else:
                score += pair_count(lists[li2], pos[li2])
            li2 += 1
        if aligned:
            if top in index.doc_room:
                rid: int = index.doc_room[top]
                in_room: bool = False
                for r in rooms:
                    if r == rid:
                        in_room = True
                if in_room:
                    scored_ids.append(top)
                    scored_vals.append(score)
            li3: int = 0
            while li3 < len(lists):
                pos[li3] = pos[li3] + 1
                li3 += 1
    out: list[int] = []
    while len(out) < limit and len(scored_ids) > 0:
        best: int = 0
        bi: int = 1
        while bi < len(scored_ids):
            if scored_vals[bi] > scored_vals[best]:
                best = bi
            bi += 1
        out.append(scored_ids[best])
        kept_ids: list[int] = []
        kept_vals: list[int] = []
        i: int = 0
        while i < len(scored_ids):
            if i != best:
                kept_ids.append(scored_ids[i])
                kept_vals.append(scored_vals[i])
            i += 1
        scored_ids = kept_ids
        scored_vals = kept_vals
    return out


# ---------------------------------------------------------------------------
# Presentation views (dataclasses; Flask renders them with asdict)
# ---------------------------------------------------------------------------

@dataclass
class MessageView:
    id: int = 0
    body: str = ""
    creator_id: int = 0
    creator_name: str = ""
    created_at: int = 0
    client_message_id: str = ""
    attachment_name: str = ""
    content_type: str = "text"
    boosts: list[str] = field(default_factory=list)
    mentions: list[str] = field(default_factory=list)


@dataclass
class RoomPageView:
    room_id: int = 0
    room_name: str = ""
    room_kind: int = 0
    messages: list[MessageView] = field(default_factory=list)
    has_more: bool = False


@dataclass
class SidebarEntry:
    room_id: int = 0
    room_name: str = ""
    room_kind: int = 0
    unread: bool = False
    involvement: int = 2


@dataclass
class SearchHitView:
    message: MessageView = field(default_factory=MessageView)
    room_name: str = ""


@dataclass
class RoomPageResult:
    ok: bool = False
    value: RoomPageView = field(default_factory=RoomPageView)
    error: str = ""


@dataclass
class MessagesPageResult:
    ok: bool = False
    value: list[MessageView] = field(default_factory=list)
    error: str = ""


@dataclass
class SidebarResult:
    ok: bool = False
    value: list[SidebarEntry] = field(default_factory=list)
    error: str = ""


@dataclass
class SearchPageResult:
    ok: bool = False
    value: list[SearchHitView] = field(default_factory=list)
    error: str = ""


def user_name_of(store: c.Store, user_id: int) -> str:
    idx: int = c.find_user_index(store, user_id)
    if idx < 0:
        return ""
    return store.users[idx].name


def build_message_view(store: c.Store, m: c.Message) -> MessageView:
    v: MessageView = MessageView()
    v.id = m.id
    v.body = m.body
    v.creator_id = m.creator_id
    v.creator_name = user_name_of(store, m.creator_id)
    v.created_at = m.created_at
    v.client_message_id = m.client_message_id
    v.attachment_name = m.attachment_name
    has_att: bool = m.attachment_name != ""
    snd: str = c.sound_command(m.body)
    ct: int = c.content_type_of(has_att, snd)
    v.content_type = c.content_type_name(ct)
    for b in store.boosts:
        if b.message_id == m.id:
            v.boosts.append(b.content)
    for mid in m.mention_ids:
        nm: str = user_name_of(store, mid)
        if nm != "":
            v.mentions.append(nm)
    return v


def room_page(store: c.Store, room_id: int, user_id: int) -> RoomPageResult:
    if c.find_membership_index(store, room_id, user_id) < 0:
        return RoomPageResult(ok=False, value=RoomPageView(), error="not a member")
    ridx: int = c.find_room_index(store, room_id)
    if ridx < 0:
        return RoomPageResult(ok=False, value=RoomPageView(), error="room not found")
    room: c.Room = store.rooms[ridx]
    msgs: list[c.Message] = c.room_messages(store, room_id)
    page: list[c.Message] = c.last_page(msgs)
    view: RoomPageView = RoomPageView()
    view.room_id = room.id
    view.room_name = room.name
    view.room_kind = room.kind
    view.has_more = len(msgs) > c.PAGE_SIZE
    for m in page:
        view.messages.append(build_message_view(store, m))
    assert view.room_id > 0
    return RoomPageResult(ok=True, value=view, error="")


def messages_page(
    store: c.Store, room_id: int, user_id: int, before_id: int, after_id: int
) -> MessagesPageResult:
    if c.find_membership_index(store, room_id, user_id) < 0:
        return MessagesPageResult(ok=False, value=[], error="not a member")
    msgs: list[c.Message] = c.room_messages(store, room_id)
    page: list[c.Message] = []
    if before_id > 0:
        anchor_idx: int = c.find_message_index(store, before_id)
        if anchor_idx < 0:
            return MessagesPageResult(ok=False, value=[], error="message not found")
        anchor: c.Message = store.messages[anchor_idx]
        page = c.page_before(msgs, anchor.created_at, anchor.id)
    elif after_id > 0:
        anchor_idx2: int = c.find_message_index(store, after_id)
        if anchor_idx2 < 0:
            return MessagesPageResult(ok=False, value=[], error="message not found")
        anchor2: c.Message = store.messages[anchor_idx2]
        page = c.page_after(msgs, anchor2.created_at, anchor2.id)
    else:
        page = c.last_page(msgs)
    out: list[MessageView] = []
    for m in page:
        out.append(build_message_view(store, m))
    return MessagesPageResult(ok=True, value=out, error="")


def sidebar(store: c.Store, user_id: int) -> SidebarResult:
    if c.find_user_index(store, user_id) < 0:
        return SidebarResult(ok=False, value=[], error="user not found")
    entries: list[SidebarEntry] = []
    for m in store.memberships:
        if m.user_id == user_id and c.is_visible_membership(m.involvement):
            ridx: int = c.find_room_index(store, m.room_id)
            if ridx >= 0:
                e: SidebarEntry = SidebarEntry()
                e.room_id = m.room_id
                e.room_name = store.rooms[ridx].name
                e.room_kind = store.rooms[ridx].kind
                e.unread = m.unread_at != 0
                e.involvement = m.involvement
                entries.append(e)
    ordered: list[SidebarEntry] = []
    for e in entries:
        pos: int = 0
        while pos < len(ordered):
            o: SidebarEntry = ordered[pos]
            if o.room_name.lower() > e.room_name.lower():
                break
            if o.room_name.lower() == e.room_name.lower() and o.room_id > e.room_id:
                break
            pos += 1
        head: list[SidebarEntry] = []
        tail: list[SidebarEntry] = []
        i: int = 0
        while i < len(ordered):
            if i < pos:
                head.append(ordered[i])
            else:
                tail.append(ordered[i])
            i += 1
        head.append(e)
        for t in tail:
            head.append(t)
        ordered = head
    return SidebarResult(ok=True, value=ordered, error="")


def search_page(
    store: c.Store, index: SearchIndex, user_id: int, query: str, limit: int
) -> SearchPageResult:
    if c.find_user_index(store, user_id) < 0:
        return SearchPageResult(ok=False, value=[], error="user not found")
    ids: list[int] = search_messages(store, index, user_id, query, limit)
    out: list[SearchHitView] = []
    for mid in ids:
        midx: int = c.find_message_index(store, mid)
        if midx < 0:
            continue
        m: c.Message = store.messages[midx]
        hit: SearchHitView = SearchHitView()
        hit.message = build_message_view(store, m)
        ridx: int = c.find_room_index(store, m.room_id)
        if ridx >= 0:
            hit.room_name = store.rooms[ridx].name
        out.append(hit)
    return SearchPageResult(ok=True, value=out, error="")


def post_message_view(
    store: c.Store,
    room_id: int,
    creator_id: int,
    body: str,
    client_message_id: str,
    now: int,
) -> c.MessageResult:
    return c.post_message(
        store, room_id, creator_id, body, "", [], client_message_id, now
    )


# ---------------------------------------------------------------------------
# Deterministic seeder (LCG only; same corpus in every language)
# ---------------------------------------------------------------------------

WORDS: list[str] = [
    "coffee", "morning", "standup", "deploy", "review", "lunch", "weekend",
    "hike", "trail", "summit", "server", "latency", "cache", "query",
    "index", "search", "rooms", "sidebar", "mention", "thread", "reply",
    "draft", "ship", "launch", "retro", "sprint", "ticket", "bugfix",
    "hotfix", "merge", "branch", "commit", "push", "pull", "test",
    "green", "red", "flaky", "retry", "timeout", "queue", "worker",
    "cron", "backup", "restore", "migrate", "schema", "column", "row",
    "table", "join", "filter", "sort", "page", "limit", "offset",
    "cursor", "scroll", "unread", "badge", "ping", "pong", "hello",
    "thanks", "please", "sorry", "welcome", "goodbye", "night", "today",
    "tomorrow", "yesterday", "meeting", "agenda", "notes", "doc",
    "link", "image", "video", "audio", "file", "upload", "download",
    "share", "invite", "join", "leave", "archive", "pin", "star",
    "emoji", "react", "laugh", "party", "tada", "rocket", "fire",
    "water", "cooler", "chat", "talk", "discuss", "decide", "shipit",
    "rails", "ruby", "python", "go", "rust", "lean", "elixir",
    "postgres", "redis", "sqlite", "docker", "server", "client",
]


def pick_word(rng: Rng) -> str:
    return WORDS[rng_next(rng, len(WORDS))]


def make_body(rng: Rng, coffees: bool) -> str:
    n: int = 5 + rng_next(rng, 20)
    out: str = ""
    i: int = 0
    while i < n:
        if i > 0:
            out += " "
        if coffees and rng_next(rng, 20) == 0:
            out += "coffee"
        else:
            out += pick_word(rng)
        i += 1
    return out


def seed_store(user_count: int, big_room_messages: int, seed: int) -> c.Store:
    assert user_count > 0
    assert big_room_messages > 0
    rng: Rng = Rng()
    rng.state = seed
    store: c.Store = c.Store()
    code: c.StrResult = c.format_join_code("SeedCode1234")
    assert code.ok
    store.accounts.append(c.Account(id=1, name="Acme", join_code=code.value))
    store.next_id = 2
    now: int = 1700000000 - 30 * 86400
    users: list[int] = []
    ui: int = 0
    while ui < user_count:
        nm: str = "user" + str(ui)
        em: str = "user" + str(ui) + "@example.com"
        role: int = c.ROLE_MEMBER
        if ui == 0:
            role = c.ROLE_ADMIN
        res: c.UserResult = c.create_user(store, nm, em, role, now, "")
        assert res.ok
        users.append(res.value.id)
        ui += 1
    general: c.RoomResult = c.create_room(
        store, c.ROOM_OPEN, "Watercooler", users[0], users, now
    )
    assert general.ok
    eng: c.RoomResult = c.create_room(
        store, c.ROOM_CLOSED, "Engineering", users[0], users, now
    )
    assert eng.ok
    gid: int = general.value.id
    mi: int = 0
    while mi < big_room_messages:
        now += 1 + rng_next(rng, 30)
        uid: int = users[rng_next(rng, len(users))]
        body: str = make_body(rng, True)
        mentions: list[int] = []
        if rng_next(rng, 12) == 0:
            mid2: int = users[rng_next(rng, len(users))]
            if mid2 != uid:
                body = "@" + user_name_of(store, mid2) + " " + body
                mentions.append(mid2)
        posted: c.MessageResult = c.post_message(
            store, gid, uid, body, "", mentions, "", now
        )
        assert posted.ok
        if rng_next(rng, 12) == 0:
            booster: int = users[rng_next(rng, len(users))]
            c.boost_message(store, posted.value.id, booster, "tada", now)
        mi += 1
    assert len(store.messages) == big_room_messages
    return store
