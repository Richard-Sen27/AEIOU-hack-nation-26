from pydantic import Field

from backend.schemas.common import ApiModel
from backend.schemas.enums import ConfidenceLevel, MatchKind, NodeType
from backend.schemas.graph import ClusterSummary


class SearchResult(ApiModel):
    id: str = Field(description="Node ID.")
    type: NodeType = Field(description="Node type.")
    label: str = Field(description="Canonical label of the node.")
    matched_synonym: str | None = Field(
        None, description="Synonym that matched, e.g. 'Ohtahara syndrome' for STXBP1 DEE."
    )
    score: float = Field(description="Combined ranking score (higher is better).")
    match_kind: MatchKind = Field(description="exact, trigram or vector.")
    cluster_id: str | None = Field(None, description="Cluster of the node, if any.")


class RankedCluster(ApiModel):
    cluster: ClusterSummary
    score: float = Field(description="Ranking score for the queried mechanism.")
    member_count: int = Field(description="Diseases in the cluster.")
    trial_count: int = Field(description="Trials linked to cluster members.")
    evidence_strength: float = Field(description="Mean confidence of supporting edges, 0..1.")
    evidence_level: ConfidenceLevel = Field(description="evidence_strength as High/Medium/Low.")
    matched_node_ids: list[str] = Field(
        default_factory=list, description="Nodes (mechanism, pathway, gene) that matched."
    )
    edge_ids: list[str] = Field(
        default_factory=list, description="Edges supporting the ranking, for citations."
    )


class SearchResponse(ApiModel):
    results: list[SearchResult]
    ranked_clusters: list[RankedCluster] = Field(
        default_factory=list, description="Expert mode mechanism queries only."
    )
    data_version: str | None = None
