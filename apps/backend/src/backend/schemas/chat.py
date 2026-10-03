"""Chat schemas. AgentReply mirrors the output contract in docs/specs/agent.md."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from backend.schemas.common import ApiModel
from backend.schemas.enums import ActionType, CardType, ChatRole, ChipType, ConfidenceLevel, Origin
from backend.schemas.gap import GapSearchRequest


class Chip(ApiModel):
    type: ChipType = Field(description="disease, gene, variant or symptom.")
    id: str | None = Field(description="Resolved stable ID (MONDO, HGNC, CLINVAR, HP) or null.")
    label: str = Field(description="Label shown on the chip.")
    negated: bool = Field(description="True for negations ('no feeding problems').")
    confirmed: bool = Field(description="True once the user confirmed the chip.")


class Claim(ApiModel):
    text: str = Field(description="One claim, in the lens's language and reading level.")
    edge_ids: list[str] = Field(description="Edges backing the claim (from this turn's tools).")
    origin: Origin = Field(description="observed = data, inferred = hypothesis, and others.")
    confidence: ConfidenceLevel


class Contradiction(ApiModel):
    claim_index: int = Field(description="Index into claims[].")
    edge_ids: list[str] = Field(description="Edges carrying the contradicting evidence.")
    note: str


class Card(ApiModel):
    type: CardType
    node_ids: list[str]
    edge_ids: list[str]


class GraphFocus(ApiModel):
    node_ids: list[str] = Field(description="Nodes to focus in the graph view.")
    highlight_path: list[str] = Field(description="Edge IDs of a path to highlight, in order.")


class Action(ApiModel):
    title: str
    type: ActionType
    viable: bool = Field(description="All supporting edges observed and active, no contradiction.")
    edge_ids: list[str]
    timeline_today: str | None = Field(description="Today's timeline for this milestone.")
    timeline_proposed: str | None = Field(description="Timeline with the proposed route.")
    assumptions: list[str]


class FollowUp(ApiModel):
    question: str
    quick_replies: list[str]
    skippable: bool = Field(description="Always true.")


ReplyKind = Literal["answer", "emergency", "declined"]


class AgentReply(ApiModel):
    """One structured agent turn (all fields required, nullable where noted)."""

    summary: str = Field(description="Plain-language answer, max 3 sentences.")
    uncertainty: str | None = Field(description="Null or one sentence.")
    chips: list[Chip]
    claims: list[Claim]
    contradictions: list[Contradiction]
    missing_evidence: list[str]
    cards: list[Card]
    graph_focus: GraphFocus | None
    actions: list[Action]
    follow_up: FollowUp | None
    gap_search: GapSearchRequest | None = Field(
        None,
        description="Set when no supported route exists: body for POST /gap-search to look for "
        "the missing evidence.",
    )
    ai_notice: str | None = Field(
        None, description="Always set by the server: the reply comes from an AI system."
    )
    kind: ReplyKind = Field(
        "answer",
        description="Set by the server: answer (default), emergency (call emergency services, "
        "no graph answer) or declined (part of the question crossed the medical boundary and "
        "was declined; graph context may still follow).",
    )


class ChatRequest(ApiModel):
    session_id: UUID | None = Field(None, description="Existing session; omit to start one.")
    message: str = Field(min_length=1, max_length=4000, description="The user's message.")
    expert_mode: bool | None = Field(None, description="Override the profile's expert mode.")


class ChatMessage(ApiModel):
    id: UUID
    session_id: UUID
    role: ChatRole
    content: str = Field(description="Redacted message text.")
    reply: AgentReply | None = Field(None, description="Structured reply (assistant only).")
    created_at: datetime


class ChatSession(ApiModel):
    id: UUID
    title: str | None = None
    created_at: datetime
    updated_at: datetime


class ChatSessionDetail(ApiModel):
    session: ChatSession
    messages: list[ChatMessage]
