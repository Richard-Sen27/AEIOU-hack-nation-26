from pydantic import Field

from backend.schemas.common import ApiModel
from backend.schemas.enums import CONFIDENCE_THRESHOLD, ConfidenceLevel, PathFamily, PathStatus
from backend.schemas.graph import Edge, Node


class PathStep(ApiModel):
    edge: Edge
    from_node: Node = Field(description="Node the step starts at (in traversal order).")
    to_node: Node = Field(description="Node the step ends at (in traversal order).")
    reversed: bool = Field(
        False, description="True when traversed against the stored edge direction."
    )


class Path(ApiModel):
    path_id: str = Field(description="path_id(edge_ids): 'p_' + 16 hex chars.")
    steps: list[PathStep]
    edge_ids: list[str] = Field(description="Edge IDs in traversal order.")
    total_cost: float = Field(description="Sum of -log(confidence) over the edges.")
    min_confidence: float = Field(description="Lowest edge confidence on the path.")
    min_confidence_level: ConfidenceLevel
    all_observed: bool = Field(description="Every edge has origin 'observed'.")
    all_active: bool = Field(description="Every edge has status 'active'.")
    supported: bool = Field(description="Every edge passes the confidence threshold.")


class SourceCount(ApiModel):
    source: str = Field(description="Source name, e.g. ClinVar, HPO, PubMed.")
    count: int = Field(description="Number of results the source contributed.")


class MissingLink(ApiModel):
    from_id: str
    to_id: str
    description: str = Field(description="What evidence is missing, in plain language.")


class CoverageReport(ApiModel):
    sources_queried: list[SourceCount] = Field(default_factory=list)
    closest_partial_path: Path | None = Field(
        None, description="Best path found, even though it is below the threshold."
    )
    missing_link: MissingLink | None = None
    suggested_question: str | None = Field(None, description="Suggested next question.")


class PathResponse(ApiModel):
    status: PathStatus
    from_id: str
    to_id: str
    family: PathFamily
    threshold: float = Field(CONFIDENCE_THRESHOLD, description="Confidence threshold used.")
    paths: list[Path] = Field(default_factory=list, description="Top-k supported paths.")
    coverage: CoverageReport | None = Field(
        None, description="Present when status is no_supported_route."
    )
