"""SQLite persistence via fquery.sqlmodel, schema-compatible with Rails/Django.

Table and column names match ../once-campfire/db/schema.rb (and
../once-campfire-django/campfire/schema.sql) so databases open in any of
the three implementations: memberships (string involvement), rooms.type
strings, email_address/password_digest, porter FTS with triggers.

Representation notes (documented differences, not silent):
- involvement/room type live as Rails strings in the DB and map to the
  domain int enums at the boundary (involvement_name/kind tables below).
- timestamps stay integer epoch seconds (Rails uses datetime(6)); the
  columns accept both forms in SQLite.
- message_mentions is an extension table (Rails embeds mentions in rich
  text); unknown tables are ignored by the sibling implementations.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from fquery.sqlmodel import sqlmodel
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine


def to_db_time(ts: int) -> str:
    """Epoch seconds to Rails/Django SQLite datetime text (UTC)."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S.%f")


def from_db_time(value) -> int:
    """DB time (ISO text or epoch int) back to epoch seconds."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text_value = str(value).strip()
    if text_value == "":
        return 0
    if "-" not in text_value and text_value.lstrip("-").isdigit():
        return int(text_value)
    stamp = text_value.replace("Z", "")
    if " " not in stamp and "T" in stamp:
        stamp = stamp.replace("T", " ")
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())

ROOM_KIND_TO_TYPE = {0: "Rooms::Open", 1: "Rooms::Closed", 2: "Rooms::Direct"}
ROOM_TYPE_TO_KIND = {v: k for k, v in ROOM_KIND_TO_TYPE.items()}

INVOLVEMENT_TO_NAME = {
    0: "invisible", 1: "nothing", 2: "mentions", 3: "everything",
}
INVOLVEMENT_TO_ID = {v: k for k, v in INVOLVEMENT_TO_NAME.items()}


@sqlmodel
@dataclass
class User:
    id: int = 0
    name: str = ""
    email_address: str = ""
    password_digest: str = ""
    bio: str = ""
    bot_token: str = ""
    role: int = 0
    status: int = 0
    created_at: int = 0
    updated_at: int = 0


@sqlmodel
@dataclass
class Room:
    id: int = 0
    name: str = ""
    type: str = "Rooms::Open"
    creator_id: int = 0
    created_at: int = 0
    updated_at: int = 0


@sqlmodel(table_name="memberships")
@dataclass
class Membership:
    id: int = 0
    room_id: int = 0
    user_id: int = 0
    involvement: str = "mentions"
    connections: int = 0
    connected_at: int = 0
    unread_at: int = 0
    created_at: int = 0
    updated_at: int = 0


@sqlmodel
@dataclass
class Message:
    id: int = 0
    room_id: int = 0
    creator_id: int = 0
    client_message_id: str = ""
    created_at: int = 0
    updated_at: int = 0


@sqlmodel(table_name="action_text_rich_texts")
@dataclass
class RichText:
    id: int = 0
    record_type: str = "Message"
    record_id: int = 0
    name: str = "body"
    body: str = ""
    created_at: int = 0
    updated_at: int = 0


@sqlmodel
@dataclass
class MessageMention:
    id: int = 0
    message_id: int = 0
    user_id: int = 0


@sqlmodel
@dataclass
class Boost:
    id: int = 0
    message_id: int = 0
    booster_id: int = 0
    content: str = ""
    created_at: int = 0
    updated_at: int = 0


@sqlmodel
@dataclass
class Ban:
    id: int = 0
    user_id: int = 0
    ip_address: str = ""
    created_at: int = 0
    updated_at: int = 0


@sqlmodel(table_name="sessions")
@dataclass
class UserSession:
    id: int = 0
    user_id: int = 0
    token: str = ""
    ip_address: str = ""
    user_agent: str = ""
    last_active_at: int = 0
    created_at: int = 0
    updated_at: int = 0


@sqlmodel(table_name="searches")
@dataclass
class SearchRecord:
    id: int = 0
    user_id: int = 0
    query: str = ""
    created_at: int = 0
    updated_at: int = 0


@sqlmodel
@dataclass
class PushSubscription:
    id: int = 0
    user_id: int = 0
    endpoint: str = ""
    p256dh_key: str = ""
    auth_key: str = ""
    user_agent: str = ""
    created_at: int = 0
    updated_at: int = 0


@sqlmodel
@dataclass
class Webhook:
    id: int = 0
    user_id: int = 0
    url: str = ""
    created_at: int = 0
    updated_at: int = 0


@sqlmodel
@dataclass
class Account:
    id: int = 0
    name: str = ""
    join_code: str = ""
    custom_styles: str = ""
    settings: str = ""
    singleton_guard: int = 0
    created_at: int = 0
    updated_at: int = 0


TABLES = [
    User, Room, Membership, Message, RichText, MessageMention, Boost, Ban,
    UserSession, SearchRecord, PushSubscription, Webhook, Account,
]

FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS message_search_index
USING fts5(body, tokenize='porter');
"""

