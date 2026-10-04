"""Atlas tree (logo hub with one radial tree per category) and the per-node summary panel."""

from enum import StrEnum

from backend.schemas.common import ApiModel
from backend.schemas.enums import NodeType
from backend.schemas.graph import AtlasEdge, ClusterSummary, Node


class AtlasCategory(StrEnum):
    researchers = "researchers"
    institutions = "institutions"
    literature = "literature"
    community = "community"
    pathways = "pathways"
    genes = "genes"
    diseases = "diseases"
    symptoms = "symptoms"
    doctors = "doctors"


class TreeNodeKind(StrEnum):
    root = "root"
    category = "category"
    group = "group"
    entity = "entity"


class GroupBasis(StrEnum):
    subcategory = "subcategory"
    mechanism_cluster = "mechanism_cluster"
    research_field = "research_field"
    focus_gene = "focus_gene"
    hpo_class = "hpo_class"
    chromosome = "chromosome"
    pathway_source = "pathway_source"
    institution_kind = "institution_kind"
    country = "country"
    year_band = "year_band"
    trial_status = "trial_status"
    agency = "agency"
    activity_code = "activity_code"
    registry_kind = "registry_kind"
    alpha_range = "alpha_range"
    not_recorded = "not_recorded"
    contributed = "contributed"


class AtlasTreeNode(ApiModel):
    id: str  # entity id, or "T:root" / "T:<category>/<seg>/..." for groups
    kind: TreeNodeKind
    label: str
    parent_id: str | None  # None only for the root
    category: AtlasCategory | None  # None only for the root
    depth: int  # root 0, category 1
    x: float
    y: float
    angle: float  # radians, polar angle (label orientation)
    entity_type: NodeType | None  # set iff kind == entity
    group_basis: GroupBasis | None  # set iff kind == group
    ref_id: str | None  # group: stored id/value it stands for; None for alpha_range
    entity_count: int  # entities in subtree, self included
    child_count: int
    cluster_id: str | None
    centrality: float | None
    contributed: bool = False


class AtlasCategorySummary(ApiModel):
    id: AtlasCategory
    node_id: str  # "T:<category>"
    label: str  # neutral English; frontend rewords per lens
    entity_count: int
    angle_start: float  # radians
    angle_end: float
    label_x: float
    label_y: float


class AtlasTree(ApiModel):
    data_version: str | None
    layout_version: int  # bump when the algorithm changes (part of the ETag)
    root_id: str  # "T:root"
    categories: list[AtlasCategorySummary]  # angular order
    nodes: list[AtlasTreeNode]  # pre-order: parents before children
    edges: list[AtlasEdge]  # all real edges (incl. overlay)
    clusters: list[ClusterSummary]


class TreePathItem(ApiModel):
    id: str
    label: str
    kind: TreeNodeKind


class SummarySectionKey(StrEnum):
    clusters = "clusters"
    diseases = "diseases"
    similar_diseases = "similar_diseases"
    genes = "genes"
    variants = "variants"
    mechanisms = "mechanisms"
    pathways = "pathways"
    symptoms = "symptoms"
    researchers = "researchers"
    doctors = "doctors"
    institutions = "institutions"
    papers = "papers"
    trials = "trials"
    grants = "grants"
    patient_orgs = "patient_orgs"
    registries = "registries"
    networks = "networks"
    claims = "claims"


class SummaryItem(ApiModel):
    id: str
    label: str
    type: NodeType
    hops: int  # 1..3
    score: int  # distinct supporting chains
    best_confidence: float  # min confidence along the best chain
    inferred: bool  # any edge of the best chain has origin != observed
    under_review: bool  # any edge of the best chain not active / flagged
    via: list[str]  # edge ids of the best chain, subject outward
    via_label: str | None  # e.g. "via 4 papers", "via gene SCN1A"
    # Why the link exists, when the best chain is a single inferred edge carrying one.
    explanation: str | None = None


class SummarySection(ApiModel):
    key: SummarySectionKey
    node_type: NodeType
    total: int
    items: list[SummaryItem]  # top 10


class AtlasSummary(ApiModel):
    node: Node
    tree_path: list[TreePathItem]  # root .. parent
    headline: str  # reuse graph._summary
    sections: list[SummarySection]  # fixed order of SummarySectionKey, empty ones omitted
    explain_edge_ids: list[str]  # <= 20, ordered: best chain of top items, sections in order
    vus_notice: str | None
    data_version: str | None
