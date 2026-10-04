"""Atlas summary panel: a node's connections grouped into sections (deterministic, no LLM).

The 1-hop neighbourhood plus fixed chains of up to 3 hops per subject type (researchers of a
disease via its papers, institutions via its people, ...). Runs on every node click, so it reads
the in-memory store only.
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
from backend.schemas.enums import VUS_NOTICE, NodeType, Origin, Relation
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
    SummarySectionKey.claims: NodeType.claim,
}
_TYPE_SECTION: dict[NodeType, SummarySectionKey] = {
    t: k for k, t in SECTION_TYPES.items() if k != SummarySectionKey.similar_diseases
}

# Cluster membership is a stored attribute, not an edge (plan section I point 3).
CLUSTER_OF_LABEL = "grouped in this cluster by the atlas, not a direct link"
MEMBER_LABEL = "member of this cluster, grouped by the atlas"
TOP_GENE_LABEL = "a top gene of this cluster, grouped by the atlas"

_NOUNS: dict[NodeType, tuple[str, str]] = {
    NodeType.paper: ("paper", "papers"),
    NodeType.grant: ("grant", "grants"),
    NodeType.trial: ("trial", "trials"),
    NodeType.gene: ("gene", "genes"),
    NodeType.disease: ("condition", "conditions"),
    NodeType.researcher: ("researcher", "researchers"),
    NodeType.doctor: ("doctor", "doctors"),
    NodeType.registry: ("registry", "registries"),
    NodeType.patient_org: ("patient group", "patient groups"),
}


def _short(label: str, limit: int = 48) -> str:
    return label if len(label) <= limit else label[: limit - 1].rstrip() + "…"


# Nodes with long titles are counted ("via 4 papers"); others are named ("via gene SCN1A").
_TITLE_NOUNS = frozenset({NodeType.paper, NodeType.grant, NodeType.trial})


@dataclass(frozen=True)
class Step:
    relation: Relation
    types: frozenset[NodeType]


def _s(relation: Relation, *types: NodeType) -> Step:
    return Step(relation, frozenset(types))


@dataclass(frozen=True)
class Chain:
    """A walk from the subject: one (relation, next node type) per hop. `label_hop` is the
    intermediate node the label counts or names."""

    steps: tuple[Step, ...]
    label_hop: int = 0


R, T = Relation, NodeType
_ABOUT_PAPER = _s(R.about, T.paper)
_AUTHORS = _s(R.authored, T.researcher)
_TO_INSTITUTION = _s(R.affiliated_with, T.institution)

CHAINS: dict[NodeType, tuple[Chain, ...]] = {
    T.disease: (
        Chain((_ABOUT_PAPER, _AUTHORS)),
        Chain((_s(R.funds_research_on, T.grant), _s(R.pi_of, T.researcher))),
        Chain((_s(R.caused_by_variant_in, T.gene), _ABOUT_PAPER, _AUTHORS)),
        Chain((_s(R.studies, T.trial), _s(R.investigator_of, T.doctor))),
        Chain((_ABOUT_PAPER, _AUTHORS, _TO_INSTITUTION), label_hop=1),
        Chain(
            (_s(R.funds_research_on, T.grant), _s(R.pi_of, T.researcher), _TO_INSTITUTION),
            label_hop=1,
        ),
        Chain(
            (_s(R.studies, T.trial), _s(R.investigator_of, T.doctor), _TO_INSTITUTION),
            label_hop=1,
        ),
        Chain((_s(R.studies, T.registry), _s(R.runs, T.institution, T.patient_org))),
    ),
    T.gene: (
        Chain((_ABOUT_PAPER, _AUTHORS)),
        Chain((_s(R.caused_by_variant_in, T.disease), _s(R.studies, T.trial))),
        Chain((_s(R.caused_by_variant_in, T.disease), _s(R.serves, T.patient_org))),
        Chain((_s(R.caused_by_variant_in, T.disease), _s(R.studies, T.registry))),
    ),
    T.phenotype: (
        Chain((_s(R.has_phenotype, T.disease), _s(R.caused_by_variant_in, T.gene))),
        Chain((_s(R.has_phenotype, T.disease), _s(R.serves, T.patient_org))),
        Chain((_s(R.has_phenotype, T.disease), _s(R.studies, T.trial))),
    ),
    T.researcher: (
        Chain((_s(R.authored, T.paper), _s(R.about, T.disease))),
        Chain((_s(R.authored, T.paper), _s(R.about, T.gene))),
        Chain((_s(R.pi_of, T.grant), _s(R.funds_research_on, T.disease))),
    ),
    T.doctor: (Chain((_s(R.investigator_of, T.trial), _s(R.studies, T.disease))),),
    T.institution: (
        Chain(
            (_s(R.affiliated_with, T.researcher), _s(R.authored, T.paper), _s(R.about, T.disease))
        ),
        Chain(
            (
                _s(R.affiliated_with, T.doctor),
                _s(R.investigator_of, T.trial),
                _s(R.studies, T.disease),
            )
        ),
    ),
    T.trial: (Chain((_s(R.investigator_of, T.doctor), _TO_INSTITUTION)),),
    T.pathway: (Chain((_s(R.participates_in, T.gene), _s(R.caused_by_variant_in, T.disease))),),
    T.variant: (Chain((_s(R.variant_of, T.gene), _s(R.caused_by_variant_in, T.disease))),),
    T.paper: (Chain((_s(R.about, T.gene), _s(R.caused_by_variant_in, T.disease))),),
    T.patient_org: (Chain((_s(R.runs, T.registry), _s(R.studies, T.disease))),),
    T.registry: (Chain((_s(R.runs, T.patient_org), _s(R.serves, T.disease))),),
    T.network: (Chain((_s(R.member_of, T.patient_org), _s(R.serves, T.disease))),),
}


def section_for(subject: Node, other: Node, hops: int = 1) -> SummarySectionKey | None:
    """Section of a connected node; None for types without a section."""
    if subject.type == NodeType.disease and other.type == NodeType.disease and hops == 1:
        return SummarySectionKey.similar_diseases
    return _TYPE_SECTION.get(other.type)


# A chain's sort key: fewer hops first (a direct link beats any walk), then the weakest link
# strongest, then active before under review, observed before inferred, then edge ids.
_Key = tuple[int, float, bool, bool, tuple[str, ...]]


def _chain_key(edges: tuple[Edge, ...], store: graph.GraphStore) -> _Key:
    return (
        len(edges),
        -min(e.confidence for e in edges),
        any(not graph.edge_is_active(store, e) for e in edges),
        any(e.origin != Origin.observed for e in edges),
        tuple(e.id for e in edges),
    )


@dataclass
class _Target:
    node: Node
    score: int = 0
    best_key: _Key | None = None
    best_edges: tuple[Edge, ...] = ()
    best_noun: NodeType | None = None
    direct: bool = False
    # label noun -> (distinct label nodes, best key and label node for that noun)
    label_nodes: dict[NodeType, set[str]] = field(default_factory=dict)
    label_best: dict[NodeType, tuple[_Key, str]] = field(default_factory=dict)
    noun_order: list[NodeType] = field(default_factory=list)

    def add(
        self,
        edges: tuple[Edge, ...],
        store: graph.GraphStore,
        noun: NodeType | None = None,
        label_node: str | None = None,
    ) -> None:
        self.score += 1
        key = _chain_key(edges, store)
        if self.best_key is None or key < self.best_key:
            self.best_key, self.best_edges, self.best_noun = key, edges, noun
        if noun is None or label_node is None:
            self.direct = True
            return
        if noun not in self.label_nodes:
            self.label_nodes[noun] = set()
            self.noun_order.append(noun)
        self.label_nodes[noun].add(label_node)
        prev = self.label_best.get(noun)
        if prev is None or key < prev[0]:
            self.label_best[noun] = (key, label_node)

    def via_label(self) -> str | None:
        if not self.label_nodes:
            return None
        order = sorted(self.noun_order, key=lambda n: n != self.best_noun)
        parts = []
        for noun in order:
            count = len(self.label_nodes[noun])
            singular, plural = _NOUNS.get(noun, (noun.value, noun.value + "s"))
            if noun not in _TITLE_NOUNS:
                best = graph.get_node(self.label_best[noun][1])
                name = _short(best.label if best else self.label_best[noun][1])
                parts.append(
                    f"{singular} {name}" if count == 1 else f"{count} {plural} incl. {name}"
                )
            else:
                parts.append(f"{count} {singular if count == 1 else plural}")
        text = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
        return ("direct link, also via " if self.direct else "via ") + text

    def item(self, store: graph.GraphStore) -> SummaryItem:
        edges = self.best_edges
        return SummaryItem(
            id=self.node.id,
            label=self.node.label,
            type=self.node.type,
            hops=len(edges),
            score=self.score,
            best_confidence=min(e.confidence for e in edges),
            inferred=any(e.origin != Origin.observed for e in edges),
            under_review=any(not graph.edge_is_active(store, e) for e in edges),
            via=[e.id for e in edges],
            via_label=self.via_label(),
            explanation=_single_inferred_explanation(edges),
        )


def _single_inferred_explanation(edges: tuple[Edge, ...]) -> str | None:
    """The explanation of a best chain that is one inferred edge (a computed link), else None."""
    if len(edges) == 1 and edges[0].origin == Origin.inferred:
        return edges[0].explanation
    return None


def _membership_item(node: Node, via_label: str) -> SummaryItem:
    return SummaryItem(
        id=node.id,
        label=node.label,
        type=node.type,
        hops=1,
        score=1,
        best_confidence=0.0,
        inferred=True,
        under_review=False,
        via=[],
        via_label=via_label,
    )


class _Adjacency:
    """Per-call memo of a node's incident edges (flag overlay and contributions applied)."""

    def __init__(self, store: graph.GraphStore) -> None:
        self.store = store
        self._memo: dict[str, list[tuple[Edge, Node]]] = {}

    def __call__(self, node_id: str) -> list[tuple[Edge, Node]]:
        out = self._memo.get(node_id)
        if out is None:
            out = []
            for edge in graph._incident_edges(self.store, node_id):
                other = graph.get_node(graph._other(edge, node_id))
                if other is not None and other.id != node_id:
                    out.append((edge, other))
            self._memo[node_id] = out
        return out