TRIGGER_SQL = [
    # Bodies live in action_text_rich_texts (Rails form); the FTS index
    # follows them there. Legacy ActionText::RichText rows are covered too.
    """
    CREATE TRIGGER IF NOT EXISTS rich_texts_ai AFTER INSERT ON action_text_rich_texts
    WHEN new.record_type IN ('Message', 'ActionText::RichText') AND new.name = 'body'
    BEGIN
      INSERT INTO message_search_index(rowid, body) VALUES (new.record_id, new.body);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS rich_texts_au AFTER UPDATE ON action_text_rich_texts
    WHEN new.record_type IN ('Message', 'ActionText::RichText') AND new.name = 'body'
    BEGIN
      UPDATE message_search_index SET body = new.body WHERE rowid = new.record_id;
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS rich_texts_ad AFTER DELETE ON action_text_rich_texts
    WHEN old.record_type IN ('Message', 'ActionText::RichText') AND old.name = 'body'
    BEGIN
      DELETE FROM message_search_index WHERE rowid = old.record_id;
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS rich_text_cleanup_ad AFTER DELETE ON messages BEGIN
      DELETE FROM action_text_rich_texts
      WHERE record_id = old.id AND name = 'body'
        AND record_type IN ('Message', 'ActionText::RichText');
    END;
    """,
]

INDEX_SQL = [
    "CREATE UNIQUE INDEX IF NOT EXISTS index_memberships_on_room_id_and_user_id"
    " ON memberships (room_id, user_id);",
    "CREATE INDEX IF NOT EXISTS index_memberships_on_room_id"
    " ON memberships (room_id);",
    "CREATE INDEX IF NOT EXISTS index_memberships_on_user_id"
    " ON memberships (user_id);",
    "CREATE INDEX IF NOT EXISTS index_memberships_on_room_id_and_created_at"
    " ON memberships (room_id, created_at);",
    "CREATE UNIQUE INDEX IF NOT EXISTS index_accounts_on_singleton_guard"
    " ON accounts (singleton_guard);",
    "CREATE UNIQUE INDEX IF NOT EXISTS index_action_text_rich_texts_uniqueness"
    " ON action_text_rich_texts (record_type, record_id, name);",
    "CREATE INDEX IF NOT EXISTS index_boosts_on_booster_id"
    " ON boosts (booster_id);",
    "CREATE INDEX IF NOT EXISTS index_bans_on_user_id"
    " ON bans (user_id);",

    "CREATE INDEX IF NOT EXISTS index_messages_on_room_id"
    " ON messages (room_id);",
    "CREATE INDEX IF NOT EXISTS index_messages_on_creator_id"
    " ON messages (creator_id);",
    "CREATE UNIQUE INDEX IF NOT EXISTS index_sessions_on_token"
    " ON sessions (token);",
    "CREATE INDEX IF NOT EXISTS index_sessions_on_user_id"
    " ON sessions (user_id);",
    "CREATE UNIQUE INDEX IF NOT EXISTS index_users_on_email_address"
    " ON users (email_address);",
    "CREATE UNIQUE INDEX IF NOT EXISTS index_users_on_bot_token"
    " ON users (bot_token);",
    "CREATE INDEX IF NOT EXISTS index_searches_on_user_id"
    " ON searches (user_id);",
    "CREATE INDEX IF NOT EXISTS index_bans_on_ip_address"
    " ON bans (ip_address);",
    "CREATE INDEX IF NOT EXISTS index_boosts_on_message_id"
    " ON boosts (message_id);",
    "CREATE INDEX IF NOT EXISTS index_webhooks_on_user_id"
    " ON webhooks (user_id);",
]


