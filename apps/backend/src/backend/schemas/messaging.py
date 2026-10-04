"""Messaging between patients and professionals, and the connect settings it needs.

Held under the `connect` consent ("Studies, surveys and contacts"). Message bodies are plain
text (links are never made clickable), at most 2,000 characters, stored encrypted. No model ever
reads them. User ids never appear in these schemas: the other side of a thread is a name
snapshot and, for a professional, their public card id.
"""

import unicodedata
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator

from backend.schemas.common import ApiModel

MAX_BODY = 2000
MAX_DISPLAY_NAME = 60
DAILY_THREAD_LIMIT = 5
INACTIVE_MONTHS = 12
MAX_THREADS_PAGE = 200

# The text next to the extra required checkbox for users aged 16 or 17, on their first message in
# each thread (connect-plan section 8). The frontend shows it with the recipient's name; the
# version is stored with the agreement. Bump both sides together when the wording changes.
GUARDIAN_TEXT_VERSION = "guardian-2026-10-04"
GUARDIAN_TEXT = "A parent or guardian knows about this and agrees that I share it with {recipient}."

# Filing a report authorizes the Amber team to read that conversation (logged).
REPORT_AUTHORIZATION_VERSION = "report-2026-10-04"
REPORT_AUTHORIZATION_TEXT = (
    "I ask the Amber team to read this conversation to review my report. Every access is logged."
)

# The connect consent notice (the frontend dialog shows it; version in schemas/account.py).
CONNECT_CONSENT_TEXT = (
    "Studies, surveys and contacts: Amber lets you write to verified doctors and researchers who "
    "accept messages. We store your messages encrypted and show them only to you and the person "
    "you write to. No AI model reads them, and the Amber team reads a conversation only when you "
    "report it, and every such access is logged. Messages are not a medical consultation. You "
    "tell us your age group; if you are 16 or 17, you confirm that a parent or guardian agrees "
    "(self-declared, not checked). Withdrawing this consent deletes your messages and closes "
    "your conversations."
)


def _has_control(value: str) -> bool:
    return any(unicodedata.category(c) in ("Cc", "Zl", "Zp") and c not in "\n\t" for c in value)


def clean_body(value: str) -> str:
    """Plain text: CRLF becomes LF, other control characters fail, 1-2,000 characters."""
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    if _has_control(value):
        raise ValueError("control characters are not allowed")
    if not value.strip():
        raise ValueError("empty")
    if len(value) > MAX_BODY:
        raise ValueError("too long")
    return value


def clean_name(value: str) -> str:
    if _has_control(value) or "\n" in value or "\t" in value:
        raise ValueError("control characters are not allowed")
    value = " ".join(value.split())
    if not value or len(value) > MAX_DISPLAY_NAME:
        raise ValueError("1-60 characters")
    return value


class AgeGroup(StrEnum):
    adult = "18_plus"
    minor = "16_17"


class ThreadStatus(StrEnum):
    """requested: waiting for the professional; open; declined; closed (withdrawn consent, a
    deleted account or a role change); blocked (one side blocked the other)."""

    requested = "requested"
    open = "open"
    declined = "declined"
    closed = "closed"
    blocked = "blocked"


class ThreadOrigin(StrEnum):
    card = "card"
    signup = "signup"


class ThreadRole(StrEnum):
    opener = "opener"
    recipient = "recipient"


class ReportReason(StrEnum):
    harassment = "harassment"
    spam = "spam"
    medical_advice = "medical_advice"
    impersonation = "impersonation"
    other = "other"


# ---- connect settings -----------------------------------------------------------------------


class ConnectStatus(ApiModel):
    consent_active: bool = Field(description="An active `connect` consent exists.")
    age_group: AgeGroup | None = Field(
        description="Self-declared at the first connect action; null until stated."
    )
    age_group_set_at: datetime | None = None
    guardian_text: str = Field(
        description="The extra checkbox for users aged 16 or 17; `{recipient}` is replaced by the "
        "recipient's name."
    )
    guardian_text_version: str
    report_authorization_text: str
    report_authorization_version: str


class AgeGroupUpdate(ApiModel):
    model_config = ConfigDict(extra="forbid")

    age_group: AgeGroup = Field(description="18_plus or 16_17 (self-declared, correctable).")


# ---- threads and messages ---------------------------------------------------------------------


class Counterpart(ApiModel):
    """The other person in a thread. Never a user id."""

    name: str | None = Field(description="Name snapshot; null when the account was deleted.")
    is_professional: bool = Field(description="The other side is the professional (recipient).")
    card_id: UUID | None = Field(
        None, description="The professional's public card, for the patient's side only."
    )
    deleted: bool = Field(
        description="The account was deleted: its messages were removed (show a placeholder)."
    )


