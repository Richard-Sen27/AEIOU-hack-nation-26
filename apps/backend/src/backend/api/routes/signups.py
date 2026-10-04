"""Suggestions of calls and sign-ups to them (connect stage 4, `connect` consent).

Registered before the calls router so that /calls/suggested is not read as a call id.
"""

from uuid import UUID

from fastapi import APIRouter, Request

from backend.api.deps import DB, SignedInUser, User
from backend.api.errors import responses
from backend.api.ratelimit import limiter
from backend.api.services import signups, suggestions
from backend.schemas.signups import (
    MySignup,
    MySignupList,
    ReceivedSignup,
    ReceivedSignupList,
    SignupOptions,
    SignupRequest,
    SuggestionList,
    SuggestionSettings,
    SuggestionSettingsUpdate,
)

router = APIRouter()

SIGNUP_LIMIT = "20/day"
SUGGEST_LIMIT = "60/minute"

# Suggestions and signing up need the current `connect` consent (checked in the services, which
# answer 403 consent_required); suggestions also need the user's own switch. Listing, withdrawing
# and the publisher's view never need it: they stay available after a withdrawal.


@router.get(
    "/calls/suggested",
    response_model=SuggestionList,
    responses=responses(401, 403, 429),
    operation_id="listSuggestedCalls",
    tags=["calls"],
)
@limiter.limit(SUGGEST_LIMIT)
async def list_suggested_calls(request: Request, db: DB, user: User) -> SuggestionList:
    """Published calls that overlap my confirmed profile, with the reasons. Computed now in my
    own account and never stored; empty unless the connect consent is active and suggestions are
    switched on (see the flags)."""
    return await suggestions.suggested(db, user)


@router.get(
    "/me/connect/suggestions",
    response_model=SuggestionSettings,
    responses=responses(401, 403),
    operation_id="getSuggestionSettings",
    tags=["connect"],
)
async def get_suggestion_settings(db: DB, user: User) -> SuggestionSettings:
    """Whether suggestions are switched on (off by default)."""
    return await suggestions.get_settings(db, user)


@router.put(
    "/me/connect/suggestions",
    response_model=SuggestionSettings,
    responses=responses(401, 403, 422),
    operation_id="setSuggestionSettings",
    tags=["connect"],
)
async def set_suggestion_settings(
    body: SuggestionSettingsUpdate, db: DB, user: User
) -> SuggestionSettings:
    """Switch suggestions on (403 consent_required without the current connect consent) or off
    (deletes the suggestion notifications)."""
    return await suggestions.set_enabled(db, user, body.enabled)


@router.get(
    "/calls/{call_id}/signup",
    response_model=SignupOptions,
    responses=responses(401, 403, 404, 409),
    operation_id="getSignupOptions",
    tags=["calls"],
)
async def get_signup_options(call_id: UUID, db: DB, user: User) -> SignupOptions:
    """The sign-up screen for a published, open call: the items I may tick (only confirmed
    profile items the call asks for and targets; only a matching diagnosis pre-ticked), the
    authorization and guardian texts, and whether the consent or the age group must be asked
    first. The profile is read only while the connect consent is active."""
    return await signups.options(db, user, call_id)


@router.post(
    "/calls/{call_id}/signup",
    status_code=201,
    response_model=MySignup,
    responses=responses(401, 403, 404, 409, 422, 429),
    operation_id="signUpToCall",
    tags=["calls"],
)
@limiter.limit(SIGNUP_LIMIT)
async def sign_up_to_call(
    request: Request, call_id: UUID, body: SignupRequest, db: DB, user: User
) -> MySignup:
    """Send the ticked items to the call's publisher. 403 consent_required, age_group_required,
    guardian_agreement_required (16 or 17), forbidden (doctors and researchers, or a call for
    adults and a 16- or 17-year-old); 404 closed or unknown call; 409 expired, full, duplicate,
    declined before, own call, not open yet, or the publisher's card is hidden; 422 names the
    field (an item not offered, the authorization); 429 with open_conversation at 5 new
    conversations a day."""
    return await signups.sign_up(db, user, call_id, body)


@router.get(
    "/me/signups",
    response_model=MySignupList,
    responses=responses(401),
    operation_id="listMySignups",
    tags=["calls"],
)
async def list_my_signups(db: DB, user: SignedInUser) -> MySignupList:
    """My sign-ups, newest first, stubs included. Ones past their time are deleted first."""
    return await signups.list_mine(db, user)


@router.delete(
    "/me/signups/{signup_id}",
    status_code=204,
    responses=responses(401, 404),
    operation_id="withdrawSignup",
    tags=["calls"],
)
async def withdraw_signup(signup_id: UUID, db: DB, user: SignedInUser) -> None:
    """Withdraw a sign-up: the shared items and the note are deleted at once; the study team
    keeps a 'withdrew' stub for 30 days; its conversation closes. Idempotent."""
    await signups.withdraw(db, user, signup_id)


@router.get(
    "/me/calls/{call_id}/signups",
    response_model=ReceivedSignupList,
    responses=responses(401, 404),
    operation_id="listCallSignups",
    tags=["calls"],
)
async def list_call_signups(call_id: UUID, db: DB, user: SignedInUser) -> ReceivedSignupList:
    """The sign-ups to one of my calls: display name, the ticked items, the note, the status and
    the 16-17 label. Never an account id or e-mail; 404 unless it is my call."""
    return await signups.received(db, user, call_id)


@router.post(
    "/me/calls/{call_id}/signups/{signup_id}/decline",
    response_model=ReceivedSignup,
    responses=responses(401, 404, 409),
    operation_id="declineCallSignup",
    tags=["calls"],
)
async def decline_call_signup(
    call_id: UUID, signup_id: UUID, db: DB, user: SignedInUser
) -> ReceivedSignup:
    """Decline an active sign-up to my call: its items and note are deleted at once and a stub
    stays for 30 days. Idempotent for a declined one; 409 for a withdrawn or closed one."""
    return await signups.decline(db, user, call_id, signup_id)
