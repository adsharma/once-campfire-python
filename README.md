# once-campfire-python

Campfire core domain in **static python** — a faithful port of the business
rules in [`../once-campfire`](https://github.com/basecamp/once-campfire)
(Basecamp ONCE Campfire, a Rails app) into a Python subset that transpiles
to Go (compiles today) and Rust (transpiles today, compiles later).

Following `.agents/skills/static-python-skill`, with one override: **no
pattern matching** — every branch is `if`/`elif`/`else` so the code runs on
any Python 3 and never depends on `match` semantics.

## Layout

| File | Purpose |
|---|---|
| `campfire.py` | The port. Single file, no dependencies beyond `py2many.spec` (contracts only). Transpile this. |
| `test_campfire.py` | 171 runnable checks (CPython). Not transpiled. |

## Static-python rules applied

- `int` is the fixed-width integer (`i32` in Rust, `int` in Go).
  Timestamps are `int` epoch seconds **passed in as arguments** — no clock
  calls, no randomness; callers supply tokens, client ids and `now`, which
  keeps every function pure and testable.
- Composition instead of inheritance: Rails concerns (`Role`, `Bot`,
  `Bannable`, `Connectable`, `Pagination`, `Mentionee`, …) are plain
  functions over dataclasses, and STI room types are one `Room` struct
  plus a `kind` tag (`ROOM_OPEN`/`ROOM_CLOSED`/`ROOM_DIRECT`).
- Result structs instead of exceptions: every fallible operation returns
  `XxxResult(ok, value, error)`. No `try`/`except` anywhere. (Monomorphic
  structs — one per entity — because py2many 0.9 cannot parse generic
  `Ok[T]`/`Result[T, E]` aliases.)
- Contracts as `assert` **plus** `CHECKER.pre`/`CHECKER.post` blocks
  (`from py2many.spec import CHECKER`). Asserts enforce at runtime and
  transpile to `assert!`/`panic`; CHECKER blocks are stripped for Rust/Go
  and reserved for the Lean backend (see Verification below).
- Transpiler-safe string handling only: `+` with a literal left operand
  or `+=` accumulators, `split`/`strip`/`lower`/`startswith`, char loops.
  No slicing, no `isinstance`, no regex, no backslash escapes in literals
  (built with `chr()` — py2many 0.9 mangles backslash literals in Rust
  output), single-line module docstring (multi-line docstrings break Go
  output).

## Rails → static-python mapping

| Rails | Port |
|---|---|
| `User`, roles, statuses | `User` + `ROLE_*`/`STATUS_*`, `can_administer`, `can_create_room` |
| `Room`, `Rooms::Open/Closed/Direct` | `Room.kind`, `default_involvement`, `direct_type_change_blocked`, `find_or_create_direct_room` (exact user-set match) |
| `Membership`, `Connectable` (60s TTL) | `RoomMembership` (`Membership` collides with Lean core), `is_connected`, `present/disconnect/disconnect_all` |
| `Message`, `Mentionee`, `Pagination` (40/page) | `Message`, `post_message`, `message_mentionees`, `last/first/before/after/around` |
| `Boost` (16-char limit) | `boost_message` |
| `Ban` (public IPs only) | `validate_ban_ip` (strict IPv4 + minimal IPv6), `ban_user`/`unban_user` |
| `User::Bot`, `Webhook` | `bot_key_of/parse`, `authenticate_bot`, `build_webhook_payload`, `webhook_reply_kind`, `apply_webhook_reply` |
| `Session` (1h refresh) | `start_session`, `touch_session`, `session_needs_refresh` |
| `Search` (keep 10) | `record_search`, `trim_searches` |
| `Account::Joinable` (`xxxx-xxxx-xxxx`) | `format_join_code`, `create/reset_account_join_code` |
| `Sound::BUILTIN` (55 sounds), `/play <name>` | `builtin_sounds`, `find_sound`, `sound_command` |
| ActionCable broadcasts | `Store.outbox` entries (`push:`, `webhook:`, `remove:`) — observable, no IO |
| `User#Bannable`, deactivate | `ban_user`, `deactivate_user` (keeps direct memberships, anonymises email) |

Out of scope (not transpilable): ActiveRecord persistence, ActionCable
delivery, ActiveStorage blobs (filename strings instead), ActionText rich
text (body strings + mention id lists), password hashing, signed ids,
token generation, HTTP clients (webhook POST, OpenGraph fetch), web-push
delivery, `Transferable` (Rails signed ids), ONCE platform glue
(`FirstRun`, `Purchaser`).

## Verification status

| Check | Command | Status |
|---|---|---|
| Python tests | `python3 test_campfire.py` | ✅ 171/171 |
| Transpile Rust | `py2many --rust campfire.py --outdir out_rust` | ✅ clean (rustfmt) |
| Transpile Go | `py2many --go campfire.py --outdir out_go` | ✅ clean (gofmt) |
| Compile Go | `go build` + `go vet` on output | ✅ clean |
| Contracts | `CHECKER.pre/post` on ~40 functions | ✅ stripped for Rust/Go |
| Lean | `py2many --lean` + `lake build` | ✅ file elaborates; ~80 obligations auto-discharged, 20 open (see below) |
| SMT | `py2many --smt` | ❌ toolchain crash (missing `cljstyle`, `None.startwith`) |
| Compile Rust | `rustc` on output | ❌ later: needs owned-`String` overhaul in py2many |

## Lean verification (20 open obligations)

`lake build` elaborates the whole file; every remaining error is a genuine
proof obligation (no translation gaps left). Closed automatically: all
single-return definitional posts, all error-branch returns (`¬False`), all
positive if/elif/else branches (hypotheses + `simp_all`/`omega`/`decide`/`grind`),
trivial call-site pres. Open classes:

- **Loops (9)**: `remove_all`, `same_id_set`, `sound_command`, `parse_ipv4`,
  `format_join_code`, `last_page`, `first_page`, `page_around`,
  `record_search` (touch path) — need loop invariants / indexed reasoning.
- **Data (5)**: `create_user`, `create_room`, `post_message`, `boost_message`,
  `start_session` success returns (`id > 0` from `alloc_id`, opaque).
- **Call-opaque (4)**: `apply_webhook_reply` ×2, `create_account`,
  `record_search` touch path — need callee postcondition propagation.
- **String library (2)**: `bot_key_of` (`toString` length), `deactivated_email`
  (`splitOn` round-trip lemma).

Two porting conventions came out of this and are applied throughout:

- Guard sequences are `if`/`elif`/`else` chains (never fallthrough returns),
  so each branch's negations are available as hypotheses.
- Success values are constructed inline at `return` (sharing one allocated
  id via a `new_id` local) so postconditions see the literal.
- `CHECKER.pre` appears only where call sites can discharge it (trivially
  true `Nat` facts, or uncalled functions); `Membership` was renamed
  `RoomMembership` (Lean core collision) and helpers are ordered before use.

Run py2many from the checkout (it contains the lookup-table fixes below;
released 0.9 lacks them):

```bash
cd ~/src/py2many && uv run --project . python -m py2many --go /path/to/campfire.py --outdir out_go
```

## Toolchain fixes (in `~/src/py2many`; Go fixes in PR #850, Lean fixes in PR #851)

Made while transpiling this port; covered by the repo suite plus `go build`
of this port's output and `lake build` of its Lean output:

- `py2many/rewriters.py` — `CheckerBlockRemover.visit_If` now recurses
  (`generic_visit`), so CHECKER blocks nested inside regular `if`s are
  stripped too (previously only top-level ones were).
- `pygo/stubs.py` — lookup table: `str.startswith` → `strings.HasPrefix`,
  `str.endswith` → `strings.HasSuffix`, plus `str.isalnum`/`str.isascii`.
- `pygo/plugins.py` — dispatch map: `ord(x)` → `int([]rune(x)[0])`,
  `chr(n)` → `string(rune(n))`.
- `pygo/transpiler.py` — `for ch in s` over a `str` now emits byte-indexed
  iteration yielding 1-byte strings (Go `range` would yield runes and break
  every string comparison); `.append` rewriting extended to inferred
  `list[T]` variables and `store.items.append(...)` attribute targets.
- `pylean/*` — subtype parens, `str` method table (`startsWith`, `splitOn`,
  `trim`, `toLower`, …), `ord`/`chr`, lowercase containers, `String`
  iteration via `toList.map toString`, `++` for `String`, struct functional
  updates, `let mut` for field-mutated params, `Inhabited` derivation,
  default-filled partial literals, `if hN` hypotheses, uniform
  `(try simp_all) <;> (first | omega | decide | grind)` return tactic,
  `Int` widening for `-1` sentinels with call-site `.toNat`/coercions.

## HTTP app + benchmark (`campfile` package)

`src/campfile` is an idiomatic Flask app (factory in `campfile/__init__.py`,
blueprints in `campfile/routes/`, config in `campfile/config.py`, `wsgi.py`
entry point) over the port. The domain stays in `campfile/domain/`
(`campfire.py` is still the single transpilable unit; `workload.py` adds
seeding, Porter stemming, the inverted index and the five hot paths).

```bash
uv venv && uv pip install -e .
.venv/bin/python tests/test_campfire.py  # 171 domain checks
.venv/bin/python tests/test_workload.py  # 34 workload checks (porter, pages, search)
.venv/bin/gunicorn -w 4 wsgi:app           # one in-memory store per worker
.venv/bin/python bench/bench_http.py http://127.0.0.1:5057 --concurrency 12
```

Routes mirror `bench/compare_http.rb`: `GET /rooms/<id>`,
`GET /rooms/<id>/messages?before=`, `GET /users/me/sidebar`,
`GET /searches?q=`, `POST /rooms/<id>/messages`, plus `/__meta`.

Measured on this machine (4 gunicorn sync workers, 12 client threads,
60 users / 3000 messages synthetic seed) vs the Ruby numbers from
`../once-campfire` (16 clients, fixed seed). The SQLite column exercises
cookie login per thread (like the Rails bench); the in-memory column
uses the `?as=` backdoor:

| path | SQLite+auth req/s (p50) | in-memory req/s | Ruby req/s |
|---|---|---|---|
| room | 1335 (8.1ms) | 3074 | 244 |
| messages | 1411 (7.8ms) | 3008 | 424 |
| sidebar | 2461 (4.2ms) | 3371 | 556 |
| search | 826 (13.4ms) | 1034 | 432 |
| post | 1151 (7.6ms) | 3127 | 258 |

Read this as methodology, not victory: different corpora and hardware,
JSON API vs full HTML/ActionText rendering, no CSRF, CPython vs
Ruby+Puma. The Ruby request does far more work per request — HTML
rendering parity is what would make this fully apples-to-apples. What
changed structurally: SQLite (WAL) round-trips on every path, session
token lookup per request, and FTS5-BM25 search in C (faster than the
Python postings merge it replaced). Search parity costs: Django's
`LIMIT 100` (vs the earlier 20) builds 5x views per query.

## Compatibility with once-campfire-django

Functional compatibility target: same database, same session model, same
routes. Verified by `tests/test_compat.py` (reads/writes a database
created from their `schema.sql`) and `tests/test_auth.py` (20 flow checks).

| Area | Status |
|---|---|
| Tables/columns | same names for all Rails tables; string `involvement`/`type`, `email_address`, `password_digest`, porter FTS + triggers |
| Bodies | `action_text_rich_texts` like Rails/Django (record `Message`, legacy `ActionText::RichText` accepted) |
| Timestamps | integer epoch in, ISO datetime text out (Rails form); mixed-representation DBs order correctly, arithmetic coerces |
| Sessions | bcrypt login, token rows, throttled touch, signed `session_token` cookie; banned/deactivated rejected |
| Routes | same paths (`rooms/<kind>`, bot keys, boosts, `/autocompletable/users`, `searches/clear`, `account/*`, `users/*`); 302 to `/session/new` when anonymous; 403/404/401/422 matching Django; 204 on deletes; bot `Location` + `X-Total-Count`/`Link` headers |
| Behavior | unread fan-out (`connected_at < now-60`, invisible excluded), open-room grants on signup, direct-room dedupe, 10-query search history cap, `restrict_room_creation_to_administrators` gate, deactivate/ban semantics (session/IP cleanup, email rewrite, status flips) |
| Known boundaries | cookie crypto is Flask-native (not Rails-interchangeable); `message_mentions` is an extension table; no ActiveStorage/media/Cable/jobs/push; timestamps differ from Django reads (ints vs datetimes in the in-memory layer only) |

## Known limitations

- Go string iteration is byte-wise; Python is code-point-wise. Outcomes are
  identical for all predicates used here (UTF-8 preserves ordering; no
  multibyte byte ever equals an ASCII literal), except `user_initials` on
  non-ASCII names.
- IPv6 ban validation is an approximation (well-formedness + well-known
  non-public prefixes); IPv4 is strict.
- `Room.receive` push fan-out and webhook HTTP POST are outbox entries,
  not network calls, by design.
