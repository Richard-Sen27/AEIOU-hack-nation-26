from fastapi import APIRouter, Request

from backend.api.deps import DB, User
from backend.api.errors import responses
from backend.api.ratelimit import GAP_SEARCH_LIMIT, admit_model_request, hold_stream, limiter
from backend.api.services import gap_search
from backend.api.sse import EventStream, sse_doc, sse_response
from backend.schemas.events import GapSearchEvent
from backend.schemas.gap import GapSearchRequest

router = APIRouter(tags=["gap-search"])


@router.post(
    "/gap-search",
    response_class=EventStream,
    responses={
        **sse_doc(
            GapSearchEvent, "Stream of GapSearchEvent (progress..., candidate..., final | error)."
        ),
        **responses(401, 404, 422, 429, 501),
    },
    operation_id="gapSearch",
)
@limiter.limit(GAP_SEARCH_LIMIT)
async def post_gap_search(
    request: Request, body: GapSearchRequest, db: DB, user: User
) -> EventStream:
    """Agent progress and pending_review candidate edges for a missing link.

    Queries are built from the two nodes' public graph terms only, never from user data.
    """
    ticket = await admit_model_request(request, user.id)
    try:
        prepared = await gap_search.prepare(db, body, user)
    except BaseException:
        ticket.cancel()
        raise
    return sse_response(hold_stream(gap_search.run(body, user, prepared=prepared), ticket))
