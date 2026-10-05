"""fquery bindings: @node/@query declarations for every model + runner.

Production reads build chains against these (TABLE/ALIAS mirror the
Rails schema) and execute them with rows(session, chain, params).
Writes stay on db.exec / raw SQL. Predicates take user input only via
param("name") so values always travel as bind params, never SQL text.
"""

import ast
import sqlite3
from dataclasses import dataclass
from typing import List

from fquery.query import query
from fquery.view_model import edge, node
from fquery.walk import JoinOn  # noqa: F401 (re-exported for chain sites)


def alias(qcls) -> str:
    from fquery.sql_builder import SQLBuilderVisitor
    return SQLBuilderVisitor.alias_for(qcls)


def pred(text: str) -> ast.Expr:
    return ast.Expr(text)


def order(text: str) -> ast.Expr:
    return ast.Expr(text)


def rows(session, chain, params=None) -> list:
    """Run a chain on the session's own connection (sees flushed writes)."""
    conn = session.connection().connection.driver_connection
    if not isinstance(conn, sqlite3.Connection):
        raise TypeError("fquery runner needs a sqlite3 connection")
    return chain.to_rows(conn, params)


@node
@dataclass
class UserNode:
    QUERY_NAME = "UserQuery"


@node
@dataclass
class RoomNode:
    QUERY_NAME = "RoomQuery"


@node
@dataclass
class MembershipNode:
    QUERY_NAME = "MembershipQuery"

    @edge
    async def room(self) -> List["RoomNode"]:
        yield []


@node
@dataclass
class RoomWithMembershipsNode:
    QUERY_NAME = "RoomWithMembershipsQuery"

    @edge
    async def memberships(self) -> List["MembershipNode"]:
        yield []


@node
@dataclass
class MessageNode:
    QUERY_NAME = "MessageQuery"


@node
@dataclass
class RichTextNode:
    QUERY_NAME = "RichTextQuery"


@node
@dataclass
class MessageMentionNode:
    QUERY_NAME = "MessageMentionQuery"

    @edge
    async def user(self) -> List["UserNode"]:
        yield []


@node
@dataclass
class BanNode:
    QUERY_NAME = "BanQuery"


@node
@dataclass
class BoostNode:
    QUERY_NAME = "BoostQuery"


@node
@dataclass
class UserSessionNode:
    QUERY_NAME = "UserSessionQuery"


@node
@dataclass
class SearchRecordNode:
    QUERY_NAME = "SearchRecordQuery"


@node
@dataclass
class PushSubscriptionNode:
    QUERY_NAME = "PushSubscriptionQuery"


@node
@dataclass
class WebhookNode:
    QUERY_NAME = "WebhookQuery"


@node
@dataclass
class AccountNode:
    QUERY_NAME = "AccountQuery"


@node
@dataclass
class FTSNode:
    QUERY_NAME = "FTSQuery"

    @edge
    async def messages(self) -> List["MessageNode"]:
        yield []


@query
class UserQuery:
    TYPE = UserNode
    TABLE = "users"


@query
class RoomQuery:
    TYPE = RoomNode
    TABLE = "rooms"


@query
class MembershipQuery:
    TYPE = MembershipNode
    TABLE = "memberships"


@query
class RoomWithMembershipsQuery:
    TYPE = RoomWithMembershipsNode
    TABLE = "rooms"
    ALIAS = "room"


@query
class MessageQuery:
    TYPE = MessageNode
    TABLE = "messages"


@query
class RichTextQuery:
    TYPE = RichTextNode
    TABLE = "action_text_rich_texts"
    ALIAS = "rich"


@query
class MessageMentionQuery:
    TYPE = MessageMentionNode
    TABLE = "message_mentions"
    ALIAS = "mm"


@query
class BanQuery:
    TYPE = BanNode
    TABLE = "bans"


@query
class BoostQuery:
    TYPE = BoostNode
    TABLE = "boosts"


@query
class UserSessionQuery:
    TYPE = UserSessionNode
    TABLE = "sessions"
    ALIAS = "sess"


@query
class WebhookQuery:
    TYPE = WebhookNode
    TABLE = "webhooks"


@query
class SearchRecordQuery:
    TYPE = SearchRecordNode
    TABLE = "searches"
    ALIAS = "search"


@query
class PushSubscriptionQuery:
    TYPE = PushSubscriptionNode
    TABLE = "push_subscriptions"
    ALIAS = "push"


@query
class AccountQuery:
    TYPE = AccountNode
    TABLE = "accounts"


@query
class FTSQuery:
    TYPE = FTSNode
    TABLE = "message_search_index"
    ALIAS = "idx"
