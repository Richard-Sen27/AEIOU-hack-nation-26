"""Atlas summary panel: a node's connections grouped into sections (deterministic, no LLM).

Minimal version: the 1-hop neighbourhood (plus the node's cluster, and a cluster's members).
"""

from collections import Counter
from dataclasses import dataclass, field

from backend.api.errors import not_found
from backend.api.services import atlas_tree, graph
from backend.schemas.atlas import (
    AtlasSummary,
    SummaryItem,
    SummarySection,
    SummarySectionKey,
    TreePathItem,
)
from backend.schemas.common import Lens
from backend.schemas.enums import VUS_NOTICE, NodeType, Origin
from backend.schemas.graph import Edge, Node

MAX_ITEMS = 10
MAX_EXPLAIN_EDGES = 20

SECTION_TYPES: dict[SummarySectionKey, NodeType] = {
    SummarySectionKey.clusters: NodeType.cluster,
    SummarySectionKey.diseases: NodeType.disease,
    SummarySectionKey.similar_diseases: NodeType.disease,
    SummarySectionKey.genes: NodeType.gene,
    SummarySectionKey.variants: NodeType.variant,
    SummarySectionKey.mechanisms: NodeType.mechanism,
    SummarySectionKey.pathways: NodeType.pathway,
    SummarySectionKey.symptoms: NodeType.phenotype,
    SummarySectionKey.researchers: NodeType.researcher,
    SummarySectionKey.doctors: NodeType.doctor,
    SummarySectionKey.institutions: NodeType.institution,
    SummarySectionKey.papers: NodeType.paper,
    SummarySectionKey.trials: NodeType.trial,
    SummarySectionKey.grants: NodeType.grant,
    SummarySectionKey.patient_orgs: NodeType.patient_org,
    SummarySectionKey.registries: NodeType.registry,
    SummarySectionKey.networks: NodeType.network,
}
_TYPE_SECTION: dict[NodeType, SummarySectionKey] = {
    t: k for k, t in SECTION_TYPES.items() if k != SummarySectionKey.similar_diseases
}


def section_for(subject: Node, other: Node) -> SummarySectionKey | None:
    """Section of a neighbour; None for types without a section (claims)."""
    if subject.type == NodeType.disease and other.type == NodeType.disease:
        return SummarySectionKey.similar_diseases
    return _TYPE_SECTION.get(other.type)


@dataclass
class _Candidate:
    node: Node
    edges: list[Edge] = field(default_factory=list)

    def item(self, store: graph.GraphStore) -> SummaryItem:
        best = max(self.edges, key=lambda e: (e.confidence, e.id), default=None)
        return SummaryItem(
            id=self.node.id,
            label=self.node.label,
            type=self.node.type,
            hops=1,
            score=max(len(self.edges), 1),
            best_confidence=best.confidence if best else 0.0,
            inferred=bool(best and best.origin != Origin.observed),
            under_review=bool(best and not graph.edge_is_active(store, best)),
            via=[best.id] if best else [],
            via_label=None,
        )


def _rank(item: SummaryItem) -> tuple[int, float, str, str]:
    return (-item.score, -item.best_confidence, item.label.casefold(), item.id)


def atlas_summary(node_id: str, lens: Lens) -> AtlasSummary:
    """Connections of an entity grouped into sections; 404 for unknown and ``T:`` ids."""
    if node_id.startswith("T:"):
        raise not_found()
    store = graph.get_graph()
    node = graph.get_node(node_id)
    if node is None:
        raise not_found()

    candidates: dict[str, _Candidate] = {}
    neighbor_types: Counter[NodeType] = Counter()
    for edge in graph._incident_edges(store, node.id):
        other_id = graph._other(edge, node.id)
        other = graph.get_node(other_id)
        if other is None or other_id == node.id:
            continue
        if other_id not in candidates:
            candidates[other_id] = _Candidate(other)
            neighbor_types[other.type] += 1
        candidates[other_id].edges.append(edge)
    extra = list(store.members.get(node.id, ())) if node.type == NodeType.cluster else []
    if node.cluster_id and node.cluster_id != node.id:
        extra.append(node.cluster_id)
    for other_id in extra:
        if other_id not in candidates and other_id != node.id:
            other = graph.get_node(other_id)
            if other is not None:
                candidates[other_id] = _Candidate(other)

    grouped: dict[SummarySectionKey, list[SummaryItem]] = {}
    for cand in candidates.values():
        key = section_for(node, cand.node)
        if key is not None:
            grouped.setdefault(key, []).append(cand.item(store))
    sections = [
        SummarySection(
            key=key,
            node_type=SECTION_TYPES[key],
            total=len(grouped[key]),
            items=sorted(grouped[key], key=_rank)[:MAX_ITEMS],
        )
        for key in SummarySectionKey
        if grouped.get(key)
    ]

    explain: list[str] = []
    for rank in range(MAX_ITEMS):
        for section in sections:
            if rank < len(section.items):
                for eid in section.items[rank].via:
                    if eid not in explain and len(explain) < MAX_EXPLAIN_EDGES:
                        explain.append(eid)

    return AtlasSummary(
        node=node,
        tree_path=[
            TreePathItem(id=a.id, label=a.label, kind=a.kind) for a in atlas_tree.ancestors(node.id)
        ],
        headline=graph._summary(store, node, neighbor_types, lens.role),
        sections=sections,
        explain_edge_ids=explain,
        vus_notice=VUS_NOTICE if graph.is_vus(node) else None,
        data_version=store.data_version,
    )
