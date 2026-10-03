"""Feedback: flag an edge; it shows as under_review while flags are open."""

from sqlalchemy.ext.asyncio import AsyncSession

from backend.schemas.account import CurrentUser
from backend.schemas.contributions import FlagCreate, FlagResult


async def flag_edge(
    db: AsyncSession, user: CurrentUser, edge_id: str, body: FlagCreate
) -> FlagResult:
    """Record a flag (404 for unknown edges) and refresh the in-memory flag overlay."""
    raise NotImplementedError
