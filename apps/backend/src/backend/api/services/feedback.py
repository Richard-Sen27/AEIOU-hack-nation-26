"""Feedback: flag an edge; it shows as under_review while flags are open."""

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import ApiError, not_found
from backend.api.services.contributions import refresh_shared_graph, screen_free_text
from backend.schemas.account import CurrentUser
from backend.schemas.contributions import FlagCreate, FlagResult
from backend.schemas.enums import EdgeStatus, ErrorCode

MAX_REASON = 280


async def flag_edge(
    db: AsyncSession, user: CurrentUser, edge_id: str, body: FlagCreate
) -> FlagResult:
    """Record a flag (404 for unknown edges, 409 if this user already has an open flag)."""
    if len(edge_id) > 64 or not await db.scalar(
        text("SELECT EXISTS (SELECT 1 FROM edges WHERE id = :e)"), {"e": edge_id}
    ):
        raise not_found("Edge not found.")
    await screen_free_text(body.reason, "reason", max_length=MAX_REASON)
    try:
        async with db.begin_nested():
            await db.execute(
                text(
                    "INSERT INTO edge_flags (edge_id, user_id, reason, status)"
                    " VALUES (:e, :uid, :reason, 'open')"
                ),
                {"e": edge_id, "uid": user.id, "reason": body.reason.strip()},
            )
    except IntegrityError:
        raise ApiError(409, ErrorCode.conflict, "You already flagged this edge.") from None
    await refresh_shared_graph(db, flags=True)
    open_flags = await db.scalar(
        text("SELECT open_flags FROM edge_flag_counts() WHERE edge_id = :e"), {"e": edge_id}
    )
    return FlagResult(edge_id=edge_id, status=EdgeStatus.under_review, open_flags=open_flags or 1)
