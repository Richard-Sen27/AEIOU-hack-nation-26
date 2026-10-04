"""Verification and the opt-in public card of doctors and researchers; card lookups."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import RedirectResponse

from backend.api.deps import DB, OptionalUser, SignedInUser, User
from backend.api.errors import responses
from backend.api.ratelimit import limiter
from backend.api.services import people
from backend.schemas.people import (
    CardSettingsUpdate,
    MyCard,
    OrcidStart,
    OrcidStartRequest,
    PeopleList,
    PublicCard,
    VerificationRequestCreate,
)

router = APIRouter(tags=["people"])

CARD_LIMIT = "30/hour"
ORCID_START_LIMIT = "10/hour"
VERIFICATION_REQUEST_LIMIT = "3/day"
PEOPLE_LIMIT = "120/minute"
MONDO_PATTERN = r"^MONDO:\d{7}$"


@router.get(
    "/me/professional/card",
    response_model=MyCard,
    responses=responses(401),
    operation_id="getMyCard",
)
async def get_my_card(db: DB, user: SignedInUser) -> MyCard:
    """Own verification state, card settings and a preview of exactly what others would see."""
    return await people.get_my_card(db, user)


@router.put(
    "/me/professional/card",
    response_model=MyCard,
    responses=responses(401, 403, 409, 422, 429),
    operation_id="putMyCard",
)
@limiter.limit(CARD_LIMIT)
async def put_my_card(
    request: Request, body: CardSettingsUpdate, db: DB, user: SignedInUser
) -> MyCard:
    """Replace the card settings. `visible: true` needs a verified doctor or researcher with a
    name (403 role, 409 not verified or no name); `visible: false` always works and hides the
    card at once."""
    return await people.put_my_card(db, user, body)


@router.post(
    "/me/professional/orcid/start",
    response_model=OrcidStart,
    responses=responses(401, 403, 429, 501),
    operation_id="startOrcidConfirmation",
)
@limiter.limit(ORCID_START_LIMIT)
async def start_orcid_confirmation(
    request: Request, body: OrcidStartRequest, db: DB, user: SignedInUser
) -> OrcidStart:
    """URL of the ORCID sign-in (or the local simulated one) that confirms the user's ORCID iD.
    501 when ORCID sign-in is not configured. 403 unless doctor or researcher."""
    return await people.start_orcid(db, user, body)


@router.get(
    "/me/professional/orcid/callback",
    response_class=RedirectResponse,
    status_code=302,
    operation_id="orcidCallback",
)
async def orcid_callback(request: Request, db: DB, user: OptionalUser) -> Response:
    """ORCID redirect target. Redirects to the frontend path from the start call with
    ?orcid=confirmed|denied|failed|already_linked."""
    return await people.orcid_callback(request, db, user)


@router.post(
    "/me/professional/verification-request",
    response_model=MyCard,
    responses=responses(401, 403, 409, 422, 429),
    operation_id="requestVerification",
)
@limiter.limit(VERIFICATION_REQUEST_LIMIT)
async def request_verification(
    request: Request, body: VerificationRequestCreate, db: DB, user: SignedInUser
) -> MyCard:
    """Ask the Amber team for a manual check (institutional e-mail and a public profile page).
    Replaces an earlier request. 403 unless doctor or researcher; 409 if already verified."""
    return await people.request_verification(db, user, body)


@router.delete(
    "/me/professional/verification-request",
    status_code=204,
    responses=responses(401),
    operation_id="withdrawVerificationRequest",
)
async def withdraw_verification_request(db: DB, user: SignedInUser) -> None:
    """Withdraw a pending or rejected request (the e-mail and link are deleted)."""
    await people.withdraw_verification_request(db, user)


@router.get(
    "/people",
    response_model=PeopleList,
    responses=responses(401, 403, 404, 422, 429),
    operation_id="listPeople",
)
@limiter.limit(PEOPLE_LIMIT)
async def list_people(
    request: Request,
    db: DB,
    user: User,
    disease: Annotated[str, Query(pattern=MONDO_PATTERN, description="Atlas disease ID.")],
) -> PeopleList:
    """Visible, verified cards of doctors and researchers whose verified atlas entry is linked to
    the disease. Professionals only; patients are never listed."""
    return await people.list_people(db, disease)


@router.get(
    "/people/{card_id}",
    response_model=PublicCard,
    responses=responses(401, 403, 404, 429),
    operation_id="getPersonCard",
)
@limiter.limit(PEOPLE_LIMIT)
async def get_person_card(request: Request, card_id: UUID, db: DB, user: User) -> PublicCard:
    """One public card; 404 unless it is visible and verified right now."""
    return await people.get_card(db, card_id)
