from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from backend.api.deps import DB, User, build_lens
from backend.api.errors import responses
from backend.api.services import proposal
from backend.schemas.proposal import ProposalRequest

router = APIRouter(tags=["proposal"])


@router.post(
    "/proposal",
    response_class=HTMLResponse,
    responses={
        200: {"description": "One-page sourced proposal.", "content": {"text/html": {}}},
        **responses(401, 404, 422, 501),
    },
    operation_id="createProposal",
)
async def create_proposal(body: ProposalRequest, db: DB, user: User) -> HTMLResponse:
    """One-page sourced proposal as HTML (print to PDF)."""
    lens = build_lens(user, body.role, body.language)
    return HTMLResponse(await proposal.render_proposal(db, user, body, lens))
