from uuid import UUID

from fastapi import APIRouter

from backend.api.deps import DB, User, build_lens
from backend.api.errors import responses
from backend.api.services import chat
from backend.api.sse import EventStream, sse_doc, sse_response
from backend.schemas.chat import ChatRequest, ChatSession, ChatSessionDetail
from backend.schemas.events import ChatEvent

router = APIRouter(tags=["chat"])


@router.post(
    "/chat",
    response_class=EventStream,
    responses={
        **sse_doc(ChatEvent, "Stream of ChatEvent (status, summary_delta, ..., final)."),
        **responses(401, 404, 422, 429, 501),
    },
    operation_id="chat",
)
async def post_chat(body: ChatRequest, user: User) -> EventStream:
    """Send a message; streams the structured agent reply."""
    lens = build_lens(user, expert_mode=body.expert_mode)
    return sse_response(chat.run_turn(body, user, lens))


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
