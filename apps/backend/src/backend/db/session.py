"""Async engine and RLS-aware transactions.

Every unit of DB work runs in a transaction that starts with
``SELECT set_config('app.user_id', :uid, true)`` (empty for guests), so row-level
security scopes user tables to that user for exactly that transaction.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None

SET_USER_SQL = text("SELECT set_config('app.user_id', :uid, true)")


def configure_engine(url: str | None = None, **kwargs) -> AsyncEngine:
    """(Re)create the global engine; called by the app factory and tests."""
    global _engine, _sessionmaker
    _engine = create_async_engine(url or get_settings().database_url, pool_pre_ping=True, **kwargs)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_engine() -> AsyncEngine:
    return _engine or configure_engine()


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        configure_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def set_user(session: AsyncSession, user_id: UUID | str | None) -> None:
    """Scope the session's current transaction to user_id (None = guest)."""
    await session.execute(SET_USER_SQL, {"uid": str(user_id) if user_id else ""})


@asynccontextmanager
async def user_transaction(user_id: UUID | str | None) -> AsyncIterator[AsyncSession]:
    """One short transaction scoped to user_id; commits on success, rolls back on error.

    Use in SSE handlers and background jobs instead of holding a request transaction
    open for the life of a stream.
    """
    async with get_sessionmaker()() as session, session.begin():
        await set_user(session, user_id)
        yield session


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: request-scoped transaction, guest-scoped until a user is set."""
    async with get_sessionmaker()() as session, session.begin():
        await set_user(session, None)
        yield session