class ThreadSummary(ApiModel):
    id: UUID
    origin: ThreadOrigin
    status: ThreadStatus
    my_role: ThreadRole
    counterpart: Counterpart
    created_at: datetime
    last_message_at: datetime | None
    unread_count: int = Field(description="Messages from the other side since my last read.")
    can_send: bool = Field(description="The thread is open and both people are still here.")
    can_respond: bool = Field(description="A request waiting for me to accept or decline.")
    blocked_by_me: bool
    guardian_agreement_needed: bool = Field(
        description="I am 16 or 17 and have not yet ticked the guardian checkbox in this thread: "
        "my next message must send `guardian_agreed: true`."
    )


class Message(ApiModel):
    id: UUID
    mine: bool
    body: str | None = Field(
        description="Plain text; render as text, never as HTML or clickable links. Null if it "
        "could not be decrypted."
    )
    created_at: datetime


class ThreadDetail(ApiModel):
    thread: ThreadSummary
    messages: list[Message] = Field(description="Oldest first.")


class ThreadList(ApiModel):
    items: list[ThreadSummary] = Field(description="Most recent activity first; hidden excluded.")
    unread_total: int
    requests_waiting: int = Field(description="Requests waiting for me to accept or decline.")


class OpenThreadRequest(ApiModel):
    """A request to a professional's card: one message the professional accepts or declines."""

    model_config = ConfigDict(extra="forbid")

    card_id: UUID = Field(description="The professional's public card.")
    display_name: str = Field(
        description="How the professional sees you (1-60 characters). Your e-mail, account name "
        "and profile are never shown."
    )
    body: str = Field(description="The request message, plain text, 1-2,000 characters.")
    guardian_agreed: bool = Field(
        False, description="Required true when the age group is 16_17 (see ConnectStatus)."
    )

    @field_validator("display_name")
    @classmethod
    def _name(cls, value: str) -> str:
        return clean_name(value)

    @field_validator("body")
    @classmethod
    def _body(cls, value: str) -> str:
        return clean_body(value)


class SendMessageRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(description="Plain text, 1-2,000 characters.")
    guardian_agreed: bool = Field(
        False,
        description="Required true on the first message in a thread when the age group is 16_17.",
    )

    @field_validator("body")
    @classmethod
    def _body(cls, value: str) -> str:
        return clean_body(value)


class ReportRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    reason: ReportReason
    message_id: UUID | None = Field(None, description="The message reported, if one.")
    authorize_review: bool = Field(
        description="Must be true: the report authorizes the Amber team to read this "
        "conversation (REPORT_AUTHORIZATION_TEXT); every access is logged."
    )

    @field_validator("authorize_review")
    @classmethod
    def _must_authorize(cls, value: bool) -> bool:
        if not value:
            raise ValueError("a report needs the authorization to review the conversation")
        return value


class Report(ApiModel):
    id: UUID
    thread_id: UUID | None
    message_id: UUID | None
    reason: ReportReason
    authorization_version: str
    created_at: datetime
    reviewed_at: datetime | None


class Block(ApiModel):
    id: UUID
    name: str | None = Field(description="Name snapshot of the blocked person.")
    created_at: datetime


class BlockList(ApiModel):
    items: list[Block]


class MessageUnreadCount(ApiModel):
    count: int = Field(description="Unread messages in threads that are not hidden.")
    requests_waiting: int = Field(description="Requests waiting for me to accept or decline.")


# ---- export -----------------------------------------------------------------------------------


class MessageExport(ApiModel):
    id: UUID
    body: str | None
    created_at: datetime


class ThreadExport(ApiModel):
    """A thread I take part in, with my own messages only (the other side's are theirs)."""

    id: UUID
    origin: ThreadOrigin
    status: ThreadStatus
    my_role: ThreadRole
    counterpart_name: str | None
    my_display_name: str | None
    created_at: datetime
    accepted_at: datetime | None
    closed_at: datetime | None
    last_message_at: datetime | None
    last_read_at: datetime | None
    hidden_at: datetime | None
    guardian_agreed_at: datetime | None
    guardian_text_version: str | None
    my_messages: list[MessageExport]


class ConnectExport(ApiModel):
    age_group: AgeGroup | None
    age_group_set_at: datetime | None
    threads: list[ThreadExport]
    blocks: list[Block]
    reports: list[Report]
