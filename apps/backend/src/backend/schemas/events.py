"""Server-sent event payloads, one discriminated union per stream.

Wire format: ``event: <type>`` + ``data: <json>``; the JSON repeats ``type``.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, RootModel

from backend.schemas.chat import Action, AgentReply, Card, Chip, Claim, Contradiction, FollowUp
from backend.schemas.common import ApiModel
from backend.schemas.enums import ErrorCode, GapStopReason, JobStage, Role
from backend.schemas.gap import CandidateEdge


class StreamError(ApiModel):
    code: ErrorCode = Field(description="Stable error code.")
    message: str = Field(description="Human-readable message. Never echoes user content.")


# --- chat --------------------------------------------------------------------------------


class ChatStatusEvent(ApiModel):
    type: Literal["status"] = "status"
    tool: str | None = Field(None, description="Tool currently running, e.g. find_path.")
    message: str = Field(description="Short progress text.")
    progress: float | None = Field(None, ge=0, le=1, description="Optional progress 0..1.")


class ChatUncertaintyEvent(ApiModel):
    type: Literal["uncertainty"] = "uncertainty"
    text: str = Field(description="One-line uncertainty statement; sent before the summary.")


class ChatSummaryDeltaEvent(ApiModel):
    type: Literal["summary_delta"] = "summary_delta"
    text: str = Field(description="Next chunk of the summary.")


class ChatChipsEvent(ApiModel):
    type: Literal["chips"] = "chips"
    chips: list[Chip]


class ChatClaimsEvent(ApiModel):
    type: Literal["claims"] = "claims"
    claims: list[Claim]
    contradictions: list[Contradiction] = Field(default_factory=list)


class ChatCardsEvent(ApiModel):
    type: Literal["cards"] = "cards"
    cards: list[Card]


class ChatActionsEvent(ApiModel):
    type: Literal["actions"] = "actions"
    actions: list[Action]


class ChatFollowUpEvent(ApiModel):
    type: Literal["follow_up"] = "follow_up"
    follow_up: FollowUp


class ChatFinalEvent(ApiModel):
    type: Literal["final"] = "final"
    reply: AgentReply
    session_id: UUID
    message_id: UUID


class ChatTurnEvent(ApiModel):
    type: Literal["turn"] = "turn"
    session_id: UUID = Field(description="Session of this turn (new or existing).")
    message_id: UUID = Field(
        description="The stored user message of this turn: send it as retry_message_id to run "
        "the turn again without storing the message twice."
    )
    run_id: UUID | None = Field(
        None,
        description="The server-side run of this turn: follow it again with streamChatRun "
        "(after a reload or from another view) or stop it with cancelChatRun.",
    )


class ChatErrorEvent(StreamError):
    type: Literal["error"] = "error"


class ChatEvent(
    RootModel[
        Annotated[
            ChatStatusEvent
            | ChatTurnEvent
            | ChatUncertaintyEvent
            | ChatSummaryDeltaEvent
            | ChatChipsEvent
            | ChatClaimsEvent
            | ChatCardsEvent
            | ChatActionsEvent
            | ChatFollowUpEvent
            | ChatFinalEvent
            | ChatErrorEvent,
            Field(discriminator="type"),
        ]
    ]
):
    """One event of the POST /chat stream."""


# --- explain -----------------------------------------------------------------------------

ExplainStep = Literal["reading", "writing", "checking", "fixing_sources", "simplifying"]


class ExplainStatusEvent(ApiModel):
    type: Literal["status"] = "status"
    step: ExplainStep = Field(
        description="reading the links, writing, checking the sources, rewriting to fix the "
        "sources, or rewriting in simpler words."
    )
    message: str = Field(description="Short progress text in the lens language.")


class ExplainDeltaEvent(ApiModel):
    type: Literal["delta"] = "delta"
    text: str


class ExplainFinalEvent(ApiModel):
    type: Literal["final"] = "final"
    path_id: str
    text: str = Field(description="Full explanation; citations appear inline as [e_...].")
    citations: list[str] = Field(description="Edge IDs cited; always a subset of the path.")
    cached: bool
    reading_grade: float | None = Field(None, description="Flesch-Kincaid grade of the text.")
    role: Role
    language: str
    data_version: str | None = None


class ExplainErrorEvent(StreamError):
    type: Literal["error"] = "error"


class ExplainEvent(
    RootModel[
        Annotated[
            ExplainStatusEvent | ExplainDeltaEvent | ExplainFinalEvent | ExplainErrorEvent,
            Field(discriminator="type"),
        ]
    ]
):
    """One event of the POST /explain stream. `status` events come only with `steps: true`,
    while a new text is written; the text itself is sent only after it passed the checks."""


# --- gap search --------------------------------------------------------------------------


class GapProgressEvent(ApiModel):
    type: Literal["progress"] = "progress"
    step: int = Field(description="Agent step number.")
    tool: str | None = Field(None, description="pubmed_search, clinicaltrials_search, ...")
    message: str
    elapsed_s: float = 0.0


class GapCandidateEvent(ApiModel):
    type: Literal["candidate"] = "candidate"
    candidate: CandidateEdge


class GapFinalEvent(ApiModel):
    type: Literal["final"] = "final"
    candidate_count: int
    stop_reason: GapStopReason
    job_id: UUID | None = Field(None, description="Job row that keeps the result for the user.")


class GapErrorEvent(StreamError):
    type: Literal["error"] = "error"


class GapSearchEvent(
    RootModel[
        Annotated[
            GapProgressEvent | GapCandidateEvent | GapFinalEvent | GapErrorEvent,
            Field(discriminator="type"),
        ]
    ]
):
    """One event of the POST /gap-search stream."""


# --- jobs --------------------------------------------------------------------------------


class JobProgressEvent(ApiModel):
    type: Literal["progress"] = "progress"
    job_id: UUID
    stage: JobStage
    percent: int = Field(ge=0, le=100)


class JobDoneEvent(ApiModel):
    type: Literal["done"] = "done"
    job_id: UUID
    document_id: UUID | None = None
    finding_count: int = 0


class JobErrorEvent(StreamError):
    type: Literal["error"] = "error"
    job_id: UUID | None = None


class JobEvent(
    RootModel[
        Annotated[
            JobProgressEvent | JobDoneEvent | JobErrorEvent,
            Field(discriminator="type"),
        ]
    ]
):
    """One event of the GET /jobs/{id} stream."""


AnyEvent = (
    ChatStatusEvent
    | ChatUncertaintyEvent
    | ChatSummaryDeltaEvent
    | ChatChipsEvent
    | ChatClaimsEvent
    | ChatCardsEvent
    | ChatActionsEvent
    | ChatFollowUpEvent
    | ChatFinalEvent
    | ChatErrorEvent
    | ExplainStatusEvent
    | ExplainDeltaEvent
    | ExplainFinalEvent
    | ExplainErrorEvent
    | GapProgressEvent
    | GapCandidateEvent
    | GapFinalEvent
    | GapErrorEvent
    | JobProgressEvent
    | JobDoneEvent
    | JobErrorEvent
)
