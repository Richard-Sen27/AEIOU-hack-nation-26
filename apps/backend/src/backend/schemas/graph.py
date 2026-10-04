from datetime import datetime
from typing import Any

from pydantic import Field, model_validator

from backend.schemas.common import ApiModel
from backend.schemas.enums import (
    ClaimType,
    ConfidenceLevel,
    EdgeFamily,
    EdgeStatus,
    EvidenceTier,
    LabelStyle,
    NodeType,
    Origin,
    Polarity,
    Relation,
    StartLayout,
    VariantClassification,
)


class Node(ApiModel):
    id: str = Field(description="Stable node ID, e.g. MONDO:0100135, HGNC:11444, HP:0001250.")
    type: NodeType = Field(description="Node type.")
    label: str = Field(description="Display label.")
    description: str | None = Field(None, description="Short description from the source.")
    url: str | None = Field(None, description="Link to the authoritative source page.")
    attrs: dict[str, Any] = Field(
        default_factory=dict,
        description="Type-specific attributes (e.g. variant classification, registry kind).",
    )
    cluster_id: str | None = Field(None, description="Mechanism/phenotype cluster, if any.")
    x: float | None = Field(None, description="Precomputed layout x position.")
    y: float | None = Field(None, description="Precomputed layout y position.")
    centrality: float | None = Field(None, description="Precomputed centrality score (0..1).")


def feature_explanation(features: dict[str, Any] | None) -> str | None:
    """The one-line explanation an inferred edge carries in features.explanation, if any."""
    text = (features or {}).get("explanation")
    return (text.strip() or None) if isinstance(text, str) else None


class Edge(ApiModel):
    id: str = Field(description="Edge ID, 'e_' + 12 hex chars.")
    source_id: str = Field(description="Source node ID.")
    target_id: str = Field(description="Target node ID.")
    relation: Relation = Field(description="Relation type.")
    family: EdgeFamily = Field(description="Edge family: dna, symptoms, research, community.")
    confidence: float = Field(ge=0, le=1, description="Stage 4 confidence, 0..1.")
    confidence_level: ConfidenceLevel = Field(description="High >= 0.8, Medium >= 0.5, else Low.")
    origin: Origin = Field(description="observed (data) vs inferred (hypothesis) and others.")
    status: EdgeStatus = Field(
        description="active, pending_review, or under_review (open user flags)."
    )
    features: dict[str, Any] | None = Field(
        None, description="Features behind inferred edges (shared HPO terms, scores ...)."
    )
    data_version: str | None = Field(None, description="Graph data version.")
    evidence_count: int = Field(0, ge=0, description="Number of evidence rows.")
    contradiction_count: int = Field(0, ge=0, description="Evidence rows that contradict.")
    flagged: bool = Field(False, description="True when the edge has open user flags.")
    explanation: str | None = Field(
        None,
        description="One line on why an inferred (computed) link exists, from "
        "features.explanation. A hypothesis, never an established fact; null when absent.",
    )

    @model_validator(mode="after")
    def _explanation_from_features(self) -> "Edge":
        if self.explanation is None:
            self.explanation = feature_explanation(self.features)
        return self


class Evidence(ApiModel):
    id: int = Field(description="Evidence row ID.")
    edge_id: str = Field(description="Edge this evidence belongs to.")
    tier: EvidenceTier = Field(description="Evidence tier.")
    tier_weight: float = Field(description="Weight of the tier in the confidence formula.")
    source_type: str = Field(description="Source kind, e.g. ClinVar, PubMed, HPO, fixture.")
    source_id: str | None = Field(None, description="Source identifier (PMID, NCT, VCV ...).")
    url: str | None = Field(None, description="Link to the source.")
    quote: str | None = Field(None, description="Exact supporting span from the source.")
    retrieved_at: datetime | None = Field(None, description="When the source was retrieved.")
    polarity: Polarity = Field(description="Whether this item supports or contradicts the edge.")
    claim_type: ClaimType | None = Field(None, description="Kind of claim, for literature.")


class ConfidenceTerm(ApiModel):
    evidence_id: int = Field(description="Evidence row ID.")
    tier: EvidenceTier = Field(description="Evidence tier.")
    weight: float = Field(description="Tier weight w_i.")


