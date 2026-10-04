"""Calls: surveys, studies and trials looking for participants; the publisher's own calls."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request

from backend.api.deps import DB, SignedInUser, User
from backend.api.errors import responses
from backend.api.ratelimit import limiter
from backend.api.services import calls
from backend.schemas.calls import Call, CallInput, CallKind, CallList, OwnCall, OwnCallList

router = APIRouter(tags=["calls"])

CREATE_LIMIT = "20/day"
UPDATE_LIMIT = "60/hour"
SUBMIT_LIMIT = "10/day"
BROWSE_LIMIT = "120/minute"

# Browsing needs a signed-in 16+ account and no consent: the calls are published content and
# nothing about the reader is stored. Writing needs a verified doctor or researcher with a
# visible card (contract basis, publisher terms). Close, delete and the own list work without
# verification, so a publisher who lost it can still end and remove their calls.


@router.get(
    "/calls",
    response_model=CallList,
    responses=responses(401, 403, 422, 429),
    operation_id="listCalls",
)
@limiter.limit(BROWSE_LIMIT)
async def list_calls(
    request: Request,
    db: DB,
    user: User,
    kind: Annotated[CallKind | None, Query(description="Only this kind.")] = None,
) -> CallList:
    """Every published call that is still open, newest first, with its publisher's card. The
    list is the same for every user (filter by disease in the client: disease IDs are health
    data and stay out of URLs)."""
    return await calls.list_published(db, kind)


@router.get(
    "/calls/{call_id}",
    response_model=Call,
    responses=responses(401, 403, 404, 429),
    operation_id="getCall",
)
@limiter.limit(BROWSE_LIMIT)
async def get_call(request: Request, call_id: UUID, db: DB, user: User) -> Call:
    """One published, still open call. 404 for anything else (own drafts: GET /me/calls/{id})."""
    return await calls.get_published(db, call_id)


@router.get(
    "/me/calls",
    response_model=OwnCallList,
    responses=responses(401),
    operation_id="listMyCalls",
)
async def list_my_calls(db: DB, user: SignedInUser) -> OwnCallList:
    """The user's own calls in every status, and whether they may publish."""
    return await calls.list_own(db, user)


@router.get(
    "/me/calls/{call_id}",
    response_model=OwnCall,
    responses=responses(401, 404),
    operation_id="getMyCall",
)
async def get_my_call(call_id: UUID, db: DB, user: SignedInUser) -> OwnCall:
    """One of the user's own calls, with the review note and the wording check result."""
    return await calls.get_own(db, user, call_id)


@router.post(
    "/me/calls",
    response_model=OwnCall,
    status_code=201,
    responses=responses(401, 403, 409, 422, 429),
    operation_id="createCall",
)
@limiter.limit(CREATE_LIMIT)
async def create_call(request: Request, body: CallInput, db: DB, user: User) -> OwnCall:
    """Write a call as a draft. 403 unless the user is a verified doctor or researcher with a
    visible card; 409 at 10 draft, pending and published calls; 422 names the invalid field
    (atlas IDs must exist; studies and trials need `ethics_reference`, trials `registry_id`)."""
    return await calls.create(db, user, body)


@router.put(
    "/me/calls/{call_id}",
    response_model=OwnCall,
    responses=responses(401, 403, 404, 409, 422, 429),
    operation_id="updateCall",
)
@limiter.limit(UPDATE_LIMIT)
async def update_call(
    request: Request, call_id: UUID, body: CallInput, db: DB, user: User
) -> OwnCall:
    """Replace a draft, rejected or pending call; it becomes a draft and must be submitted again.
    409 for published, closed and withdrawn calls."""
    return await calls.update(db, user, call_id, body)


@router.post(
    "/me/calls/{call_id}/submit",
    response_model=OwnCall,
    responses=responses(401, 403, 404, 409, 422, 429),
    operation_id="submitCall",
)
@limiter.limit(SUBMIT_LIMIT)
async def submit_call(request: Request, call_id: UUID, db: DB, user: User) -> OwnCall:
    """Send the call to the Amber team for review (status pending_review). 422 when the wording
    check finds an offer, promise or price of a treatment (the message names field and rule) or
    an atlas ID has left the atlas."""
    return await calls.submit(db, user, call_id)


@router.post(
    "/me/calls/{call_id}/close",
    response_model=OwnCall,
    responses=responses(401, 404),
    operation_id="closeCall",
)
async def close_call(call_id: UUID, db: DB, user: SignedInUser) -> OwnCall:
    """End a published call (closed) or pull an unpublished one (withdrawn). Idempotent."""
    return await calls.close(db, user, call_id)


@router.delete(
    "/me/calls/{call_id}",
    status_code=204,
    responses=responses(401, 404),
    operation_id="deleteCall",
)
async def delete_call(call_id: UUID, db: DB, user: SignedInUser) -> None:
    """Delete one of the user's calls in any status, with its review log."""
    await calls.delete(db, user, call_id)
