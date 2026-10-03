from uuid import UUID

from fastapi import APIRouter

from backend.api.deps import DB, ContributeConsentUser, User
from backend.api.errors import responses
from backend.api.services import contributions, feedback
from backend.schemas.contributions import Contribution, ContributionCreate, FlagCreate, FlagResult

router = APIRouter(tags=["contributions"])


@router.get(
    "/contributions",
    response_model=list[Contribution],
    responses=responses(401, 501),
    operation_id="listContributions",
)
async def list_contributions(db: DB, user: User) -> list[Contribution]:
    """The user's own contributions."""
    return await contributions.list_own(db, user)


@router.post(
    "/contributions",
    response_model=Contribution,
    status_code=201,
    responses=responses(401, 403, 422, 501),
    operation_id="createContribution",
)
async def create_contribution(
    body: ContributionCreate,
    db: DB,
    user: ContributeConsentUser,
) -> Contribution:
    """Contribute a patient-reported profile or asset (status pending_review)."""
    return await contributions.create(db, user, body)


@router.delete(
    "/contributions/{contribution_id}",
    status_code=204,
    responses=responses(401, 404, 501),
    operation_id="deleteContribution",
)
async def delete_contribution(contribution_id: UUID, db: DB, user: User) -> None:
    """Delete one of the user's contributions."""
    await contributions.delete(db, user, contribution_id)


@router.post(
    "/edges/{edge_id}/flag",
    response_model=FlagResult,
    status_code=201,
    responses=responses(401, 404, 409, 422, 501),
    operation_id="flagEdge",
)
async def flag_edge(edge_id: str, body: FlagCreate, db: DB, user: User) -> FlagResult:
    """Flag an edge; it is shown as under_review."""
    return await feedback.flag_edge(db, user, edge_id, body)
