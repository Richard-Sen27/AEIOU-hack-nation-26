"""Chat orchestrator ("Dr. Wu"): see docs/specs/agent.md.

Turn order: redact the message -> emergency detection (no model call) -> tool loop on the
user's ChatGPT plan -> post-checks in code -> stream status, turn, uncertainty (if any),
summary deltas, chips, claims, cards, actions, follow_up, final. A turn that ends in an error
is stored too (its error and status steps, nothing else), so a reloaded session shows it; a
retry replaces it without storing the user's message again. Stored messages and traces hold
redacted text only."""

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import ApiError, not_found
from backend.api.services import auth as auth_service
from backend.api.services.chat import safety
from backend.api.services.chat.agent import (
    TurnResult,
    emergency_result,
    profile_json,
    reply_language,
    run_agent,
)
from backend.api.services.chat.tools import STATUS_TEXT
from backend.api.services.explanation.common import chunk_text, llm_error, pick
from backend.db.session import user_transaction
from backend.llm import LLMClient, LLMError
from backend.observability import tracing
from backend.privacy.redaction import redact
from backend.schemas.account import CurrentUser
from backend.schemas.chat import (
    AgentReply,
    ChatMessage,
    ChatRequest,
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
TITLE_CHARS = 60
INTERRUPTED = TurnFailure(
    code="interrupted", message="The answer was interrupted before it was complete.", steps=[]
)
INTERNAL = (ErrorCode.internal_error, "Something went wrong.")
# Tasks that must outlive the request that started them (model prefetch, saving a cut turn).
_background: set[asyncio.Task] = set()


def _detach(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)
    return task


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
    """One session with its messages; 404 if not the user's."""
    row = await _get_session_row(db, user.id, session_id)
    return ChatSessionDetail(
        session=_session(row), messages=await _messages(db, user.id, row["id"])
    )


async def delete_session(db: AsyncSession, user: CurrentUser, session_id: UUID) -> None:
    """Delete a session and its messages; 404 if not the user's."""
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

    _detach(warm())
    return llm


async def start_turn(
    request: ChatRequest, user: CurrentUser, lens: Lens
) -> AsyncIterator[ChatEvent]:
    """Request-level checks (404 unknown session or message, 409 retry of an answered message,
    401 no usable ChatGPT sign-in), redaction and emergency detection; returns the stream."""
    lens = _effective_lens(request, lens)
    if request.retry_message_id is not None and request.session_id is None:
        raise ApiError(422, ErrorCode.validation_error, "A retry needs its session_id.")
    raw = request.message
    async with user_transaction(user.id) as db:
        profile = await _load_profile(db, user.id)
        history: list[dict[str, str]] = []
        if request.session_id is not None:
            await _get_session_row(db, user.id, request.session_id)
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
    return _stream(prepared, user, lens)


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
        async for event in stream:
            yield event

    return _gen()


async def _save_user_message(
    user_id: UUID, session_id: UUID | None, message: str
) -> tuple[UUID, UUID]:
    """Store the user's message (and a new session); returns (session_id, message_id)."""
    async with user_transaction(user_id) as db:
        if session_id is None:
            session_id = await db.scalar(
                text(
                    "INSERT INTO chat_sessions (user_id, title) VALUES (:uid, :title) RETURNING id"
                ),
                {"uid": user_id, "title": message[:TITLE_CHARS]},
            )
        message_id = await db.scalar(
            text(
                "INSERT INTO chat_messages (session_id, user_id, role, content)"
                " VALUES (:sid, :uid, 'user', :content) RETURNING id"
            ),
            {"sid": session_id, "uid": user_id, "content": message},
        )
        await db.execute(
            text("UPDATE chat_sessions SET updated_at = now() WHERE id = :sid"), {"sid": session_id}
        )
    return session_id, message_id


async def _start_retry(user_id: UUID, session_id: UUID, message_id: UUID) -> None:
    """Drop the failed turn(s) stored after the retried user message."""
    async with user_transaction(user_id) as db:
        await db.execute(
            text(
                "DELETE FROM chat_messages WHERE session_id = :sid AND user_id = :uid"
                " AND role = 'assistant' AND reply -> 'error' IS NOT NULL AND (created_at, id) >"
                " (SELECT created_at, id FROM chat_messages WHERE id = :mid AND user_id = :uid)"
            ),
            {"sid": session_id, "uid": user_id, "mid": message_id},
        )
        await db.execute(
            text("UPDATE chat_sessions SET updated_at = now() WHERE id = :sid"), {"sid": session_id}
        )


async def _save_failure(user_id: UUID, session_id: UUID, failure: TurnFailure) -> None:
    """Store a failed turn as an assistant message: its error and status steps only."""
    async with user_transaction(user_id) as db:
        await db.execute(
            text(
                "INSERT INTO chat_messages (session_id, user_id, role, content, reply)"
                " VALUES (:sid, :uid, 'assistant', :content, CAST(:reply AS jsonb))"
            ),
            {
                "sid": session_id,
                "uid": user_id,
                "content": failure.message,
                "reply": json.dumps({"error": failure.model_dump(mode="json")}),
            },
        )
        await db.execute(
            text("UPDATE chat_sessions SET updated_at = now() WHERE id = :sid"), {"sid": session_id}
        )


async def _save_reply(user_id: UUID, session_id: UUID, reply: AgentReply) -> UUID:
    async with user_transaction(user_id) as db:
        message_id = await db.scalar(
            text(
                "INSERT INTO chat_messages (session_id, user_id, role, content, reply)"
                " VALUES (:sid, :uid, 'assistant', :content, CAST(:reply AS jsonb)) RETURNING id"
            ),
            {
                "sid": session_id,
                "uid": user_id,
                "content": reply.summary,
                "reply": reply.model_dump_json(),
            },
        )
        await db.execute(
            text("UPDATE chat_sessions SET updated_at = now() WHERE id = :sid"), {"sid": session_id}
        )
    return message_id


async def traced_turn(
    prepared: _Prepared,
    user_id: UUID | str,
    lens: Lens,
    session_id: UUID | str | None,
    on_status=None,
) -> TurnResult:
    """Emergency reply or agent turn inside one `chat.turn` trace (redacted text only)."""
    tracer = tracing.get_tracer()
    meta = {"role": lens.role.value, "expert_mode": lens.expert_mode, "language": lens.language}
    with tracer.trace(
        "chat.turn",
        user_id=str(user_id),
        session_id=str(session_id) if session_id else None,
        input=prepared.message,
        metadata=meta,
    ) as span:
        if prepared.emergency:
            result = emergency_result(prepared.message, lens)
        else:
            assert prepared.llm is not None
            result = await run_agent(
                prepared.llm,
                message=prepared.message,
                lens=lens,
                profile=prepared.profile,
                profile_text=prepared.profile_text,
                history=prepared.history,
                on_status=on_status,
                tracer=tracer,
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


async def _stream(prepared: _Prepared, user: CurrentUser, lens: Lens) -> AsyncIterator[ChatEvent]:
    language = reply_language(prepared.message, lens)
    steps: list[TurnStep] = []

    def status(tool: str | None, message: str) -> ChatEvent:
        steps.append(TurnStep(tool=tool, message=message))
        return ChatEvent(ChatStatusEvent(tool=tool, message=message))

    yield status(None, pick(STATUS_TEXT["start"], language))
    if prepared.retry_of is not None:
        assert prepared.session_id is not None
        session_id, user_message_id = prepared.session_id, prepared.retry_of
        await _start_retry(user.id, session_id, user_message_id)
    else:
        session_id, user_message_id = await _save_user_message(
            user.id, prepared.session_id, prepared.message
        )
    yield ChatEvent(ChatTurnEvent(session_id=session_id, message_id=user_message_id))

    stored = False  # an assistant row (reply or failure) exists for this turn
    queue: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(
        traced_turn(
            prepared, user.id, lens, session_id, lambda tool, msg: queue.put_nowait((tool, msg))
        )
    )
    try:
        while True:
            getter = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({task, getter}, return_when=asyncio.FIRST_COMPLETED)
            if getter in done:
                tool, msg = getter.result()
                yield status(tool, msg)
                continue
            getter.cancel()
            while not queue.empty():
                tool, msg = queue.get_nowait()
                yield status(tool, msg)
            break
        try:
            result = task.result()
        except LLMError as exc:
            code, message = llm_error(exc)
            log.info("chat turn failed: llm %s", exc.code)
        except Exception as exc:  # noqa: BLE001 - stored and shown like any failed turn
            code, message = INTERNAL
            log.error("chat turn failed: %s", type(exc).__name__)
        else:
            code = None
        if code is not None:
            failure = TurnFailure(code=code.value, message=message, steps=steps)
            await _save_failure(user.id, session_id, failure)
            stored = True
            yield ChatEvent(ChatErrorEvent(code=code, message=message))
            return
        reply = result.reply
        message_id = await _save_reply(user.id, session_id, reply)
        stored = True
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if not stored:
            # The stream was cut (client gone): keep the turn, outside the cancelled request.
            cut = INTERRUPTED.model_copy(update={"steps": list(steps)})
            _detach(_save_failure(user.id, session_id, cut))

    if reply.uncertainty:
        yield ChatEvent(ChatUncertaintyEvent(text=reply.uncertainty))
    for chunk in chunk_text(reply.summary):
        yield ChatEvent(ChatSummaryDeltaEvent(text=chunk))
    yield ChatEvent(ChatChipsEvent(chips=reply.chips))
    yield ChatEvent(ChatClaimsEvent(claims=reply.claims, contradictions=reply.contradictions))
    yield ChatEvent(ChatCardsEvent(cards=reply.cards))
    yield ChatEvent(ChatActionsEvent(actions=reply.actions))
    if reply.follow_up is not None:
        yield ChatEvent(ChatFollowUpEvent(follow_up=reply.follow_up))
    yield ChatEvent(ChatFinalEvent(reply=reply, session_id=session_id, message_id=message_id))
