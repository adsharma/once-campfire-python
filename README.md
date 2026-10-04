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
| `Membership`, `Connectable` (60s TTL) | `Membership`, `is_connected`, `present/disconnect/disconnect_all` |
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
| SMT | `py2many --smt` | ❌ toolchain crash (missing `cljstyle`, `None.startwith`) |
| Lean | `py2many --lean` + `lake build` | ⏳ deferred — CHECKS are in place for it |
| Compile Rust | `rustc` on output | ❌ later: needs owned-`String` overhaul in py2many |

Run py2many from the checkout (it contains the lookup-table fixes below;
released 0.9 lacks them):

```bash
cd ~/src/py2many && uv run --project . python -m py2many --go /path/to/campfire.py --outdir out_go
```

## Toolchain fixes (in `~/src/py2many`, uncommitted)

Made while transpiling this port; covered by the repo suite
(`test_generated -k "go or rust"`: 68 passed, 0 failed) plus `go build`
of this port's output:

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

## Known limitations

- Go string iteration is byte-wise; Python is code-point-wise. Outcomes are
  identical for all predicates used here (UTF-8 preserves ordering; no
  multibyte byte ever equals an ASCII literal), except `user_initials` on
  non-ASCII names.
- IPv6 ban validation is an approximation (well-formedness + well-known
  non-public prefixes); IPv4 is strict.
- `Room.receive` push fan-out and webhook HTTP POST are outbox entries,
  not network calls, by design.
