"""Dr. Wu turns as server-side runs, detached from the request that started them.

A run is one turn graph (agent.run_graph) in an asyncio task. Its progress events get sequence
numbers (1, 2, ...) and are kept in process memory, so any client of the same user can attach,
replay from a sequence number and follow live; a client that goes away only ends its own
stream. The run's `chat_runs` row (with the latest checkpoint) exists while it runs and is
deleted in the transaction that stores the reply or the failed turn.

One API process holds the runs (see docs/homework.md for several instances). After a restart,
a row whose `worker` is not this process's boot id is an orphan: it is stored as an
`interrupted` failed turn (with the steps from its checkpoint, so "Try again" works) and its
row deleted, lazily, the next time its owner lists runs, opens the session or starts a turn.
Runs are not resumed: the user's model client, the tool cache and the turn deadline belong to
the process, and re-running model calls after a crash is not a safe replay.
"""

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import ApiError, not_found
from backend.api.services.chat.checkpoints import ChatRunSaver, load_state, run_config
from backend.db.session import user_transaction
from backend.schemas.chat import AgentReply, ChatRun, ChatRunExport, TurnFailure, TurnStep
from backend.schemas.enums import ErrorCode
from backend.schemas.events import ChatEvent

log = logging.getLogger(__name__)

BOOT_ID = uuid.uuid4().hex  # this API process; rows of other workers are orphans
RUN_KEEP_S = 60.0  # a finished run's events stay attachable this long, then are dropped
CANCEL_WAIT_S = 5.0
TITLE_CHARS = 60
INTERRUPTED = TurnFailure(
    code="interrupted", message="The answer was interrupted before it was complete.", steps=[]
)
BUSY = "Dr. Wu is still answering in this conversation."

saver = ChatRunSaver()
_runs: dict[UUID, "Run"] = {}
_tasks: set[asyncio.Task] = set()


@dataclass
class Run:
    id: UUID
    user_id: UUID
    session_id: UUID
    message_id: UUID
    created_at: datetime
    events: list[ChatEvent] = field(default_factory=list)
    steps: list[TurnStep] = field(default_factory=list)
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    done: bool = False
    discard: bool = False  # session/consent/account deleted: store nothing
    task: asyncio.Task | None = None

    def emit(self, event: ChatEvent) -> None:
        self.events.append(event)
        changed, self.changed = self.changed, asyncio.Event()
        changed.set()

    def finish(self) -> None:
        self.done = True
        self.changed.set()

    def summary(self) -> ChatRun:
        return ChatRun(
            id=self.id,
            session_id=self.session_id,
            message_id=self.message_id,
            created_at=self.created_at,
        )


