from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from backend.api.deps import DB, User, require_consent
from backend.api.errors import responses
from backend.api.ratelimit import limiter
from backend.api.services import connect, messaging
from backend.schemas.account import CurrentUser
from backend.schemas.enums import ConsentType
from backend.schemas.messaging import (
    AgeGroupUpdate,
    BlockList,
    ConnectStatus,
    Message,
    MessageUnreadCount,
    OpenThreadRequest,
    Report,
    ReportRequest,
    SendMessageRequest,
    ThreadDetail,
    ThreadList,
)

router = APIRouter()

ConnectConsentUser = Annotated[CurrentUser, Depends(require_consent(ConsentType.connect))]
OPEN_LIMIT = "20/hour"  # on top of 5 new threads per day, enforced in the database
SEND_LIMIT = "120/hour"

# Starting, accepting, declining and sending need the `connect` consent (and an age group for
# starting and sending). Reading, hiding, deleting one's own messages, blocking and reporting
# never do: they stay available after a withdrawal, which closes every thread.


@router.get(
    "/me/connect",
    response_model=ConnectStatus,
    responses=responses(401, 403),
    operation_id="getConnectStatus",
    tags=["connect"],
)
async def get_connect_status(db: DB, user: User) -> ConnectStatus:
    """The connect consent state, the stated age group and the texts of the extra checkboxes."""
    return await connect.get_status(db, user)


@router.put(
    "/me/connect/age-group",
    response_model=ConnectStatus,
    responses=responses(401, 403, 422),
    operation_id="setConnectAgeGroup",
    tags=["connect"],
)
async def set_connect_age_group(
    body: AgeGroupUpdate, db: DB, user: ConnectConsentUser
) -> ConnectStatus:
    """State or correct the age group (needs the connect consent). Self-declared, not checked."""
    return await connect.set_age_group(db, user, body.age_group)


@router.get(
    "/me/threads",
    response_model=ThreadList,
    responses=responses(401, 403),
    operation_id="listThreads",
    tags=["messages"],
)
async def list_threads(db: DB, user: User) -> ThreadList:
    """My conversations with unread counts, most recent first. Hidden ones are left out until a
    new message arrives. Threads inactive for 12 months are deleted."""
    return await messaging.list_threads(db, user)


@router.post(
    "/me/threads",
    status_code=201,
    response_model=ThreadDetail,
    responses=responses(401, 403, 404, 409, 422, 429, 501),
    operation_id="openThread",
    tags=["messages"],
)
@limiter.limit(OPEN_LIMIT)
async def open_thread(
    request: Request, body: OpenThreadRequest, db: DB, user: ConnectConsentUser
) -> ThreadDetail:
    """Send a request (one message) to a professional's card. Patients and caregivers only; the
    card must be visible, verified and accept messages (404 otherwise). 403 age_group_required
    or guardian_agreement_required, 409 if a conversation with this person exists, 429 after 5
    new conversations in a day."""
    return await messaging.open_card_thread(db, user, body)


@router.get(
    "/me/threads/unread-count",
    response_model=MessageUnreadCount,
    responses=responses(401, 403),
    operation_id="getMessageUnreadCount",
    tags=["messages"],
)
async def get_message_unread_count(db: DB, user: User) -> MessageUnreadCount:
    """Unread messages and waiting requests, for the header. Cheap enough to poll."""
    return await messaging.unread_count(db, user)


@router.get(
    "/me/threads/{thread_id}",
    response_model=ThreadDetail,
    responses=responses(401, 403, 404),
    operation_id="getThread",
    tags=["messages"],
)
async def get_thread(thread_id: UUID, db: DB, user: User) -> ThreadDetail:
    """A conversation with all its messages, oldest first; marks it read."""
    return await messaging.get_thread(db, user, thread_id)


@router.post(
    "/me/threads/{thread_id}/accept",
    response_model=ThreadDetail,
    responses=responses(401, 403, 404, 409),
    operation_id="acceptThread",
    tags=["messages"],
)
async def accept_thread(thread_id: UUID, db: DB, user: ConnectConsentUser) -> ThreadDetail:
    """Accept a request addressed to me (409 if there is none)."""
    return await messaging.respond(db, user, thread_id, accept=True)


@router.post(
    "/me/threads/{thread_id}/decline",
    response_model=ThreadDetail,
    responses=responses(401, 403, 404, 409),
    operation_id="declineThread",
    tags=["messages"],
)
async def decline_thread(thread_id: UUID, db: DB, user: ConnectConsentUser) -> ThreadDetail:
    """Decline a request addressed to me (409 if there is none)."""
    return await messaging.respond(db, user, thread_id, accept=False)


@router.post(
    "/me/threads/{thread_id}/messages",
    status_code=201,
    response_model=Message,
    responses=responses(401, 403, 404, 409, 422, 429, 501),
    operation_id="sendMessage",
    tags=["messages"],
)
@limiter.limit(SEND_LIMIT)
async def send_message(
    request: Request, thread_id: UUID, body: SendMessageRequest, db: DB, user: ConnectConsentUser
) -> Message:
    """Send a plain-text message into an open conversation (409 when it is not open or a block
    exists). 403 age_group_required or guardian_agreement_required."""
    return await messaging.send_message(db, user, thread_id, body)


@router.delete(
    "/me/threads/{thread_id}/messages/{message_id}",
    status_code=204,
    responses=responses(401, 403, 404),
    operation_id="deleteMessage",
    tags=["messages"],
)
async def delete_message(thread_id: UUID, message_id: UUID, db: DB, user: User) -> None:
    """Delete my own message for both sides."""
    await messaging.delete_message(db, user, thread_id, message_id)


@router.post(
    "/me/threads/{thread_id}/hide",
    status_code=204,
    responses=responses(401, 403, 404),
    operation_id="hideThread",
    tags=["messages"],
)
async def hide_thread(thread_id: UUID, db: DB, user: User) -> None:
    """Hide a conversation from my list until a new message arrives."""
    await messaging.hide_thread(db, user, thread_id)


@router.post(
    "/me/threads/{thread_id}/block",
    status_code=204,
    responses=responses(401, 403, 404, 409),
    operation_id="blockThreadParticipant",
    tags=["messages"],
)
async def block_thread_participant(thread_id: UUID, db: DB, user: User) -> None:
    """Block the other person of this conversation: no messages or new conversations either
    way until unblocked."""
    await messaging.block(db, user, thread_id)


@router.post(
    "/me/threads/{thread_id}/report",
    status_code=201,
    response_model=Report,
    responses=responses(401, 403, 404, 422),
    operation_id="reportThread",
    tags=["messages"],
)
async def report_thread(thread_id: UUID, body: ReportRequest, db: DB, user: User) -> Report:
    """Report a conversation (optionally one message). This authorizes the Amber team to read
    the conversation; every access is logged."""
    return await messaging.report(db, user, thread_id, body)


@router.get(
    "/me/blocks",
    response_model=BlockList,
    responses=responses(401, 403),
    operation_id="listBlocks",
    tags=["messages"],
)
async def list_blocks(db: DB, user: User) -> BlockList:
    """The people I blocked."""
    return await messaging.list_blocks(db, user)


@router.delete(
    "/me/blocks/{block_id}",
    status_code=204,
    responses=responses(401, 403, 404),
    operation_id="unblock",
    tags=["messages"],
)
async def unblock(block_id: UUID, db: DB, user: User) -> None:
    """Lift a block; conversations it blocked reopen unless the other side blocked me too."""
    await messaging.unblock(db, user, block_id)