def get_engine(url: str):
    engine = create_engine(url, connect_args={"check_same_thread": False})
    with Session(engine) as session:
        session.exec(text("PRAGMA journal_mode=WAL;"))
        session.exec(text("PRAGMA synchronous=NORMAL;"))
        session.commit()
    return engine


def create_schema(engine) -> None:
    tables = [m.__sqlmodel__.__table__ for m in TABLES]
    SQLModel.metadata.create_all(engine, tables=tables)
    with Session(engine) as session:
        session.exec(text(FTS_SQL))
        for trigger in TRIGGER_SQL:
            session.exec(text(trigger))
        for index in INDEX_SQL:
            session.exec(text(index))
        session.commit()


def load_store(engine, store, password_digest: str = "") -> dict:
    """Bulk-load a campfire.Store (ids preserved). Returns row counts."""
    counts = {}
    with Session(engine) as session:
        for u in store.users:
            # Rails stores NULL (not "") for absent bot tokens; NULLs do
            # not conflict in the UNIQUE index, empty strings would.
            session.add(User.__sqlmodel__(
                id=u.id, name=u.name, email_address=u.email,
                password_digest=password_digest or None, bio=u.bio,
                bot_token=u.bot_token or None, role=u.role,
                status=u.status, created_at=to_db_time(u.created_at),
                updated_at=to_db_time(u.created_at)))
        for r in store.rooms:
            session.add(Room.__sqlmodel__(
                id=r.id, name=r.name,
                type=ROOM_KIND_TO_TYPE.get(r.kind, "Rooms::Open"),
                creator_id=r.creator_id, created_at=to_db_time(r.created_at),
                updated_at=to_db_time(r.created_at)))
        for m in store.memberships:
            session.add(Membership.__sqlmodel__(
                id=m.id, room_id=m.room_id, user_id=m.user_id,
                involvement=INVOLVEMENT_TO_NAME.get(m.involvement, "mentions"),
                connections=m.connections, connected_at=m.connected_at or None,
                unread_at=m.unread_at or None, created_at=to_db_time(m.updated_at),
                updated_at=to_db_time(m.updated_at)))
        for m in store.messages:
            session.add(Message.__sqlmodel__(
                id=m.id, room_id=m.room_id, creator_id=m.creator_id,
                client_message_id=m.client_message_id,
                created_at=to_db_time(m.created_at),
                updated_at=to_db_time(m.created_at)))
            session.add(RichText.__sqlmodel__(
                record_type="Message", record_id=m.id, name="body",
                body=m.body, created_at=to_db_time(m.created_at),
                updated_at=to_db_time(m.created_at)))
            for mid in m.mention_ids:
                session.add(MessageMention.__sqlmodel__(
                    message_id=m.id, user_id=mid))
        for b in store.boosts:
            session.add(Boost.__sqlmodel__(
                id=b.id, message_id=b.message_id, booster_id=b.booster_id,
                content=b.content, created_at=to_db_time(b.created_at),
                updated_at=to_db_time(b.created_at)))
        base = min([u.created_at for u in store.users], default=0)
        for a in store.accounts:
            # The domain Account carries no timestamps; reuse the earliest
            # user time so Rails readers see a coherent NOT NULL value.
            session.add(Account.__sqlmodel__(
                id=a.id, name=a.name, join_code=a.join_code,
                created_at=to_db_time(base), updated_at=to_db_time(base)))
        session.commit()
        from sqlmodel import func, select
        counts["messages"] = session.exec(
            select(func.count(Message.__sqlmodel__.id))).one()
        counts["fts"] = session.exec(
            text("SELECT count(*) FROM message_search_index")).one()[0]
    return counts
