from collections.abc import AsyncIterator

from fastapi import APIRouter

from backend.api.deps import DB, OptionalUser, build_lens
from backend.api.errors import ApiError, responses
from backend.api.services import explanation
from backend.api.services.explanation.common import chunk_text
from backend.api.sse import EventStream, sse_doc, sse_response
from backend.schemas.enums import ErrorCode
from backend.schemas.events import ExplainDeltaEvent, ExplainEvent, ExplainFinalEvent
from backend.schemas.explain import ExplainRequest

router = APIRouter(tags=["explain"])


async def _replay(cached: ExplainFinalEvent) -> AsyncIterator[ExplainEvent]:
    for chunk in chunk_text(cached.text, words=6):
        yield ExplainEvent(ExplainDeltaEvent(text=chunk))
    yield ExplainEvent(cached)


@router.post(
    "/explain",
    response_class=EventStream,
    responses={
        **sse_doc(ExplainEvent, "Stream of ExplainEvent (delta..., final)."),
        **responses(401, 404, 422, 429, 501),
    },
    operation_id="explainPath",
)
async def explain(body: ExplainRequest, db: DB, user: OptionalUser) -> EventStream:
    """Role-specific explanation with citation IDs. Cached: anyone; new: signed in."""
    lens = build_lens(user, body.role, body.language)
    cached = await explanation.get_cached(db, body.edge_ids, lens)
    if cached is not None:
        return sse_response(_replay(cached))
    if user is None:
        raise ApiError(401, ErrorCode.sign_in_required)
    return sse_response(await explanation.start_generation(body.edge_ids, lens, user))
