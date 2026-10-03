from uuid import UUID

from fastapi import APIRouter, Request

from backend.api.deps import DB, ContributeConsentUser, SignedInUser, User
from backend.api.errors import responses
from backend.api.ratelimit import limiter
from backend.api.services import contributions, feedback
from backend.schemas.contributions import Contribution, ContributionCreate, FlagCreate, FlagResult

router = APIRouter(tags=["contributions"])

CONTRIBUTION_LIMIT = "30/hour"
FLAG_LIMIT = "30/hour"


@router.get(
    "/contributions",
    response_model=list[Contribution],
    responses=responses(401),
    operation_id="listContributions",
)
async def list_contributions(db: DB, user: SignedInUser) -> list[Contribution]:
    """The user's own contributions."""
    return await contributions.list_own(db, user)


@router.post(
    "/contributions",
    response_model=Contribution,
    status_code=201,
    responses=responses(401, 403, 422, 429),
    operation_id="createContribution",
)
@limiter.limit(CONTRIBUTION_LIMIT)
async def create_contribution(
    request: Request,
    body: ContributionCreate,
    db: DB,
    user: ContributeConsentUser,
) -> Contribution:
    """Contribute a phenotype profile, an asset or a candidate edge (status pending_review)."""
    return await contributions.create(db, user, body)


@router.delete(
    "/contributions/{contribution_id}",
    status_code=204,
    responses=responses(401, 404),
    operation_id="deleteContribution",
)
async def delete_contribution(contribution_id: UUID, db: DB, user: SignedInUser) -> None:
    """Delete one of the user's contributions; it leaves the shared graph."""
    await contributions.delete(db, user, contribution_id)


@router.post(
    "/edges/{edge_id}/flag",
    response_model=FlagResult,
    status_code=201,
    responses=responses(401, 403, 404, 409, 422, 429),
    operation_id="flagEdge",
)
@limiter.limit(FLAG_LIMIT)
async def flag_edge(
    request: Request, edge_id: str, body: FlagCreate, db: DB, user: User
) -> FlagResult:
    """Flag an edge; it is shown as under_review for everyone while the flag is open."""
    return await feedback.flag_edge(db, user, edge_id, body)
