"""Search: trigram on node_synonyms + vector on nodes.embedding + type/centrality boost."""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from backend.schemas.enums import NodeType
from backend.schemas.search import SearchResponse


async def search(
    db: AsyncSession,
    q: str,
    *,
    types: Sequence[NodeType] | None = None,
    limit: int = 10,
    expert: bool = False,
) -> SearchResponse:
    """Typed matches with the matched synonym; expert mechanism queries add ranked clusters."""
    raise NotImplementedError
