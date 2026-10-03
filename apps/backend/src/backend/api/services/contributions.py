"""Contributions: patient-reported profiles and assets, only with active contribute consent."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.schemas.account import CurrentUser
from backend.schemas.contributions import Contribution, ContributionCreate, SharedContribution


async def list_own(db: AsyncSession, user: CurrentUser) -> list[Contribution]:
    """The user's contributions."""
    raise NotImplementedError


async def create(db: AsyncSession, user: CurrentUser, body: ContributionCreate) -> Contribution:
    """Store a contribution (status pending_review) linked to the active consent."""
    raise NotImplementedError


async def delete(db: AsyncSession, user: CurrentUser, contribution_id: UUID) -> None:
    """Delete one of the user's contributions; 404 otherwise."""
    raise NotImplementedError


async def shared(db: AsyncSession) -> list[SharedContribution]:
    """Contributions visible to all, via shared_contributions() (no user IDs)."""
    raise NotImplementedError
