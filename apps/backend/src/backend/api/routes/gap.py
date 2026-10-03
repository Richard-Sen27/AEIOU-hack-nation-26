from fastapi import APIRouter, Request

from backend.api.deps import User
from backend.api.errors import responses
from backend.api.ratelimit import GAP_SEARCH_LIMIT, limiter
from backend.api.services import gap_search
from backend.api.sse import EventStream, sse_doc, sse_response
from backend.schemas.events import GapSearchEvent
from backend.schemas.gap import GapSearchRequest

router = APIRouter(tags=["gap-search"])


@router.post(
    "/gap-search",
    response_class=EventStream,
    responses={
        **sse_doc(GapSearchEvent, "Stream of GapSearchEvent (progress, candidate..., final)."),
        **responses(401, 404, 422, 429, 501),
    },
    operation_id="gapSearch",
)
@limiter.limit(GAP_SEARCH_LIMIT)
async def post_gap_search(request: Request, body: GapSearchRequest, user: User) -> EventStream:
    """Agent progress and pending_review candidate edges for a missing link."""
    return sse_response(gap_search.run(body, user))
