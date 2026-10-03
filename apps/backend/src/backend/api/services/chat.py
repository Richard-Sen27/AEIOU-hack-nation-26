"""Chat orchestrator ("Dr. Wu"): see docs/specs/agent.md."""

from collections.abc import AsyncIterator
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.schemas.account import CurrentUser
from backend.schemas.chat import ChatRequest, ChatSession, ChatSessionDetail
from backend.schemas.common import Lens
from backend.schemas.events import ChatEvent


def run_turn(request: ChatRequest, user: CurrentUser, lens: Lens) -> AsyncIterator[ChatEvent]:
    """Run one agent turn and stream status, summary_delta, chips, claims, cards, ..., final.

    Raise ApiError before returning for request-level failures (e.g. unknown session).
    Use backend.db.session.user_transaction(user.id) for DB work, not the request session.
    """
    raise NotImplementedError


async def list_sessions(db: AsyncSession, user: CurrentUser) -> list[ChatSession]:
    """The user's chat sessions, newest first."""
    raise NotImplementedError


async def get_session(db: AsyncSession, user: CurrentUser, session_id: UUID) -> ChatSessionDetail:
    """One session with its messages; 404 if not the user's."""
    raise NotImplementedError


async def delete_session(db: AsyncSession, user: CurrentUser, session_id: UUID) -> None:
    """Delete a session and its messages; 404 if not the user's."""
    raise NotImplementedError
