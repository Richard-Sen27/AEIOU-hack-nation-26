"""LangGraph checkpoint saver over our own `chat_runs` table (see docs/retention.md).

Why not LangGraph's PostgresSaver: it creates its own tables keyed by thread without a user
column, so they would sit outside the per-user row-level security, the cascades from sessions
and users, the export and the retention rules the chat tables have, and it keeps every
checkpoint forever. This saver keeps the *latest* checkpoint of an unfinished run in that run's
`chat_runs` row, written inside the owner's RLS transaction:

- `aput` is an UPDATE of the run's row: a run whose row is gone (turn finished, session or
  account deleted, consent withdrawn) is never written again.
- No checkpoint metadata or config is stored; pending writes stay in process memory (they only
  matter for resuming inside one process).
- Graph state is JSON-only and holds redacted content only (see agent.TurnGraphState).
"""

from collections import defaultdict
from collections.abc import AsyncIterator, Sequence
from typing import Any
from uuid import UUID

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from sqlalchemy import text

from backend.db.session import user_transaction

__all__ = ["ChatRunSaver", "run_config", "load_state"]

_serde = JsonPlusSerializer()


def run_config(run_id: UUID, user_id: UUID) -> dict[str, Any]:
    """Graph config of one run: the run id is the LangGraph thread."""
    return {"configurable": {"thread_id": str(run_id), "user_id": str(user_id)}}


def load_state(checkpoint_type: str | None, blob: bytes | None) -> dict[str, Any] | None:
    """The graph state values of a stored checkpoint (internal channels left out)."""
    if not checkpoint_type or blob is None:
        return None
    checkpoint = _serde.loads_typed((checkpoint_type, bytes(blob)))
    values = checkpoint.get("channel_values") or {}
    return {k: v for k, v in values.items() if not k.startswith(("__", "branch:"))}


class ChatRunSaver(BaseCheckpointSaver):
    def __init__(self) -> None:
        super().__init__(serde=_serde)
        # (run_id, checkpoint_id) -> {(task_id, idx): (task_id, channel, value)}
        self._writes: dict[tuple[str, str], dict] = defaultdict(dict)

    @staticmethod
    def _ids(config: dict[str, Any]) -> tuple[str, str]:
        conf = config["configurable"]
        return conf["thread_id"], conf["user_id"]

    def forget(self, run_id: UUID | str) -> None:
        """Drop the in-memory pending writes of a finished run."""
        for key in [k for k in self._writes if k[0] == str(run_id)]:
            del self._writes[key]

    async def aget_tuple(self, config: dict[str, Any]) -> CheckpointTuple | None:
        run_id, user_id = self._ids(config)
        async with user_transaction(user_id) as db:
            row = (
                (
                    await db.execute(
                        text(
                            "SELECT checkpoint_id, checkpoint_type, checkpoint FROM chat_runs"
                            " WHERE id = :rid"
                        ),
                        {"rid": run_id},
                    )
                )
                .mappings()
                .first()
            )
        if row is None or row["checkpoint"] is None:
            return None
        wanted = get_checkpoint_id(config)
        if wanted and wanted != row["checkpoint_id"]:
            return None  # only the latest checkpoint is kept
        checkpoint = self.serde.loads_typed((row["checkpoint_type"], bytes(row["checkpoint"])))
        writes = self._writes.get((run_id, row["checkpoint_id"]), {})
        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": run_id,
                    "user_id": user_id,
                    "checkpoint_ns": "",
                    "checkpoint_id": row["checkpoint_id"],
                }
            },
            checkpoint=checkpoint,
            metadata={},
            parent_config=None,
            pending_writes=list(writes.values()),
        )

    async def alist(
        self,
        config: dict[str, Any] | None,
        *,
        filter: dict[str, Any] | None = None,
        before: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        if config is None:
            return
        found = await self.aget_tuple(config)
        if found is not None:
            yield found

    async def aput(
        self,
        config: dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> dict[str, Any]:
        run_id, user_id = self._ids(config)
        kind, blob = self.serde.dumps_typed(checkpoint)
        async with user_transaction(user_id) as db:
            await db.execute(
                text(
                    "UPDATE chat_runs SET checkpoint_id = :cid, checkpoint_type = :kind,"
                    " checkpoint = :blob, updated_at = now() WHERE id = :rid"
                ),
                {"cid": checkpoint["id"], "kind": kind, "blob": blob, "rid": run_id},
            )
        previous = config["configurable"].get("checkpoint_id")
        if previous:
            self._writes.pop((run_id, previous), None)
        return {
            "configurable": {
                "thread_id": run_id,
                "user_id": user_id,
                "checkpoint_ns": "",
                "checkpoint_id": checkpoint["id"],
            }
        }

    async def aput_writes(
        self,
        config: dict[str, Any],
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        run_id, _ = self._ids(config)
        checkpoint_id = config["configurable"].get("checkpoint_id") or ""
        bucket = self._writes[(run_id, checkpoint_id)]
        for idx, (channel, value) in enumerate(writes):
            bucket[(task_id, idx)] = (task_id, channel, value)

    async def adelete_thread(self, thread_id: str) -> None:
        self.forget(thread_id)  # the row itself is deleted with the turn's outcome
