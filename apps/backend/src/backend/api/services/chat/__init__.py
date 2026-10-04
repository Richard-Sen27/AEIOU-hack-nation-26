"""Chat orchestrator ("Dr. Wu"): see docs/specs/agent.md.

Turn order: redact the message -> emergency detection (no model call) -> store the message and
start a run (runs.py) -> the turn graph (agent.py: safety, entities, model/tool rounds,
post-checks, persist) on the user's ChatGPT plan -> events status, turn, uncertainty (if any),
summary deltas, chips, claims, cards, actions, follow_up, final. The run keeps going when the
client goes away; clients attach to it by run id. A turn that ends in an error is stored too
(its error and status steps, nothing else), so a reloaded session shows it; a retry replaces it
without storing the user's message again. Stored messages, checkpoints and traces hold
redacted text only."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import ApiError, not_found
from backend.api.services import auth as auth_service
from backend.api.services.chat import runs, safety
from backend.api.services.chat.agent import (
    TurnResult,
    profile_json,
    reply_language,
    run_graph,
)
from backend.api.services.chat.tools import STATUS_TEXT
from backend.api.services.explanation.common import chunk_text, llm_error, pick
from backend.db.session import user_transaction
from backend.llm import LLMClient, LLMError
from backend.observability import tracing
from backend.privacy.redaction import redact
from backend.schemas.account import CurrentUser
from backend.schemas.chat import (
    ChatMessage,
    ChatRequest,
    ChatRun,
    ChatSession,
    ChatSessionDetail,
    TurnFailure,
    TurnStep,
    stored_reply,
)
from backend.schemas.common import Lens
from backend.schemas.enums import ChatRole, ErrorCode, Role
from backend.schemas.events import (
    ChatActionsEvent,
    ChatCardsEvent,
    ChatChipsEvent,
    ChatClaimsEvent,
    ChatErrorEvent,
    ChatEvent,
    ChatFinalEvent,
    ChatFollowUpEvent,
    ChatStatusEvent,
    ChatSummaryDeltaEvent,
    ChatTurnEvent,
    ChatUncertaintyEvent,
)
from backend.schemas.profile import PatientProfile

__all__ = [
    "active_runs",
    "attach_run",
    "cancel_run",
    "delete_session",
    "get_session",
    "list_sessions",
    "message_from_row",
    "prepare_message",
    "run_turn",
    "start_turn",
    "traced_turn",
]

log = logging.getLogger(__name__)
INTERNAL = (ErrorCode.internal_error, "Something went wrong.")


@dataclass
class _Prepared:
    message: str  # redacted
    profile: PatientProfile
    profile_text: str  # redacted
    history: list[dict[str, str]]
    session_id: UUID | None
    emergency: bool
    llm: LLMClient | None
    retry_of: UUID | None = None  # stored user message whose failed turn is run again


# ---- sessions -----------------------------------------------------------------------------


def _session(row) -> ChatSession:
    return ChatSession(
        id=row["id"], title=row["title"], created_at=row["created_at"], updated_at=row["updated_at"]
    )


async def list_sessions(db: AsyncSession, user: CurrentUser) -> list[ChatSession]:
    """The user's chat sessions, newest first."""
    await runs.reconcile(db, user.id)
    rows = (
        (
            await db.execute(
                text(
                    "SELECT id, title, created_at, updated_at FROM chat_sessions"
                    " WHERE user_id = :uid ORDER BY updated_at DESC, created_at DESC"
                ),
                {"uid": user.id},
            )
        )
        .mappings()
        .all()
    )
    return [_session(r) for r in rows]


async def _messages(db: AsyncSession, user_id: UUID, session_id: UUID) -> list[ChatMessage]:
    rows = (
        (
            await db.execute(
                text(
                    "SELECT id, session_id, role, content, reply, created_at FROM chat_messages"
                    " WHERE session_id = :sid AND user_id = :uid ORDER BY created_at, id"
                ),
                {"sid": session_id, "uid": user_id},
            )
        )
        .mappings()
        .all()
    )
    return [message_from_row(r) for r in rows]


