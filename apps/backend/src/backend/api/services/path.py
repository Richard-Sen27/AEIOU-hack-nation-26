"""Path: top-k weighted paths with edge cost -log(confidence).

Routing is undirected over active edges of the requested family. Excluded: edges whose
effective status is not active (pending review, open flags), VUS variants as intermediates
unless include_vus, and hub intermediates (see graph.GENERIC_TYPES / HUB_*): phenotypes,
mechanisms and pathways with degree >= the store's hub_degree are never traversed, smaller
ones add HUB_DAMPING * ln(degree) to the ranking cost. total_cost reports the plain
sum of -log(confidence). A path is supported when every edge has confidence >= threshold.
"""

from collections.abc import Callable
from itertools import islice

import networkx as nx

from backend.api.errors import ApiError, not_found
from backend.api.services.graph import (
    GraphStore,
    edge_cost,
    edge_is_active,
    effective_edge,
    get_graph,
    hub_penalty,
    is_hub,
    is_vus,
)
from backend.schemas.enums import (
    CONFIDENCE_THRESHOLD,
    ErrorCode,
    Origin,
    PathFamily,
    PathStatus,
    Relation,
    confidence_level,
    path_id,
)
from backend.schemas.path import (
    CoverageReport,
    MissingLink,
    Path,
    PathResponse,
    PathStep,
    SourceCount,
)

Weight = Callable[[str, str, dict], float | None]

_RELATION_PHRASES: dict[Relation, str] = {
    Relation.shared_pathway: "share a biological pathway",
    Relation.similar_symptoms: "have similar symptoms",
    Relation.same_gene_same_mechanism: "share the same gene and mechanism",
    Relation.same_gene_different_mechanism: "involve the same gene",
    Relation.shared_researcher: "are studied by the same researchers",
    Relation.shared_gene: "share a gene in a way that points to a common mechanism",
    Relation.near_on_chromosome: "share a cause beyond lying close together on a chromosome",
    Relation.candidate_phenotype: "are linked as disease and symptom",
    Relation.suggested_by_neighbour: "are related as their similar neighbours suggest",
    Relation.caused_by_variant_in: "are causally linked",
    Relation.has_phenotype: "are linked as disease and symptom",
    Relation.acts_via: "are linked through this mechanism",
    Relation.participates_in: "are linked through this pathway",
}


def _article(word: str) -> str:
    return "an" if word[:1] in "aeiou" else "a"


def _pick(store: GraphStore, data: dict, threshold: float) -> tuple[float, str] | None:
    for cost, _, eid in data["cands"]:
        edge = store.edges[eid]
        if edge.confidence >= threshold and edge_is_active(store, edge):
            return cost, eid
    return None


def _weight(
    store: GraphStore, source: str, target: str, threshold: float, include_vus: bool
) -> Weight:
    blocked: dict[str, bool] = {}
    penalty: dict[str, float] = {}

    def node_blocked(nid: str) -> bool:
        if nid not in blocked:
            node = store.nodes[nid]
            blocked[nid] = nid not in (source, target) and (
                is_hub(store, node) or (not include_vus and is_vus(node))
            )
            penalty[nid] = 0.0 if nid in (source, target) else hub_penalty(store, node)
        return blocked[nid]

    def weight(u: str, v: str, data: dict) -> float | None:
        if node_blocked(u) or node_blocked(v):
            return None
        chosen = _pick(store, data, threshold)
        if chosen is None:
            return None
        return chosen[0] + (penalty[u] + penalty[v]) / 2

    return weight


def _k_paths(graph: nx.Graph, source: str, target: str, k: int, weight: Weight) -> list[list[str]]:
    if source not in graph or target not in graph:
        return []
    try:
        return list(islice(nx.shortest_simple_paths(graph, source, target, weight=weight), k))
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return []


def _build_path(store: GraphStore, graph: nx.Graph, nodes: list[str], threshold: float) -> Path:
    steps: list[PathStep] = []
    for u, v in zip(nodes, nodes[1:], strict=False):
        chosen = _pick(store, graph[u][v], threshold)
        assert chosen is not None
        edge = effective_edge(store, store.edges[chosen[1]])
        steps.append(
            PathStep(
                edge=edge,
                from_node=store.nodes[u],
                to_node=store.nodes[v],
                reversed=edge.source_id != u,
            )
        )
    edges = [s.edge for s in steps]
    edge_ids = [e.id for e in edges]
    min_conf = min(e.confidence for e in edges)
    return Path(
        path_id=path_id(edge_ids),
        steps=steps,
        edge_ids=edge_ids,
        total_cost=round(sum(edge_cost(e.confidence) for e in edges), 6),
        min_confidence=min_conf,
        min_confidence_level=confidence_level(min_conf),
        all_observed=all(e.origin == Origin.observed for e in edges),
        all_active=all(edge_is_active(store, e) for e in edges),
        supported=min_conf >= CONFIDENCE_THRESHOLD and all(edge_is_active(store, e) for e in edges),
    )


