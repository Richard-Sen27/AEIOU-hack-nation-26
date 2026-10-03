"""Explanation: role-specific, cited path explanations, cached in explanations_cache."""

from collections.abc import AsyncIterator, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from backend.schemas.account import CurrentUser
from backend.schemas.common import Lens
from backend.schemas.events import ExplainEvent, ExplainFinalEvent


async def get_cached(
    db: AsyncSession, edge_ids: Sequence[str], lens: Lens
) -> ExplainFinalEvent | None:
    """Cached explanation for (path_id(edge_ids), role, language, data_version), or None."""
    raise NotImplementedError


def generate(edge_ids: Sequence[str], lens: Lens, user: CurrentUser) -> AsyncIterator[ExplainEvent]:
    """Stream a new explanation (delta..., final) on the user's plan; validates and caches it.

    Raise ApiError before returning for request-level failures (e.g. unknown edge IDs).
    Use backend.db.session.user_transaction for DB work, not the request session.
    """
    raise NotImplementedError