def message_from_row(r) -> ChatMessage:
    """A chat_messages row (id, session_id, role, content, reply, created_at) as ChatMessage;
    a stored failed turn becomes `error`. Also used by the data export."""
    try:
        reply, error = stored_reply(r["reply"])
    except ValueError:
        log.warning("stored chat reply failed validation; returned without it")
        reply, error = None, None
    return ChatMessage(
        id=r["id"],
        session_id=r["session_id"],
        role=ChatRole(r["role"]),
        content=r["content"],
        reply=reply,
        error=error,
        created_at=r["created_at"],
    )


async def _get_session_row(db: AsyncSession, user_id: UUID, session_id: UUID):
    row = (
        (
            await db.execute(
                text(
                    "SELECT id, title, created_at, updated_at FROM chat_sessions"
                    " WHERE id = :sid AND user_id = :uid"
                ),
                {"sid": session_id, "uid": user_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise not_found("Chat session not found.")
    return row


async def get_session(db: AsyncSession, user: CurrentUser, session_id: UUID) -> ChatSessionDetail:
    """One session with its messages and its running turn; 404 if not the user's."""
    row = await _get_session_row(db, user.id, session_id)
    run = await runs.session_run(db, user.id, row["id"])
    return ChatSessionDetail(
        session=_session(row), messages=await _messages(db, user.id, row["id"]), run=run
    )


async def delete_session(db: AsyncSession, user: CurrentUser, session_id: UUID) -> None:
    """Delete a session, its messages and its run (stopped first); 404 if not the user's."""
    await _get_session_row(db, user.id, session_id)
    await runs.discard_session(user.id, session_id)
    result = await db.execute(
        text("DELETE FROM chat_sessions WHERE id = :sid AND user_id = :uid"),
        {"sid": session_id, "uid": user.id},
    )
    if result.rowcount == 0:
        raise not_found("Chat session not found.")


# ---- turn ---------------------------------------------------------------------------------


def _history(messages: list[ChatMessage]) -> list[dict[str, str]]:
    items = []
    for m in messages:
        if m.role == ChatRole.user:
            items.append({"role": "user", "content": m.content})
        elif m.reply is not None:
            content = m.reply.summary
            if m.reply.follow_up is not None:
                content += "\n" + m.reply.follow_up.question
            items.append({"role": "assistant", "content": content})
    return items


def _profile_terms(profile: PatientProfile) -> list[str]:
    terms: list[str] = []
    for item in [*profile.diseases, *profile.genes, *profile.phenotypes]:
        terms += [item.id, item.label]
    for v in profile.variants:
        terms += [t for t in (v.hgvs, v.clinvar_id, v.gene_id) if t]
    return terms


async def _load_profile(db: AsyncSession, user_id: UUID) -> PatientProfile:
    raw = await db.scalar(
        text("SELECT profile FROM patient_profiles WHERE user_id = :uid"), {"uid": user_id}
    )
    if not raw:
        return PatientProfile()
    try:
        return PatientProfile.model_validate(raw)
    except ValueError:
        log.warning("stored patient profile failed validation; using an empty profile")
        return PatientProfile()


def _effective_lens(request: ChatRequest, lens: Lens) -> Lens:
    if request.expert_mode is None and lens.role == Role.researcher and not lens.expert_mode:
        return lens.model_copy(update={"expert_mode": True})
    return lens


def _retry_target(messages: list[ChatMessage], message_id: UUID) -> int:
    """Index of the user message to run again: the session's last user message, followed by
    nothing but failed turns. 404 if it is not in the session, 409 if it was answered."""
    index = next(
        (i for i, m in enumerate(messages) if m.id == message_id and m.role == ChatRole.user),
        None,
    )
    if index is None:
        raise not_found("Chat message not found.")
    if any(m.role == ChatRole.user or m.error is None for m in messages[index + 1 :]):
        raise ApiError(409, ErrorCode.conflict, "This message was already answered.")
    return index


async def _user_llm(user_id: UUID) -> LLMClient:
    """The user's client, with the model list fetched in the background meanwhile (it costs
    about 2 s when not cached, which the redaction running alongside hides)."""
    llm = await auth_service.llm_for_user(user_id)

    async def warm() -> None:
        with contextlib.suppress(Exception):
            await llm.resolve_model("small")
            await llm.resolve_model("main")

    runs.detach(warm())
    return llm


async def start_turn(
    request: ChatRequest,
    user: CurrentUser,
    lens: Lens,
    on_end: Callable[[], None] | None = None,
) -> AsyncIterator[tuple[int, ChatEvent]]:
    """Request-level checks (404 unknown session or message, 409 retry of an answered message
    or a session that is still answering, 401 no usable ChatGPT sign-in), redaction and
    emergency detection; stores the message, starts the run and returns its events with their
    sequence numbers. The run does not depend on the returned stream being read. `on_end` is
    called once when the run ends (not when this raises before the run starts)."""
    lens = _effective_lens(request, lens)
    if request.retry_message_id is not None and request.session_id is None:
        raise ApiError(422, ErrorCode.validation_error, "A retry needs its session_id.")
    raw = request.message
    async with user_transaction(user.id) as db:
        profile = await _load_profile(db, user.id)
        history: list[dict[str, str]] = []
        if request.session_id is not None:
            await _get_session_row(db, user.id, request.session_id)
            await runs.ensure_idle(db, user.id, request.session_id)
            messages = await _messages(db, user.id, request.session_id)
            if request.retry_message_id is not None:
                index = _retry_target(messages, request.retry_message_id)
                raw = messages[index].content  # the stored (redacted) text, not a new one
                messages = messages[:index]
            history = _history(messages)
    # Sign-in and model list run while the message is redacted; emergencies need neither.
    llm_task = asyncio.create_task(_user_llm(user.id))
    try:
        prepared = await prepare_message(raw, profile, history)
    except BaseException:
        llm_task.cancel()
        raise
    prepared.session_id = request.session_id
    prepared.retry_of = request.retry_message_id
    if prepared.emergency:
        llm_task.cancel()
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await llm_task
    else:
        prepared.llm = await llm_task
    run = await runs.create(user.id, prepared.session_id, prepared.message, prepared.retry_of)
    _open(run, prepared, lens)
    runs.start(run, lambda r: _execute(r, prepared, lens), on_end)
    return runs.follow(run, 0)


async def prepare_message(
    raw: str, profile: PatientProfile, history: list[dict[str, str]] | None = None
) -> _Prepared:
    """Redact the message and the profile (before any model call) and detect emergencies."""
    terms = _profile_terms(profile)
    message = (await asyncio.to_thread(redact, raw, allow_terms=terms)).text
    emergency = safety.is_emergency(message) or safety.is_emergency(raw)
    profile_text = profile_json(profile)
    if profile_text != "{}":
        profile_text = (await asyncio.to_thread(redact, profile_text, allow_terms=terms)).text
    return _Prepared(
        message=message,
        profile=profile,
        profile_text=profile_text,
        history=history or [],
        session_id=None,
        emergency=emergency,
        llm=None,
    )


def run_turn(request: ChatRequest, user: CurrentUser, lens: Lens) -> AsyncIterator[ChatEvent]:
    """Run one agent turn and stream status, summary_delta, chips, claims, cards, ..., final."""

    async def _gen() -> AsyncIterator[ChatEvent]:
        stream = await start_turn(request, user, lens)
        async for _, event in stream:
            yield event

    return _gen()


async def active_runs(db: AsyncSession, user: CurrentUser) -> list[ChatRun]:
    """The user's running turns, newest first."""
    return await runs.active_runs(db, user.id)


def attach_run(user: CurrentUser, run_id: UUID, after: int) -> AsyncIterator[tuple[int, ChatEvent]]:
    """Replay a run's events after sequence number `after`, then follow it; 404 if unknown."""
    return runs.follow(runs.get(user.id, run_id), after)


async def cancel_run(user: CurrentUser, run_id: UUID) -> None:
    """Stop a running turn; it is stored as interrupted."""
    await runs.cancel(user.id, run_id)


async def traced_turn(
    prepared: _Prepared,
    user_id: UUID | str,
    lens: Lens,
    session_id: UUID | str | None,
    on_status=None,
    **graph: Any,
) -> TurnResult:
    """The turn graph (emergency reply or agent turn) inside one `chat.turn` trace (redacted
    text only). `graph` passes persistence and checkpointing through to run_graph."""
    tracer = tracing.get_tracer()
    meta = {"role": lens.role.value, "expert_mode": lens.expert_mode, "language": lens.language}
    with tracer.trace(
        "chat.turn",
        user_id=str(user_id),
        session_id=str(session_id) if session_id else None,
        input=prepared.message,
        metadata=meta,
    ) as span:
        result = await run_graph(
            None if prepared.emergency else prepared.llm,
            message=prepared.message,
            lens=lens,
            profile=prepared.profile,
            profile_text=prepared.profile_text,
            history=prepared.history,
            emergency=prepared.emergency,
            on_status=on_status,
            tracer=tracer,
            **graph,
        )
        span.update(
            output=result.reply.model_dump(mode="json"),
            usage=result.usage,
            model=result.model,
            metadata={
                **meta,
                "emergency": result.emergency,
                "tool_calls": result.tool_calls,
                "tool_mode": result.tool_mode,
                "latency_ms": result.latency_ms,
                "cited_edge_ids": result.cited_edge_ids,
                "postcheck": result.checks.as_metadata() if result.checks else {},
                "boundary_asked": result.asked,
            },
        )
    return result


def _open(run: runs.Run, prepared: _Prepared, lens: Lens) -> None:
    """The run's first events: the start status and the stored turn (session, message, run)."""
    message = pick(STATUS_TEXT["start"], reply_language(prepared.message, lens))
    run.steps.append(TurnStep(tool=None, message=message))
    run.emit(ChatEvent(ChatStatusEvent(tool=None, message=message)))
    run.emit(
        ChatEvent(
            ChatTurnEvent(session_id=run.session_id, message_id=run.message_id, run_id=run.id)
        )
    )


async def _execute(run: runs.Run, prepared: _Prepared, lens: Lens) -> None:
    """The run's body: the turn graph, then the reply events, or the stored failed turn."""

    def status(tool: str | None, message: str) -> None:
        run.steps.append(TurnStep(tool=tool, message=message))
        run.emit(ChatEvent(ChatStatusEvent(tool=tool, message=message)))

    stored: list[UUID] = []

    async def persist(reply) -> UUID:
        stored.append(await runs.store_reply(run, reply))
        return stored[-1]

    try:
        result = await traced_turn(
            prepared,
            run.user_id,
            lens,
            run.session_id,
            status,
            persist=persist,
            checkpointer=runs.saver,
            config=runs.config_for(run),
            steps=[s.model_dump(mode="json") for s in run.steps],
        )
    except asyncio.CancelledError:
        if not run.discard:
            cut = runs.INTERRUPTED.model_copy(update={"steps": list(run.steps)})
            await asyncio.shield(runs.store_failure(run, cut))
        raise
    except LLMError as exc:
        code, message = llm_error(exc)
        log.info("chat turn failed: llm %s", exc.code)
    except Exception as exc:  # noqa: BLE001 - stored and shown like any failed turn
        code, message = INTERNAL
        log.error("chat turn failed: %s", type(exc).__name__)
    else:
        code = None
    if run.discard:
        return
    if code is not None:
        failure = TurnFailure(code=code.value, message=message, steps=list(run.steps))
        await runs.store_failure(run, failure)
        run.emit(ChatEvent(ChatErrorEvent(code=code, message=message)))
        return

    reply = result.reply
    message_id = stored[-1]
    if reply.uncertainty:
        run.emit(ChatEvent(ChatUncertaintyEvent(text=reply.uncertainty)))
    for chunk in chunk_text(reply.summary):
        run.emit(ChatEvent(ChatSummaryDeltaEvent(text=chunk)))
    run.emit(ChatEvent(ChatChipsEvent(chips=reply.chips)))
    run.emit(ChatEvent(ChatClaimsEvent(claims=reply.claims, contradictions=reply.contradictions)))
    run.emit(ChatEvent(ChatCardsEvent(cards=reply.cards)))
    run.emit(ChatEvent(ChatActionsEvent(actions=reply.actions)))
    if reply.follow_up is not None:
        run.emit(ChatEvent(ChatFollowUpEvent(follow_up=reply.follow_up)))
    run.emit(
        ChatEvent(ChatFinalEvent(reply=reply, session_id=run.session_id, message_id=message_id))
    )
