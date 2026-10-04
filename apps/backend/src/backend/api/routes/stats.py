from fastapi import APIRouter, Request
from fastapi.responses import Response

from backend.api.services import stats
from backend.schemas.stats import AtlasStats

router = APIRouter(tags=["graph"])

STATS_CACHE_CONTROL = "public, max-age=300"


@router.get(
    "/stats",
    response_model=AtlasStats,
    responses={304: {"description": "Not modified (If-None-Match matched the ETag)."}},
    operation_id="getStats",
)
async def get_stats(request: Request) -> Response:
    """Headline counts of the graph (computed once per data version, ETag on it)."""
    body, etag = stats.stats_payload()
    headers = {"ETag": etag, "Cache-Control": STATS_CACHE_CONTROL}
    match = request.headers.get("if-none-match", "")
    if etag in [t.strip().removeprefix("W/") for t in match.split(",")]:
        return Response(status_code=304, headers=headers)
    return Response(body, media_type="application/json", headers=headers)
