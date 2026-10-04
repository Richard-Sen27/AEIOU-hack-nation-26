from fastapi import APIRouter, Request
from fastapi.responses import Response

from backend.api.deps import DB, LensDep, OptionalUser
from backend.api.errors import responses
from backend.api.routes.graph import ATLAS_CACHE_CONTROL
from backend.api.services import atlas_summary, atlas_tree, people
from backend.schemas.atlas import AtlasSummary, AtlasTree

router = APIRouter(tags=["graph"])


@router.get(
    "/atlas/tree.json",
    response_model=AtlasTree,
    responses={304: {"description": "Not modified (If-None-Match matched the ETag)."}}
    | responses(501),
    operation_id="getAtlasTree",
)
async def get_atlas_tree(request: Request) -> Response:
    """Category trees around the hub with backend positions (ETag keyed on data and layout)."""
    # Served pre-compressed (gzip cached per data and layout version); a response that already
    # carries Content-Encoding is passed through by the GZip middleware.
    gzip_ok = "gzip" in request.headers.get("accept-encoding", "").lower()
    body, etag = atlas_tree.tree_payload_gzip() if gzip_ok else atlas_tree.tree_payload()
    headers = {"ETag": etag, "Cache-Control": ATLAS_CACHE_CONTROL, "Vary": "Accept-Encoding"}
    match = request.headers.get("if-none-match", "")
    if etag in [t.strip().removeprefix("W/") for t in match.split(",")]:
        return Response(status_code=304, headers=headers)
    if gzip_ok:
        headers["Content-Encoding"] = "gzip"
    return Response(body, media_type="application/json", headers=headers)


@router.get(
    "/atlas/summary/{node_id}",
    response_model=AtlasSummary,
    responses=responses(404, 501),
    operation_id="getAtlasSummary",
)
async def get_atlas_summary(
    node_id: str, lens: LensDep, db: DB, user: OptionalUser
) -> AtlasSummary:
    """A node's connections grouped into sections for the Atlas side panel. For signed-in users,
    researcher and doctor items carry `card_id` when the person has a visible, verified card."""
    summary = atlas_summary.atlas_summary(node_id, lens)
    if user is not None and user.age_confirmed:
        await people.attach_card_ids(db, summary)
    return summary