def _walk(subject: Node, chain: Chain, adj: _Adjacency):
    """Every simple walk matching the chain: (edges, nodes after the subject)."""
    frontier: list[tuple[tuple[Edge, ...], tuple[Node, ...]]] = [((), ())]
    for step in chain.steps:
        nxt = []
        for edges, nodes in frontier:
            here = nodes[-1].id if nodes else subject.id
            for edge, other in adj(here):
                if edge.relation != step.relation or other.type not in step.types:
                    continue
                if other.id == subject.id or any(n.id == other.id for n in nodes):
                    continue
                nxt.append(((*edges, edge), (*nodes, other)))
        frontier = nxt
    return frontier


def _cluster_top_genes(store: graph.GraphStore, cluster_id: str) -> list[Node]:
    """Gene nodes named in a cluster's attrs (ids in `genes`, or symbols in `top_genes`)."""
    summary = store.clusters.get(cluster_id)
    if summary is None:
        return []
    out: list[Node] = []
    for ref in [*summary.attrs.get("genes", []), *summary.attrs.get("top_genes", [])]:
        if not isinstance(ref, str):
            continue
        node = graph.get_node(ref)
        if node is None:
            for nid, _syn in store.name_index.get(graph.normalize_name(ref), ()):
                cand = graph.get_node(nid)
                if cand is not None and cand.type == NodeType.gene:
                    node = cand
                    break
        if node is not None and node.type == NodeType.gene and node not in out:
            out.append(node)
    return out


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

    adj = _Adjacency(store)
    targets: dict[str, _Target] = {}
    neighbor_types: Counter[NodeType] = Counter()
    for edge, other in adj(node.id):
        if other.id not in targets:
            targets[other.id] = _Target(other)
            neighbor_types[other.type] += 1
        targets[other.id].add((edge,), store)

    for chain in CHAINS.get(node.type, ()):
        for edges, nodes in _walk(node, chain, adj):
            target = nodes[-1]
            label_node = nodes[chain.label_hop]
            if target.id not in targets:
                targets[target.id] = _Target(target)
            targets[target.id].add(edges, store, label_node.type, label_node.id)

    grouped: dict[SummarySectionKey, list[SummaryItem]] = {}
    for target in targets.values():
        key = section_for(node, target.node, len(target.best_edges))
        if key is not None:
            grouped.setdefault(key, []).append(target.item(store))

    membership: list[tuple[Node, str]] = []
    if node.type == NodeType.cluster:
        membership += [(g, TOP_GENE_LABEL) for g in _cluster_top_genes(store, node.id)]
        membership += [
            (m, MEMBER_LABEL)
            for mid in store.members.get(node.id, ())
            if (m := graph.get_node(mid))
        ]
    if node.cluster_id and node.cluster_id != node.id:
        cluster = graph.get_node(node.cluster_id)
        if cluster is not None:
            membership.append((cluster, CLUSTER_OF_LABEL))
    seen = set(targets) | {node.id}
    for other, label in membership:
        if other.id in seen:
            continue
        seen.add(other.id)
        key = _TYPE_SECTION.get(other.type)
        if key is not None:
            grouped.setdefault(key, []).append(_membership_item(other, label))

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

    return AtlasSummary(
        node=node,
        tree_path=[
            TreePathItem(id=a.id, label=a.label, kind=a.kind) for a in atlas_tree.ancestors(node.id)
        ],
        headline=graph._summary(store, node, neighbor_types, lens.role),
        sections=sections,
        explain_edge_ids=explain_edges(sections),
        vus_notice=VUS_NOTICE if graph.is_vus(node) else None,
        data_version=store.data_version,
    )


def explain_edges(sections: list[SummarySection]) -> list[str]:
    """Best chains of the top items, round-robin over the sections (rank 1 of every section,
    then rank 2, ...), whole chains only, no duplicates, at most MAX_EXPLAIN_EDGES."""
    out: list[str] = []
    seen: set[str] = set()
    for rank in range(MAX_ITEMS):
        for section in sections:
            if rank >= len(section.items):
                continue
            new = [e for e in dict.fromkeys(section.items[rank].via) if e not in seen]
            if new and len(out) + len(new) <= MAX_EXPLAIN_EDGES:
                out += new
                seen.update(new)
    return out
