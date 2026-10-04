"""Chat schemas. AgentReply mirrors the output contract in docs/specs/agent.md."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from backend.schemas.common import ApiModel
from backend.schemas.enums import (
    ActionType,
    AgeRange,
    CardType,
    ChatRole,
    ChipType,
    ConfidenceLevel,
    Origin,
)
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


class ProfileHints(ApiModel):
    """Age, onset and country from this turn's message: unconfirmed, like chips. The user
    confirms them before they reach the PatientProfile (same types as its fields)."""

    age_years: int | None = Field(None, ge=0, le=120, description="Age in years, if stated.")
    age_range: AgeRange | None = Field(None, description="Age range, if stated instead.")
    onset: str | None = Field(None, description="Disease onset: HPO onset term ID or label.")
    country: str | None = Field(
        None, pattern=r"^[A-Z]{2}$", description="ISO 3166-1 alpha-2 country, if stated."
    )
    about_child_suspected: bool = Field(
        False,
        description="The message seems to describe a child (age under 16 or a family relation "
        "such as 'my son'): ask whether it is about the user or a child they care for, and get "
        "the parental-responsibility confirmation, before saving chips or hints.",
    )


class SymptomMatchTerm(ApiModel):
    """One of the user's symptoms recorded for a condition, with the link that records it."""

    user_symptom: str = Field(description="The user's symptom as its HPO term label.")
    recorded_as: str = Field(description="The HPO term recorded for the condition.")
    match: Literal["same", "more_specific", "broader"] = Field(
        description="How the recorded term relates to the user's symptom."
    )
    edge_id: str = Field(description="The has_phenotype edge that records it (cite this).")


class SymptomMatchItem(ApiModel):
    """A condition in the atlas whose recorded symptoms overlap the user's."""

    id: str = Field(description="Disease node ID.")
    label: str
    overlap: int = Field(description="How many of the user's symptoms are recorded for it.")
    of: int = Field(description="How many symptoms the user described (resolved to HPO terms).")
    on_map: bool = Field(description="Drawn on the Atlas map (the focus set); else a node page.")
    shared: list[SymptomMatchTerm] = Field(description="The shared symptoms with their edges.")
    absent: list[SymptomMatchTerm] = Field(
        description="Symptoms recorded for it that the user said are absent, with their edges."
    )


class SymptomMatch(ApiModel):
    """The symptom-overlap ranking of a turn (match_phenotypes), built in code from the tool
    result: an overlap count per condition, never a probability or a diagnosis."""

    items: list[SymptomMatchItem] = Field(description="Conditions by overlap, best first.")


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
    kind: ReplyKind | None = Field(
        None,
        description="Always set by the server on new replies: answer, emergency (call emergency "
        "services, no graph answer) or declined (part of the question crossed the medical "
        "boundary and was declined; graph context may still follow). Null only on replies "
        "stored before this field existed.",
    )
    profile_hints: ProfileHints | None = Field(
        None,
        description="Unconfirmed age, onset and country extracted from this turn, and whether "
        "the message seems to be about a child. Null when nothing was found.",
    )
    symptom_match: SymptomMatch | None = Field(
        None,
        description="Conditions ranked by symptom overlap when match_phenotypes ran this turn "
        "(symptoms-only messages), built by the server from the tool result. Null otherwise and "
        "on replies stored before this field existed.",
    )


class ChatRequest(ApiModel):
    session_id: UUID | None = Field(None, description="Existing session; omit to start one.")
    message: str = Field(min_length=1, max_length=4000, description="The user's message.")
    expert_mode: bool | None = Field(None, description="Override the profile's expert mode.")
    retry_message_id: UUID | None = Field(
        None,
        description="Run the turn of this stored user message again (needs session_id; it must "
        "be the session's last user message, without an answer). No new user message is "
        "stored; the stored failed turn is replaced, and the stored text is used, not message.",
    )


class TurnStep(ApiModel):
    tool: str | None = Field(None, description="Tool of the status event, if any.")
    message: str = Field(description="The status text the stream showed.")


class TurnFailure(ApiModel):
    """A turn that ended without an answer, stored as the live stream showed it."""

    code: str = Field(
        description="The error event's code (an ErrorCode), or `interrupted` when the stream "
        "was cut before the turn ended."
    )
    message: str = Field(description="The error event's message. Never echoes user content.")
    steps: list[TurnStep] = Field(description="The status events the turn sent, in order.")


class ChatMessage(ApiModel):
    id: UUID
    session_id: UUID
    role: ChatRole
    content: str = Field(description="Redacted message text.")
    reply: AgentReply | None = Field(None, description="Structured reply (assistant only).")
    error: TurnFailure | None = Field(
        None, description="Set on an assistant message for a turn that failed (reply is null)."
    )
    created_at: datetime


def stored_reply(data: dict[str, Any] | None) -> tuple[AgentReply | None, TurnFailure | None]:
    """The `chat_messages.reply` column: an AgentReply, or {"error": TurnFailure} for a failed
    turn. Raises ValidationError when it is neither."""
    if not data:
        return None, None
    if set(data) == {"error"}:
        return None, TurnFailure.model_validate(data["error"])
    return AgentReply.model_validate(data), None


class ChatSession(ApiModel):
    id: UUID
    title: str | None = None
    created_at: datetime
    updated_at: datetime


class ChatRun(ApiModel):
    """A Dr. Wu turn still running on the server (it keeps running without a client)."""

    id: UUID
    session_id: UUID
    message_id: UUID = Field(description="The stored user message this run answers.")
    created_at: datetime


class ChatRunExport(ApiModel):
    """A turn that was still running at export time, with its latest checkpoint."""

    id: UUID
    session_id: UUID
    message_id: UUID
    created_at: datetime
    updated_at: datetime
    state: dict[str, Any] | None = Field(
        None,
        description="The turn's last saved state (redacted message, steps so far, draft or "
        "checked reply); null before the first step.",
    )


class ChatSessionDetail(ApiModel):
    session: ChatSession
    messages: list[ChatMessage]
    run: ChatRun | None = Field(
        None,
        description="The session's running turn, if any: follow it with streamChatRun (its "
        "events replay from the start, so the turn shows as far as it got).",
    )