def find_paths(
    from_id: str,
    to_id: str,
    *,
    family: PathFamily = PathFamily.all,
    k: int = 3,
    include_vus: bool = False,
) -> PathResponse:
    """Top-k supported paths, or no_supported_route with a coverage report."""
    store = get_graph()
    if from_id not in store.nodes or to_id not in store.nodes:
        raise not_found()
    if from_id == to_id:
        raise ApiError(400, ErrorCode.bad_request, "Start and end must be different nodes.")
    graph = store.path_graphs.get(family) or nx.Graph()

    strict = _weight(store, from_id, to_id, CONFIDENCE_THRESHOLD, include_vus)
    found = _k_paths(graph, from_id, to_id, k, strict)
    if found:
        return PathResponse(
            status=PathStatus.ok,
            from_id=from_id,
            to_id=to_id,
            family=family,
            paths=[_build_path(store, graph, p, CONFIDENCE_THRESHOLD) for p in found],
        )

    relaxed = _weight(store, from_id, to_id, 0.0, include_vus)
    partial_nodes = _k_paths(graph, from_id, to_id, 1, relaxed)
    partial = _build_path(store, graph, partial_nodes[0], 0.0) if partial_nodes else None
    return PathResponse(
        status=PathStatus.no_supported_route,
        from_id=from_id,
        to_id=to_id,
        family=family,
        coverage=_coverage(store, graph, from_id, to_id, family, partial, relaxed),
    )


def _reach(graph: nx.Graph, start: str, weight: Weight) -> set[str]:
    if start not in graph:
        return {start}
    seen, frontier = {start}, [start]
    while frontier:
        nxt = []
        for u in frontier:
            for v, data in graph[u].items():
                if v not in seen and weight(u, v, data) is not None:
                    seen.add(v)
                    nxt.append(v)
        frontier = nxt
    return seen


def _sources(store: GraphStore, node_ids: set[str], edge_ids: set[str]) -> list[SourceCount]:
    counts: dict[str, int] = {}
    for nid in node_ids:
        edge_ids.update(store.incident.get(nid, ()))
    for eid in edge_ids:
        for source, n in store.edge_sources.get(eid, {}).items():
            counts[source] = counts.get(source, 0) + n
    known = {s.lower() for s in counts}
    for source in (store.ingestion.get("source_versions") or {}).keys():
        if source.lower() not in known:
            counts[source] = 0
    return [
        SourceCount(source=s, count=n)
        for s, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    ]


def _coverage(
    store: GraphStore,
    graph: nx.Graph,
    from_id: str,
    to_id: str,
    family: PathFamily,
    partial: Path | None,
    relaxed: Weight,
) -> CoverageReport:
    src, dst = store.nodes[from_id], store.nodes[to_id]
    scope = "" if family == PathFamily.all else f" among {family.value} links"
    edge_ids = set(partial.edge_ids) if partial else set()
    sources = _sources(store, {from_id, to_id}, edge_ids)

    if partial is not None:
        weakest = min(partial.steps, key=lambda s: s.edge.confidence)
        edge = weakest.edge
        a, b = weakest.from_node, weakest.to_node
        tiers = store.edge_sources.get(edge.id, {})
        n_sources = sum(tiers.values())
        weak = [s for s in partial.steps if s.edge.confidence < CONFIDENCE_THRESHOLD]
        description = (
            f"The closest route{scope} has {len(weak)} link(s) below the "
            f"{CONFIDENCE_THRESHOLD:.2f} confidence threshold. The weakest connects "
            f"{a.label} and {b.label}: {_article(edge.origin.value)} {edge.origin.value} "
            f"{edge.relation.value.replace('_', ' ')} link with "
            f"{edge.confidence_level.value} confidence ({edge.confidence:.2f}) from "
            f"{n_sources} evidence item(s)"
            + (f", {edge.contradiction_count} contradicting" if edge.contradiction_count else "")
            + ". A peer-reviewed or curated source for this link would close the gap."
        )
        phrase = _RELATION_PHRASES.get(edge.relation, "are connected")
        return CoverageReport(
            sources_queried=sources,
            closest_partial_path=partial,
            missing_link=MissingLink(from_id=a.id, to_id=b.id, description=description),
            suggested_question=(
                f"Is there peer-reviewed or curated evidence that {a.label} and {b.label} {phrase}?"
            ),
        )

    left, right = _reach(graph, from_id, relaxed), _reach(graph, to_id, relaxed)
    description = (
        f"No sourced route{scope} connects {src.label} and {dst.label}. "
        f"From {src.label} the atlas reaches {len(left) - 1} other node(s); "
        f"from {dst.label} it reaches {len(right) - 1}; the two parts do not meet."
    )
    return CoverageReport(
        sources_queried=sources,
        closest_partial_path=None,
        missing_link=MissingLink(from_id=from_id, to_id=to_id, description=description),
        suggested_question=(
            f"Which genes, pathways, symptoms or researchers connect {src.label} and {dst.label}?"
        ),
    )