def detach(coro: Awaitable) -> asyncio.Task:
    """A task that outlives the request that started it."""
    task = asyncio.ensure_future(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


# ---- storage ------------------------------------------------------------------------------


async def _touch(db: AsyncSession, session_id: UUID) -> None:
    await db.execute(
        text("UPDATE chat_sessions SET updated_at = now() WHERE id = :sid"), {"sid": session_id}
    )


async def _insert_failure(
    db: AsyncSession, user_id: UUID, session_id: UUID, failure: TurnFailure
) -> None:
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
    await _touch(db, session_id)


async def _end(db: AsyncSession, run_id: UUID) -> bool:
    """Delete the run's row (and so its checkpoint); False if it was already gone."""
    result = await db.execute(text("DELETE FROM chat_runs WHERE id = :rid"), {"rid": run_id})
    return result.rowcount > 0


async def store_reply(run: Run, reply: AgentReply) -> UUID:
    """Store the reply and end the run, in one transaction."""
    async with user_transaction(run.user_id) as db:
        message_id = await db.scalar(
            text(
                "INSERT INTO chat_messages (session_id, user_id, role, content, reply)"
                " VALUES (:sid, :uid, 'assistant', :content, CAST(:reply AS jsonb)) RETURNING id"
            ),
            {
                "sid": run.session_id,
                "uid": run.user_id,
                "content": reply.summary,
                "reply": reply.model_dump_json(),
            },
        )
        await _touch(db, run.session_id)
        await _end(db, run.id)
    return message_id


async def store_failure(run: Run, failure: TurnFailure) -> None:
    """Store the failed turn (its error and status steps) and end the run, in one
    transaction; nothing when the run's row is gone (session or account deleted)."""
    try:
        async with user_transaction(run.user_id) as db:
            if await _end(db, run.id):
                await _insert_failure(db, run.user_id, run.session_id, failure)
    except Exception as exc:  # noqa: BLE001 - the session may be gone meanwhile
        log.info("chat run failure not stored: %s", type(exc).__name__)


async def reconcile(db: AsyncSession, user_id: UUID, session_id: UUID | None = None) -> None:
    """Close the user's orphaned runs (their process is gone) as interrupted failed turns."""
    rows = (
        (
            await db.execute(
                text(
                    "SELECT id, session_id, checkpoint_type, checkpoint FROM chat_runs"
                    " WHERE user_id = :uid AND (CAST(:sid AS uuid) IS NULL OR session_id = :sid)"
                    " FOR UPDATE SKIP LOCKED"
                ),
                {"uid": user_id, "sid": session_id},
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        live = _runs.get(row["id"])
        if live is not None and not live.done:
            continue
        try:
            state = load_state(row["checkpoint_type"], row["checkpoint"]) or {}
        except Exception:  # noqa: BLE001 - an unreadable checkpoint only loses the steps
            state = {}
        steps = [TurnStep.model_validate(s) for s in state.get("steps") or []]
        await _end(db, row["id"])
        await _insert_failure(
            db, user_id, row["session_id"], INTERRUPTED.model_copy(update={"steps": steps})
        )


async def active_runs(db: AsyncSession, user_id: UUID) -> list[ChatRun]:
    """The user's running turns, newest first (orphans are closed first)."""
    await reconcile(db, user_id)
    runs = [r for r in _runs.values() if r.user_id == user_id and not r.done]
    return [r.summary() for r in sorted(runs, key=lambda r: r.created_at, reverse=True)]


async def session_run(db: AsyncSession, user_id: UUID, session_id: UUID) -> ChatRun | None:
    await reconcile(db, user_id, session_id)
    for r in _runs.values():
        if r.user_id == user_id and r.session_id == session_id and not r.done:
            return r.summary()
    return None


async def ensure_idle(db: AsyncSession, user_id: UUID, session_id: UUID) -> None:
    """409 when the session already has a running turn."""
    if await session_run(db, user_id, session_id) is not None:
        raise ApiError(409, ErrorCode.conflict, BUSY)


async def export(db: AsyncSession, user_id: UUID) -> list[ChatRunExport]:
    """The user's unfinished runs for the data export (Art. 15): usually none, since a run's
    row and checkpoint are deleted when its turn ends."""
    rows = (
        (
            await db.execute(
                text(
                    "SELECT id, session_id, user_message_id, created_at, updated_at,"
                    " checkpoint_type, checkpoint FROM chat_runs WHERE user_id = :uid"
                    " ORDER BY created_at, id"
                ),
                {"uid": user_id},
            )
        )
        .mappings()
        .all()
    )
    out = []
    for r in rows:
        try:
            state = load_state(r["checkpoint_type"], r["checkpoint"])
        except Exception:  # noqa: BLE001 - export the row even if its checkpoint is unreadable
            state = None
        out.append(
            ChatRunExport(
                id=r["id"],
                session_id=r["session_id"],
                message_id=r["user_message_id"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                state=state,
            )
        )
    return out


# ---- lifecycle ----------------------------------------------------------------------------


async def create(
    user_id: UUID,
    session_id: UUID | None,
    message: str,
    retry_of: UUID | None,
) -> Run:
    """Store the user's message (or drop the failed turns of a retried one) and the run's row in
    one transaction. 409 when the session already has a running turn."""
    try:
        async with user_transaction(user_id) as db:
            if retry_of is not None:
                assert session_id is not None
                message_id = retry_of
                await db.execute(
                    text(
                        "DELETE FROM chat_messages WHERE session_id = :sid AND user_id = :uid"
                        " AND role = 'assistant' AND reply -> 'error' IS NOT NULL"
                        " AND (created_at, id) > (SELECT created_at, id FROM chat_messages"
                        " WHERE id = :mid AND user_id = :uid)"
                    ),
                    {"sid": session_id, "uid": user_id, "mid": message_id},
                )
            else:
                if session_id is None:
                    session_id = await db.scalar(
                        text(
                            "INSERT INTO chat_sessions (user_id, title) VALUES (:uid, :title)"
                            " RETURNING id"
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
            await _touch(db, session_id)
            row = (
                await db.execute(
                    text(
                        "INSERT INTO chat_runs (user_id, session_id, user_message_id, worker)"
                        " VALUES (:uid, :sid, :mid, :worker) RETURNING id, created_at"
                    ),
                    {"uid": user_id, "sid": session_id, "mid": message_id, "worker": BOOT_ID},
                )
            ).one()
    except IntegrityError:
        raise ApiError(409, ErrorCode.conflict, BUSY) from None
    run = Run(
        id=row.id,
        user_id=user_id,
        session_id=session_id,
        message_id=message_id,
        created_at=row.created_at,
    )
    _runs[run.id] = run
    return run


_counts = {"started": 0, "finished": 0, "cancelled": 0, "failed": 0}


def running_count() -> int:
    return sum(1 for r in _runs.values() if not r.done)


def stats_text() -> str:
    return " ".join(f"chat_runs_{k}={v}" for k, v in _counts.items())


def start(
    run: Run,
    body: Callable[[Run], Awaitable[None]],
    on_end: Callable[[], None] | None = None,
) -> None:
    """Run `body` detached from the request; the run is closed and later dropped after it.
    `on_end` runs once when it ends however it ends (frees its model slot)."""

    async def _main() -> None:
        started = time.monotonic()
        outcome = "finished"
        _counts["started"] += 1
        log.info("chat run start running=%d", running_count())
        try:
            await body(run)
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except Exception:
            outcome = "failed"
            raise
        finally:
            run.finish()
            if on_end is not None:
                on_end()
            _counts[outcome] += 1
            log.info(
                "chat run end outcome=%s ms=%d running=%d",
                "discarded" if run.discard else outcome,
                round((time.monotonic() - started) * 1000),
                running_count(),
            )
            saver.forget(run.id)
            if run.discard:
                _runs.pop(run.id, None)
            else:
                asyncio.get_running_loop().call_later(RUN_KEEP_S, _runs.pop, run.id, None)

    run.task = detach(_main())


def get(user_id: UUID, run_id: UUID) -> Run:
    """The user's run (running, or finished less than RUN_KEEP_S ago); 404 otherwise."""
    run = _runs.get(run_id)
    if run is None or run.user_id != user_id:
        raise not_found("This answer is no longer running.")
    return run


async def follow(run: Run, after: int = 0) -> AsyncIterator[tuple[int, ChatEvent]]:
    """Events with sequence number > after, then live ones until the run ends. Leaving
    early (the client went away) does not affect the run."""
    index = max(0, after)
    while True:
        changed = run.changed
        while index < len(run.events):
            index += 1
            yield index, run.events[index - 1]
        if run.done:
            return
        await changed.wait()


async def _stop(run: Run) -> None:
    if run.task is not None and not run.task.done():
        run.task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await asyncio.wait_for(asyncio.shield(run.task), CANCEL_WAIT_S)


async def cancel(user_id: UUID, run_id: UUID) -> None:
    """Stop a running turn; it is stored as interrupted, like a cut stream used to be."""
    run = get(user_id, run_id)
    if run.done:
        return
    await _stop(run)


async def discard_session(user_id: UUID, session_id: UUID) -> None:
    """Before a session is deleted: stop its run, store nothing, drop its events."""
    for run in [r for r in _runs.values() if r.user_id == user_id and r.session_id == session_id]:
        run.discard = True
        _runs.pop(run.id, None)
        await _stop(run)


async def discard_user(user_id: UUID) -> None:
    """Before health data or the account is deleted: stop all the user's runs, store nothing,
    drop their events from memory."""
    for run in [r for r in _runs.values() if r.user_id == user_id]:
        run.discard = True
        _runs.pop(run.id, None)
        await _stop(run)


def config_for(run: Run) -> dict:
    return run_config(run.id, run.user_id)
