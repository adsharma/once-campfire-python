"""fquery bindings: @node declarations for every model + runner.

Query classes are generated with make_query_type (TABLE/ALIAS mirror
the Rails schema); chains execute with rows(session, chain, params).
Writes stay on db.exec / raw SQL. Predicates take user input only via
param("name") so values always travel as bind params, never SQL text.
"""

import ast
import sqlite3
from dataclasses import dataclass
from typing import List

from fquery.query import make_query_type
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
    pass


@node
@dataclass
class RoomNode:
    pass


@node
@dataclass
class MembershipNode:
    @edge
    async def room(self) -> List["RoomNode"]:
        yield []


@node
@dataclass
class RoomWithMembershipsNode:
    @edge
    async def memberships(self) -> List["MembershipNode"]:
        yield []


@node
@dataclass
class MessageNode:
    pass


@node
@dataclass
class RichTextNode:
    pass


@node
@dataclass
class MessageMentionNode:
    @edge
    async def user(self) -> List["UserNode"]:
        yield []


@node
@dataclass
class BanNode:
    pass


@node
@dataclass
class BoostNode:
    pass


@node
@dataclass
class UserSessionNode:
    pass


@node
@dataclass
class SearchRecordNode:
    pass


@node
@dataclass
class PushSubscriptionNode:
    pass


@node
@dataclass
class WebhookNode:
    pass


@node
@dataclass
class AccountNode:
    pass


@node
@dataclass
class FTSNode:
    @edge
    async def messages(self) -> List["MessageNode"]:
        yield []


def _qt(node_cls, name: str, table: str, alias: str = ""):
    ns = {"TABLE": table}
    if alias:
        ns["ALIAS"] = alias
    return make_query_type(node_cls, name, ns)


UserQuery = _qt(UserNode, "UserQuery", "users")
RoomQuery = _qt(RoomNode, "RoomQuery", "rooms")
MembershipQuery = _qt(MembershipNode, "MembershipQuery", "memberships")
RoomWithMembershipsQuery = _qt(
    RoomWithMembershipsNode, "RoomWithMembershipsQuery", "rooms", "room")
MessageQuery = _qt(MessageNode, "MessageQuery", "messages")
RichTextQuery = _qt(RichTextNode, "RichTextQuery", "action_text_rich_texts",
                    "rich")
MessageMentionQuery = _qt(MessageMentionNode, "MessageMentionQuery",
                          "message_mentions", "mm")
BanQuery = _qt(BanNode, "BanQuery", "bans")
BoostQuery = _qt(BoostNode, "BoostQuery", "boosts")
UserSessionQuery = _qt(UserSessionNode, "UserSessionQuery", "sessions", "sess")
SearchRecordQuery = _qt(SearchRecordNode, "SearchRecordQuery", "searches",
                        "search")
PushSubscriptionQuery = _qt(PushSubscriptionNode, "PushSubscriptionQuery",
                            "push_subscriptions", "push")
WebhookQuery = _qt(WebhookNode, "WebhookQuery", "webhooks")
AccountQuery = _qt(AccountNode, "AccountQuery", "accounts")
FTSQuery = _qt(FTSNode, "FTSQuery", "message_search_index", "idx")
