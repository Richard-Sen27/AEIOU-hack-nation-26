"""Path: top-k weighted paths with edge cost -log(confidence)."""

from backend.schemas.enums import PathFamily
from backend.schemas.path import PathResponse


def find_paths(
    from_id: str,
    to_id: str,
    *,
    family: PathFamily = PathFamily.all,
    k: int = 3,
    include_vus: bool = False,
) -> PathResponse:
    """Top-k supported paths, or no_supported_route with a coverage report."""
    raise NotImplementedError
