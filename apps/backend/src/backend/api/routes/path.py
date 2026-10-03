from typing import Annotated

from fastapi import APIRouter, Query

from backend.api.errors import responses
from backend.api.services import path
from backend.schemas.enums import PathFamily
from backend.schemas.path import PathResponse

router = APIRouter(tags=["graph"])


@router.get(
    "/path",
    response_model=PathResponse,
    responses=responses(404, 422, 501),
    operation_id="findPath",
)
async def find_path(
    from_id: Annotated[str, Query(alias="from", description="Start node ID.")],
    to_id: Annotated[str, Query(alias="to", description="End node ID.")],
    family: Annotated[PathFamily, Query()] = PathFamily.all,
    k: Annotated[int, Query(ge=1, le=10)] = 3,
    include_vus: Annotated[bool, Query(description="Allow VUS variants on paths.")] = False,
) -> PathResponse:
    """Ordered path steps, or no_supported_route with a coverage report."""
    return path.find_paths(from_id, to_id, family=family, k=k, include_vus=include_vus)
