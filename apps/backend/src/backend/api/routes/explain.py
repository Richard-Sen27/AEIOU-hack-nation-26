from collections.abc import AsyncIterator

from fastapi import APIRouter, Request

from backend.api.deps import DB, OptionalUser, build_lens, require_signed_in, require_user
from backend.api.errors import not_found, responses
from backend.api.ratelimit import EXPLAIN_LIMIT, admit_model_request, hold_stream
from backend.api.services import explanation, graph
from backend.api.services.explanation.common import chunk_text
from backend.api.sse import EventStream, sse_doc, sse_response
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
        **sse_doc(
            ExplainEvent,
            "Stream of ExplainEvent (delta..., final); with `steps: true` a new text is "
            "preceded by status events (status..., delta..., final).",
        ),
        **responses(401, 403, 404, 422, 429, 501),
    },
    operation_id="explainPath",
)
async def explain(
    request: Request, body: ExplainRequest, db: DB, user: OptionalUser
) -> EventStream:
    """Role-specific explanation with citation IDs. Cached: anyone; new: signed in.

    With `subject_node_id` the edges are that node's connections (the Atlas summary), not an
    ordered path; it has its own cache key. With `steps` a new text streams its progress
    (reading, writing, checking) first; the text is sent only after it passed the checks.
    A new text counts against the account's explanation and model limits (429)."""
    lens = build_lens(user, body.role, body.language)
    subject = body.subject_node_id
    if subject is not None and graph.get_node(subject) is None:
        raise not_found("Unknown subject node.")
    scope = {"subject_node_id": subject} if subject else {}
    cached = await explanation.get_cached(db, body.edge_ids, lens, **scope)
    if cached is not None:
        return sse_response(_replay(cached))
    await require_user(await require_signed_in(user))
    ticket = await admit_model_request(request, user.id, limit=EXPLAIN_LIMIT)
    try:
        stream = await explanation.start_generation(
            body.edge_ids, lens, user, steps=body.steps, **scope
        )
    except BaseException:
        ticket.cancel()
        raise
    return sse_response(hold_stream(stream, ticket))