class ConfidenceBreakdown(ApiModel):
    supporting: list[ConfidenceTerm] = Field(description="Supporting evidence terms.")
    support_score: float = Field(description="1 - prod(1 - w_i) over supporting evidence.")
    n_contradicting: int = Field(description="Number of contradicting evidence items.")
    penalty_per_contradiction: float = Field(description="Penalty p per contradiction.")
    penalty: float = Field(description="p * n_contradicting.")
    result: float = Field(description="Clamped confidence, 0..1.")
    level: ConfidenceLevel = Field(description="High / Medium / Low.")
    formula: str = Field(description="Human-readable formula with the numbers filled in.")


class EdgeEvidence(ApiModel):
    edge: Edge
    source: Node = Field(description="Source node of the edge.")
    target: Node = Field(description="Target node of the edge.")
    supporting: list[Evidence] = Field(description="Evidence with polarity 'supports'.")
    contradicting: list[Evidence] = Field(description="Evidence with polarity 'contradicts'.")
    confidence_breakdown: ConfidenceBreakdown
    open_flags: int = Field(0, description="Number of open user flags (no flagger identity).")


class ClusterSummary(ApiModel):
    id: str = Field(description="Cluster ID, e.g. CLUSTER:1.")
    label: str = Field(description="Cluster label (model-written, inferred).")
    mechanism_summary: str | None = Field(None, description="Shared mechanism, plain text.")
    member_count: int = Field(description="Number of member diseases.")
    focus_member_count: int = Field(
        0, description="Member diseases in the focus set (the ones drawn on the Atlas map)."
    )
    on_map: bool = Field(
        False, description="True when the cluster holds focus diseases and so is on the Atlas map."
    )
    attrs: dict[str, Any] = Field(
        default_factory=dict, description="Extra metadata (top genes, pathways, centroid ...)."
    )
    origin: Origin = Field(Origin.inferred, description="Cluster labels are always inferred.")


class RelationCount(ApiModel):
    relation: Relation
    family: EdgeFamily
    count: int = Field(description="Number of edges of this relation touching the node.")


class NodeDetail(ApiModel):
    node: Node
    synonyms: list[str] = Field(default_factory=list, description="Known name variants.")
    summary: str | None = Field(None, description="Short summary for the side panel.")
    relation_counts: list[RelationCount] = Field(
        default_factory=list, description="Edge counts by relation."
    )
    degree: int = Field(0, description="Total number of edges touching the node.")
    cluster: ClusterSummary | None = Field(
        None,
        description="The node's mechanism group: a disease's cluster of two or more members, or"
        " a cluster node itself. Other nodes have none.",
    )
    classification: VariantClassification | None = Field(
        None, description="For variants: the clinical classification."
    )
    vus_notice: str | None = Field(
        None, description="Standard VUS notice when classification is uncertain_significance."
    )


class LayoutHints(ApiModel):
    """Role presentation hints. They never hide anything."""

    start_layout: StartLayout = Field(description="Initial layout for the view.")
    label_style: LabelStyle = Field(description="plain, clinical or technical labels.")
    highlight_family: list[EdgeFamily] = Field(
        default_factory=list, description="Edge families highlighted first, in priority order."
    )
    highlight_node_types: list[NodeType] = Field(
        default_factory=list, description="Node types highlighted first."
    )
    show_ids: bool = Field(False, description="Show stable IDs next to labels.")
    reading_grade_target: float | None = Field(
        None, description="Target Flesch-Kincaid grade for text in this lens."
    )


class Neighborhood(ApiModel):
    center: Node
    nodes: list[Node] = Field(description="All nodes in the neighborhood, center included.")
    edges: list[Edge] = Field(description="All edges between the returned nodes.")
    cluster: ClusterSummary | None = Field(None, description="Cluster of the center node.")
    hints: LayoutHints
    data_version: str | None = Field(None, description="Graph data version.")


class AtlasNode(ApiModel):
    id: str
    type: NodeType
    label: str
    x: float | None = None
    y: float | None = None
    cluster_id: str | None = None
    centrality: float | None = None


class AtlasEdge(ApiModel):
    id: str
    source: str = Field(description="Source node ID.")
    target: str = Field(description="Target node ID.")
    relation: Relation
    family: EdgeFamily
    confidence: float
    origin: Origin
    status: EdgeStatus
    explanation: str | None = Field(
        None, description="Why an inferred link exists (one line, a hypothesis); null if absent."
    )


class AtlasLayout(ApiModel):
    """Compact whole-graph layout for the Atlas view."""

    nodes: list[AtlasNode]
    edges: list[AtlasEdge]
    clusters: list[ClusterSummary] = Field(default_factory=list)
    data_version: str | None = None
