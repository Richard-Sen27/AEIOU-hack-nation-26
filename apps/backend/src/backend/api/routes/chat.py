from uuid import UUID

from fastapi import APIRouter, Query, Request

from backend.api.deps import DB, HealthDataConsentUser, User, build_lens
from backend.api.errors import responses
from backend.api.ratelimit import limiter
from backend.api.services import chat
from backend.api.sse import EventStream, sse_doc, sse_response
from backend.schemas.chat import ChatRequest, ChatRun, ChatSession, ChatSessionDetail
from backend.schemas.events import ChatEvent

router = APIRouter(tags=["chat"])
CHAT_LIMIT = "30/minute;300/day"


@router.post(
    "/chat",
    response_class=EventStream,
    responses={
        **sse_doc(
            ChatEvent,
            "Stream of ChatEvent (status, turn, summary_delta, ..., final); each frame's SSE id "
            "is its sequence number in the run.",
        ),
        **responses(401, 403, 404, 409, 422, 429, 501),
    },
    operation_id="chat",
)
@limiter.limit(CHAT_LIMIT)
async def post_chat(
    request: Request, body: ChatRequest, user: HealthDataConsentUser
) -> EventStream:
    """Send a message to Dr. Wu (an AI system); streams the checked structured reply.

    The turn runs on the server and keeps running when this stream is closed; follow it again
    with streamChatRun. 409 when the session is still answering. Needs the health_data
    consent: the message may carry the user's health data."""
    lens = build_lens(user, expert_mode=body.expert_mode)
    return sse_response(await chat.start_turn(body, user, lens))


@router.get(
    "/chat/sessions",
    response_model=list[ChatSession],
    responses=responses(401, 501),
    operation_id="listChatSessions",
)
async def list_sessions(db: DB, user: User) -> list[ChatSession]:
    """The user's chat sessions."""
    return await chat.list_sessions(db, user)


@router.get(
    "/chat/sessions/{session_id}",
    response_model=ChatSessionDetail,
    responses=responses(401, 404, 501),
    operation_id="getChatSession",
)
async def get_session(session_id: UUID, db: DB, user: User) -> ChatSessionDetail:
    """One session with its messages."""
    return await chat.get_session(db, user, session_id)


@router.delete(
    "/chat/sessions/{session_id}",
    status_code=204,
    responses=responses(401, 404, 501),
    operation_id="deleteChatSession",
)
async def delete_session(session_id: UUID, db: DB, user: User) -> None:
    """Delete a session and its messages."""
    await chat.delete_session(db, user, session_id)


@router.get(
    "/chat/runs",
    response_model=list[ChatRun],
    responses=responses(401, 501),
    operation_id="listChatRuns",
)
async def list_runs(db: DB, user: User) -> list[ChatRun]:
    """The user's running Dr. Wu turns, newest first (at most one per session)."""
    return await chat.active_runs(db, user)


@router.get(
    "/chat/runs/{run_id}/events",
    response_class=EventStream,
    responses={
        **sse_doc(
            ChatEvent,
            "The run's ChatEvents with a sequence number above `after` (the SSE id), then live "
            "ones until final or error.",
        ),
        **responses(401, 404, 501),
    },
    operation_id="streamChatRun",
)
async def stream_run(
    run_id: UUID,
    user: User,
    after: int = Query(0, ge=0, description="Last sequence number already seen; 0 = all."),
) -> EventStream:
    """Attach to a running (or just finished) turn: replay, then follow. 404 once it is gone;
    the session then holds its reply or failed turn."""
    return sse_response(chat.attach_run(user, run_id, after))


@router.delete(
    "/chat/runs/{run_id}",
    status_code=204,
    responses=responses(401, 404, 501),
    operation_id="cancelChatRun",
)
async def cancel_run(run_id: UUID, user: User) -> None:
    """Stop a running turn. It is stored as an interrupted turn that can be tried again."""
    await chat.cancel_run(user, run_id)
