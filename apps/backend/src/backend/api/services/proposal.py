"""Proposal export: one-page sourced proposal as printable HTML."""

from sqlalchemy.ext.asyncio import AsyncSession

from backend.schemas.account import CurrentUser
from backend.schemas.common import Lens
from backend.schemas.proposal import ProposalRequest


async def render_proposal(
    db: AsyncSession, user: CurrentUser, request: ProposalRequest, lens: Lens
) -> str:
    """Render the proposal (path, assets, contacts, citations) as a standalone HTML page."""
    raise NotImplementedError
