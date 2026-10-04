"""Graph: nodes and edges held in memory (NetworkX), loaded at startup.

The store holds the pipeline graph as loaded. Two overlays are applied at presentation time,
never written to the graph tables:

- open user flags (edge_flag_counts()): such an edge is presented as ``under_review`` with
  ``flagged = true`` and can no longer support a path;
- shared contributions (shared_contributions()): patient-reported phenotype links and
  contributed assets as their own nodes/edges (ids ``CONTRIB:<12 hex>`` / ``c_<12 hex>``),
  always ``pending_review`` with the patient-reported tier weight, never feeding other edges.

Use ``get_node`` / ``get_edge`` for overlay-aware, effective lookups.
"""

import hashlib
import logging
import math
import re
import time
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import networkx as nx
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import not_found
from backend.api.services.contributions import origin_for
from backend.schemas.common import Lens
from backend.schemas.enums import (
    CONTRADICTION_PENALTY,
    TIER_WEIGHTS,
    VUS_NOTICE,
    ContributionKind,
    ContributionStatus,
    EdgeFamily,
    EdgeStatus,
    EvidenceTier,
    LabelStyle,
    NodeType,
    Origin,
    PathFamily,
    Polarity,
    Relation,
    Role,
    StartLayout,
    VariantClassification,
    compute_confidence,
    confidence_level,
)
from backend.schemas.graph import (
    AtlasEdge,
    AtlasLayout,
    AtlasNode,
    ClusterSummary,
    ConfidenceBreakdown,
    ConfidenceTerm,
    Edge,
    EdgeEvidence,
    Evidence,
    LayoutHints,
    Neighborhood,
    Node,
    NodeDetail,
    RelationCount,
)

log = logging.getLogger(__name__)

# Hub rule (used by the path service): phenotypes, mechanisms and pathways are generic
# connectors. As intermediates they cost HUB_DAMPING * ln(degree) extra (the degree damping
# of Hetionet's degree-weighted path count, w = 0.4), and with degree >= hub_degree
# (max(HUB_MIN_DEGREE, 95th percentile of the degrees of generic nodes)) they are not
# traversed at all.
GENERIC_TYPES = frozenset({NodeType.phenotype, NodeType.mechanism, NodeType.pathway})
HUB_DAMPING = 0.4
HUB_MIN_DEGREE = 10
HUB_PERCENTILE = 0.95

PATH_FAMILIES: dict[PathFamily, frozenset[EdgeFamily]] = {
    PathFamily.dna: frozenset({EdgeFamily.dna}),
    PathFamily.symptoms: frozenset({EdgeFamily.symptoms}),
    PathFamily.research: frozenset({EdgeFamily.research}),
    PathFamily.all: frozenset(EdgeFamily),
}

CONTRIB_NODE_PREFIX = "CONTRIB:"
CONTRIB_EDGE_PREFIX = "c_"
PATIENT_TIER_WEIGHT = TIER_WEIGHTS[EvidenceTier.patient_reported]


@dataclass
class GraphStore:
    """In-memory graph snapshot. `flag_counts` overlays open user flags (status under_review)."""

    data_version: str | None = None
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: dict[str, Edge] = field(default_factory=dict)
    clusters: dict[str, ClusterSummary] = field(default_factory=dict)
    synonyms: dict[str, list[str]] = field(default_factory=dict)
    flag_counts: dict[str, int] = field(default_factory=dict)
    graph: nx.MultiDiGraph = field(default_factory=nx.MultiDiGraph)
    # derived at load
    incident: dict[str, list[str]] = field(default_factory=dict)
    members: dict[str, list[str]] = field(default_factory=dict)
    degree: dict[str, int] = field(default_factory=dict)
    hub_degree: int = HUB_MIN_DEGREE
    path_graphs: dict[PathFamily, nx.Graph] = field(default_factory=dict)
    name_index: dict[str, list[tuple[str, str | None]]] = field(default_factory=dict)
    id_index: dict[str, str] = field(default_factory=dict)
    edge_sources: dict[str, dict[str, int]] = field(default_factory=dict)
    edge_source_ids: dict[str, list[str]] = field(default_factory=dict)
    ingestion: dict[str, Any] = field(default_factory=dict)
    # contributions overlay
    contrib_nodes: dict[str, Node] = field(default_factory=dict)
    contrib_edges: dict[str, Edge] = field(default_factory=dict)
    contrib_incident: dict[str, list[str]] = field(default_factory=dict)
    atlas_cache: tuple[bytes, str] | None = None
    tree_cache: Any = None  # atlas_tree.TreeCache, reset together with atlas_cache


_store = GraphStore()


def get_graph() -> GraphStore:
    """The current in-memory store (empty GraphStore before load_graph succeeds)."""
    return _store


def set_graph(store: GraphStore) -> None:
    """Install a new store (used by load_graph and tests)."""
    global _store
    _store = store


# --- helpers ------------------------------------------------------------------------------


def normalize_name(value: str) -> str:
    """Accent-, case- and punctuation-insensitive form used for exact name matching."""
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^0-9a-z+]+", " ", stripped).split())


def edge_cost(confidence: float) -> float:
    return -math.log(max(confidence, 1e-9))


def effective_edge(store: GraphStore, edge: Edge) -> Edge:
    """The edge as presented: open flags turn an active edge into under_review."""
    flags = store.flag_counts.get(edge.id, 0)
    if not flags:
        return edge
    status = EdgeStatus.under_review if edge.status == EdgeStatus.active else edge.status
    return edge.model_copy(update={"status": status, "flagged": True})


def edge_is_active(store: GraphStore, edge: Edge) -> bool:
    return edge.status == EdgeStatus.active and not store.flag_counts.get(edge.id)


def get_node(node_id: str) -> Node | None:
    store = get_graph()
    return store.nodes.get(node_id) or store.contrib_nodes.get(node_id)


def get_edge(edge_id: str) -> Edge | None:
    """Effective edge (flag overlay applied), including contribution overlay edges."""
    store = get_graph()
    edge = store.edges.get(edge_id)
    if edge is not None:
        return effective_edge(store, edge)
    return store.contrib_edges.get(edge_id)


def _require_node(store: GraphStore, node_id: str) -> Node:
    node = store.nodes.get(node_id) or store.contrib_nodes.get(node_id)
    if node is None:
        raise not_found()
    return node


def _incident_edges(store: GraphStore, node_id: str) -> Iterable[Edge]:
    for eid in store.incident.get(node_id, ()):
        yield effective_edge(store, store.edges[eid])
    for eid in store.contrib_incident.get(node_id, ()):
        yield store.contrib_edges[eid]


def _other(edge: Edge, node_id: str) -> str:
    return edge.target_id if edge.source_id == node_id else edge.source_id


def is_vus(node: Node) -> bool:
    return (
        node.type == NodeType.variant
        and node.attrs.get("classification") == VariantClassification.uncertain_significance
    )


def is_hub(store: GraphStore, node: Node) -> bool:
    return node.type in GENERIC_TYPES and store.degree.get(node.id, 0) >= store.hub_degree


def hub_penalty(store: GraphStore, node: Node) -> float:
    if node.type not in GENERIC_TYPES:
        return 0.0
    return HUB_DAMPING * math.log(max(store.degree.get(node.id, 1), 1))


# --- loading ------------------------------------------------------------------------------

_NODES_SQL = text(
    "SELECT id, type, label, description, url, attrs, cluster_id, x, y, centrality FROM nodes"
)
_EDGES_SQL = text(
    "SELECT id, source_id, target_id, relation, family, confidence, origin, status, features,"
    " data_version FROM edges"
)
_EVIDENCE_SQL = text(
    "SELECT edge_id, source_type, polarity, count(*)::int AS n,"
    " array_agg(source_id ORDER BY id) FILTER (WHERE source_id IS NOT NULL) AS source_ids"
    " FROM evidence GROUP BY edge_id, source_type, polarity"
)
_SYNONYMS_SQL = text("SELECT node_id, synonym FROM node_synonyms ORDER BY node_id, id")
_CLUSTERS_SQL = text("SELECT id, label, mechanism_summary, member_count, attrs FROM clusters")
_INGESTION_SQL = text(
    "SELECT data_version, pipeline_commit, source_versions, counts, created_at"
    " FROM ingestion_runs ORDER BY created_at DESC LIMIT 1"
)


async def load_graph(db: AsyncSession) -> GraphStore:
    """Load nodes, edges, clusters, synonyms and flag counts; install as the current store."""
    started = time.perf_counter()
    nodes = [dict(r) for r in (await db.execute(_NODES_SQL)).mappings()]
    edges = [dict(r) for r in (await db.execute(_EDGES_SQL)).mappings()]
    evidence = [dict(r) for r in (await db.execute(_EVIDENCE_SQL)).mappings()]
    synonyms = [dict(r) for r in (await db.execute(_SYNONYMS_SQL)).mappings()]
    clusters = [dict(r) for r in (await db.execute(_CLUSTERS_SQL)).mappings()]
    ingestion = (await db.execute(_INGESTION_SQL)).mappings().first()
    store = build_store(
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        synonyms=synonyms,
        clusters=clusters,
        ingestion=dict(ingestion) if ingestion else None,
    )
    set_graph(store)
    for refresh in (refresh_flags, refresh_contributions):
        try:
            async with db.begin_nested():
                await refresh(db)
        except Exception as exc:  # noqa: BLE001 - overlays are optional at startup
            log.warning("%s failed (%s)", refresh.__name__, type(exc).__name__)
    atlas_payload()
    from backend.api.services import atlas_tree, search

    atlas_tree.tree_payload()
    log.info(
        "graph store built in %.2fs: %d nodes, %d edges",
        time.perf_counter() - started,
        len(store.nodes),
        len(store.edges),
    )
    search.warm_up()
    return store


def build_store(
    *,
    nodes: Iterable[Mapping[str, Any]],
    edges: Iterable[Mapping[str, Any]],
    evidence: Iterable[Mapping[str, Any]] = (),
    synonyms: Iterable[Mapping[str, Any]] = (),
    clusters: Iterable[Mapping[str, Any]] = (),
    ingestion: Mapping[str, Any] | None = None,
) -> GraphStore:
    """Build the in-memory store from table rows (pure; used by load_graph and tests)."""
    store = GraphStore()
    skipped = Counter()

    for row in nodes:
        try:
            node = Node.model_validate({**row, "attrs": row.get("attrs") or {}})
        except ValidationError:
            skipped["nodes"] += 1
            continue
        store.nodes[node.id] = node

    for row in synonyms:
        if row["node_id"] in store.nodes:
            store.synonyms.setdefault(row["node_id"], []).append(row["synonym"])

    for row in clusters:
        try:
            summary = ClusterSummary.model_validate(
                {
                    **row,
                    "label": row.get("label") or row["id"],
                    "member_count": row.get("member_count") or 0,
                    "attrs": row.get("attrs") or {},
                }
            )
        except ValidationError:
            skipped["clusters"] += 1
            continue
        store.clusters[summary.id] = summary

    support: Counter[str] = Counter()
    contra: Counter[str] = Counter()
    for row in evidence:
        eid = row["edge_id"]
        n = int(row["n"])
        if row["polarity"] == Polarity.contradicts:
            contra[eid] += n
        else:
            support[eid] += n
        sources = store.edge_sources.setdefault(eid, {})
        sources[row["source_type"]] = sources.get(row["source_type"], 0) + n
        if row.get("source_ids"):
            store.edge_source_ids.setdefault(eid, []).extend(row["source_ids"])

    graph = nx.MultiDiGraph()
    graph.add_nodes_from(store.nodes)
    for row in edges:
        if row["source_id"] not in store.nodes or row["target_id"] not in store.nodes:
            skipped["edges"] += 1
            continue
        eid = row["id"]
        confidence = float(row["confidence"])
        try:
            edge = Edge.model_validate(
                {
                    **row,
                    "confidence": confidence,
                    "confidence_level": confidence_level(confidence),
                    "evidence_count": support[eid] + contra[eid],
                    "contradiction_count": contra[eid],
                }
            )
        except ValidationError:
            skipped["edges"] += 1
            continue
        store.edges[eid] = edge
        graph.add_edge(edge.source_id, edge.target_id, key=eid)
        store.incident.setdefault(edge.source_id, []).append(eid)
        if edge.target_id != edge.source_id:
            store.incident.setdefault(edge.target_id, []).append(eid)
    store.graph = graph

    if ingestion:
        store.ingestion = dict(ingestion)
        store.data_version = ingestion.get("data_version")
    if store.data_version is None:
        versions = sorted({e.data_version for e in store.edges.values() if e.data_version})
        store.data_version = versions[-1] if versions else None

    store.degree = {nid: len(store.incident.get(nid, ())) for nid in store.nodes}
    degrees = sorted(d for nid, d in store.degree.items() if store.nodes[nid].type in GENERIC_TYPES)
    if degrees:
        pct = degrees[min(len(degrees) - 1, int(HUB_PERCENTILE * len(degrees)))]
        store.hub_degree = max(HUB_MIN_DEGREE, pct)

    for node in store.nodes.values():
        if node.cluster_id:
            store.members.setdefault(node.cluster_id, []).append(node.id)
    for cid, summary in store.clusters.items():
        if not summary.member_count:
            count = sum(
                1 for m in store.members.get(cid, ()) if store.nodes[m].type == NodeType.disease
            )
            store.clusters[cid] = summary.model_copy(update={"member_count": count})

    _fill_positions(store)
    _build_indexes(store)
    store.path_graphs = {family: _path_graph(store, fams) for family, fams in PATH_FAMILIES.items()}
    if skipped:
        log.warning("graph rows skipped: %s", dict(skipped))
    return store


def _fill_positions(store: GraphStore) -> None:
    """Precomputed positions come from the pipeline; place any missing node deterministically."""
    missing = [n for n in store.nodes.values() if n.x is None or n.y is None]
    if not missing:
        return
    groups = sorted({n.cluster_id or n.type.value for n in missing})
    centers = {
        g: (
            1000 * math.cos(2 * math.pi * i / len(groups)),
            1000 * math.sin(2 * math.pi * i / len(groups)),
        )
        for i, g in enumerate(groups)
    }
    for node in missing:
        h = int(hashlib.sha1(node.id.encode()).hexdigest()[:8], 16)
        angle, radius = (h % 3600) / 3600 * 2 * math.pi, 50 + (h >> 12) % 250
        cx, cy = centers[node.cluster_id or node.type.value]
        store.nodes[node.id] = node.model_copy(
            update={
                "x": round(cx + radius * math.cos(angle), 2),
                "y": round(cy + radius * math.sin(angle), 2),
            }
        )


def _build_indexes(store: GraphStore) -> None:
    for node in store.nodes.values():
        store.id_index[node.id.upper()] = node.id
        names: list[tuple[str, str | None]] = [(node.label, None)]
        symbol = node.attrs.get("symbol")
        if isinstance(symbol, str) and symbol != node.label:
            names.append((symbol, None))
        names += [(s, s) for s in store.synonyms.get(node.id, ())]
        seen: set[str] = set()
        for name, synonym in names:
            key = normalize_name(name)
            if key and key not in seen:
                seen.add(key)
                store.name_index.setdefault(key, []).append((node.id, synonym))


def _path_graph(store: GraphStore, families: frozenset[EdgeFamily]) -> nx.Graph:
    """Undirected graph for routing; each node pair keeps its active candidate edges by cost."""
    g = nx.Graph()
    for edge in store.edges.values():
        if (
            edge.family not in families
            or edge.status != EdgeStatus.active
            or edge.source_id == edge.target_id
            or edge.confidence <= 0
        ):
            continue
        u, v = edge.source_id, edge.target_id
        cand = (edge_cost(edge.confidence), -edge.evidence_count, edge.id)
        if g.has_edge(u, v):
            g[u][v]["cands"].append(cand)
        else:
            g.add_edge(u, v, cands=[cand])
    for _, _, data in g.edges(data=True):
        data["cands"].sort()
    return g


# --- overlays -----------------------------------------------------------------------------


async def refresh_flags(db: AsyncSession) -> None:
    """Reload open-flag counts via edge_flag_counts() into the current store."""
    rows = (await db.execute(text("SELECT edge_id, open_flags FROM edge_flag_counts()"))).all()
    store = get_graph()
    store.flag_counts = {r.edge_id: int(r.open_flags) for r in rows if r.open_flags}
    store.atlas_cache = None
    store.tree_cache = None


async def refresh_contributions(db: AsyncSession) -> None:
    """Overlay shared contributions (shared_contributions()) as pending_review nodes/edges."""
    rows = (
        await db.execute(text("SELECT id, kind, payload, status FROM shared_contributions()"))
    ).mappings()
    store = get_graph()
    nodes, edges = build_contribution_overlay(store, [dict(r) for r in rows])
    incident: dict[str, list[str]] = defaultdict(list)
    for edge in edges.values():
        incident[edge.source_id].append(edge.id)
        incident[edge.target_id].append(edge.id)
    store.contrib_nodes, store.contrib_edges = nodes, edges
    store.contrib_incident = dict(incident)
    store.atlas_cache = None
    store.tree_cache = None


def _overlay_id(prefix: str, key: str) -> str:
    return prefix + hashlib.sha1(key.encode()).hexdigest()[:12]


def _overlay_edge(
    source_id: str,
    relation: Relation,
    target_id: str,
    family: EdgeFamily,
    origin: Origin,
    reports: int,
    features: dict[str, Any],
    data_version: str | None,
) -> Edge:
    return Edge(
        id=_overlay_id(CONTRIB_EDGE_PREFIX, f"{source_id}|{relation}|{target_id}|{origin}"),
        source_id=source_id,
        target_id=target_id,
        relation=relation,
        family=family,
        confidence=PATIENT_TIER_WEIGHT,
        confidence_level=confidence_level(PATIENT_TIER_WEIGHT),
        origin=origin,
        status=EdgeStatus.pending_review,
        features=features,
        data_version=data_version,
        evidence_count=reports,
    )


def build_contribution_overlay(
    store: GraphStore, rows: Iterable[Mapping[str, Any]]
) -> tuple[dict[str, Node], dict[str, Edge]]:
    """Phenotype profiles aggregate into patient_reported disease->phenotype edges (no patient
    nodes); assets become registry-type nodes linked to their diseases. Each carries its
    contribution's own origin (contributions.origin_for: patient_reported for both)."""
    phenotypes: dict[tuple[str, str], Counter] = defaultdict(Counter)
    nodes: dict[str, Node] = {}
    edges: dict[str, Edge] = {}
    for row in rows:
        if row.get("status") == ContributionStatus.rejected:
            continue
        payload = row.get("payload") or {}
        kind = row.get("kind")
        if kind == ContributionKind.phenotype_profile:
            disease = payload.get("disease_id")
            if disease not in store.nodes:
                continue
            for hp in payload.get("phenotype_ids") or ():
                if hp in store.nodes:
                    phenotypes[(disease, hp)]["reports"] += 1
            for hp in payload.get("excluded_phenotype_ids") or ():
                if hp in store.nodes:
                    phenotypes[(disease, hp)]["absent_reports"] += 1
        elif kind == ContributionKind.asset and payload.get("name"):
            origin = origin_for(kind)
            diseases = [d for d in payload.get("disease_ids") or () if d in store.nodes]
            nid = _overlay_id(CONTRIB_NODE_PREFIX, str(row["id"]))
            anchor = store.nodes[diseases[0]] if diseases else None
            h = int(hashlib.sha1(nid.encode()).hexdigest()[:8], 16)
            if anchor is not None and anchor.x is not None and anchor.y is not None:
                x, y = anchor.x + 40, anchor.y + 40
            else:
                x, y = float(h % 2000 - 1000), float((h >> 11) % 2000 - 1000)
            nodes[nid] = Node(
                id=nid,
                type=NodeType.registry,
                label=str(payload["name"])[:200],
                description=payload.get("description"),
                url=payload.get("url"),
                attrs={
                    "kind": payload.get("asset_type") or "other",
                    "origin": origin.value,
                    "status": EdgeStatus.pending_review.value,
                    "contributed": True,
                },
                x=x,
                y=y,
            )
            for disease in diseases:
                edge = _overlay_edge(
                    nid,
                    Relation.about,
                    disease,
                    EdgeFamily.research,
                    origin,
                    1,
                    {"label": "contributed asset"},
                    store.data_version,
                )
                edges[edge.id] = edge
    for (disease, hp), counts in sorted(phenotypes.items()):
        if not counts["reports"]:
            continue
        edge = _overlay_edge(
            disease,
            Relation.has_phenotype,
            hp,
            EdgeFamily.symptoms,
            Origin.patient_reported,
            counts["reports"],
            {
                "reports": counts["reports"],
                "absent_reports": counts["absent_reports"],
                "label": "patient-reported",
            },
            store.data_version,
        )
        edges[edge.id] = edge
    return nodes, edges


# --- presentation -------------------------------------------------------------------------

ROLE_HINTS: dict[Role, LayoutHints] = {
    Role.guest: LayoutHints(
        start_layout=StartLayout.tour,
        label_style=LabelStyle.plain,
        highlight_family=[EdgeFamily.symptoms, EdgeFamily.community, EdgeFamily.dna],
        highlight_node_types=[NodeType.disease, NodeType.patient_org, NodeType.registry],
        show_ids=False,
        reading_grade_target=6,
    ),
    Role.patient: LayoutHints(
        start_layout=StartLayout.ring,
        label_style=LabelStyle.plain,
        highlight_family=[EdgeFamily.symptoms, EdgeFamily.community, EdgeFamily.dna],
        highlight_node_types=[NodeType.disease, NodeType.patient_org, NodeType.registry],
        show_ids=False,
        reading_grade_target=8,
    ),
    Role.doctor: LayoutHints(
        start_layout=StartLayout.hierarchy,
        label_style=LabelStyle.clinical,
        highlight_family=[EdgeFamily.symptoms, EdgeFamily.community, EdgeFamily.dna],
        highlight_node_types=[
            NodeType.phenotype,
            NodeType.institution,
            NodeType.doctor,
            NodeType.trial,
            NodeType.variant,
        ],
        show_ids=False,
        reading_grade_target=12,
    ),
    Role.researcher: LayoutHints(
        start_layout=StartLayout.cluster,
        label_style=LabelStyle.technical,
        highlight_family=[EdgeFamily.dna, EdgeFamily.research],
        highlight_node_types=[
            NodeType.cluster,
            NodeType.mechanism,
            NodeType.variant,
            NodeType.pathway,
            NodeType.paper,
            NodeType.grant,
        ],
        show_ids=True,
        reading_grade_target=14,
    ),
}


def layout_hints(role: Role) -> LayoutHints:
    return ROLE_HINTS.get(role, ROLE_HINTS[Role.guest]).model_copy(deep=True)


def _cluster_of(store: GraphStore, node: Node) -> ClusterSummary | None:
    if node.type == NodeType.cluster and node.id in store.clusters:
        return store.clusters[node.id]
    return store.clusters.get(node.cluster_id) if node.cluster_id else None


def neighborhood(node_id: str, lens: Lens) -> Neighborhood:
    """Same full neighborhood for every role; the lens only adds presentation hints."""
    store = get_graph()
    center = _require_node(store, node_id)
    ids = {center.id}
    if center.type == NodeType.cluster:
        ids.update(store.members.get(center.id, ()))
    for edge in _incident_edges(store, center.id):
        ids.add(_other(edge, center.id))
    edges: dict[str, Edge] = {}
    for nid in ids:
        for edge in _incident_edges(store, nid):
            if _other(edge, nid) in ids:
                edges[edge.id] = edge
    others = sorted(ids - {center.id})
    return Neighborhood(
        center=center,
        nodes=[center] + [n for i in others if (n := get_node(i)) is not None],
        edges=[edges[k] for k in sorted(edges)],
        cluster=_cluster_of(store, center),
        hints=layout_hints(lens.role),
        data_version=store.data_version,
    )


_TYPE_WORDS: dict[NodeType, tuple[str, str]] = {
    NodeType.disease: ("condition", "conditions"),
    NodeType.gene: ("gene", "genes"),
    NodeType.variant: ("variant", "variants"),
    NodeType.mechanism: ("mechanism", "mechanisms"),
    NodeType.pathway: ("pathway", "pathways"),
    NodeType.phenotype: ("symptom", "symptoms"),
    NodeType.paper: ("paper", "papers"),
    NodeType.claim: ("claim", "claims"),
    NodeType.researcher: ("researcher", "researchers"),
    NodeType.doctor: ("doctor", "doctors"),
    NodeType.institution: ("institution", "institutions"),
    NodeType.network: ("network", "networks"),
    NodeType.grant: ("grant", "grants"),
    NodeType.trial: ("study", "studies"),
    NodeType.patient_org: ("patient group", "patient groups"),
    NodeType.registry: ("registry or study", "registries or studies"),
    NodeType.cluster: ("cluster", "clusters"),
}
_TECHNICAL_WORDS = {
    NodeType.disease: ("disease", "diseases"),
    NodeType.phenotype: ("phenotype", "phenotypes"),
    NodeType.trial: ("clinical study", "clinical studies"),
}


def _summary(store: GraphStore, node: Node, neighbor_types: Counter, role: Role) -> str:
    words = dict(_TYPE_WORDS)
    if role in (Role.doctor, Role.researcher):
        words.update(_TECHNICAL_WORDS)
    parts = []
    for ntype, count in sorted(neighbor_types.items(), key=lambda kv: (-kv[1], kv[0].value))[:4]:
        singular, plural = words[ntype]
        parts.append(f"{count} {singular if count == 1 else plural}")
    lead = (node.description or node.label).strip()
    if not lead.endswith("."):
        lead += "."
    if node.type == NodeType.cluster:
        count = len(store.members.get(node.id, ()))
        return f"{lead} Groups {count} members by shared mechanism or symptoms."
    if not parts:
        return lead
    linked = ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1]
    return f"{lead} Linked to {linked} in the atlas."


def node_detail(node_id: str, lens: Lens) -> NodeDetail:
    """Node, synonyms, summary, relation counts, cluster; VUS notice for uncertain variants."""
    store = get_graph()
    node = _require_node(store, node_id)
    relations: Counter[tuple[Relation, EdgeFamily]] = Counter()
    neighbor_types: Counter[NodeType] = Counter()
    seen: set[str] = set()
    degree = 0
    for edge in _incident_edges(store, node.id):
        degree += 1
        relations[(edge.relation, edge.family)] += 1
        other = _other(edge, node.id)
        if other not in seen and (other_node := get_node(other)) is not None:
            seen.add(other)
            neighbor_types[other_node.type] += 1
    classification = None
    if node.type == NodeType.variant:
        try:
            classification = VariantClassification(node.attrs.get("classification"))
        except ValueError:
            classification = None
    return NodeDetail(
        node=node,
        synonyms=store.synonyms.get(node.id, []),
        summary=_summary(store, node, neighbor_types, lens.role),
        relation_counts=[
            RelationCount(relation=rel, family=fam, count=n)
            for (rel, fam), n in sorted(relations.items(), key=lambda kv: (-kv[1], kv[0][0].value))
        ],
        degree=degree,
        cluster=_cluster_of(store, node),
        classification=classification,
        vus_notice=VUS_NOTICE
        if classification == VariantClassification.uncertain_significance
        else None,
    )


def clusters() -> list[ClusterSummary]:
    """Cluster IDs, labels, sizes and mechanism summaries."""
    store = get_graph()
    return [store.clusters[k] for k in sorted(store.clusters)]


def atlas_layout() -> AtlasLayout:
    """Compact whole-graph layout for the Atlas view."""
    store = get_graph()
    all_nodes = list(store.nodes.values()) + list(store.contrib_nodes.values())
    all_edges = [effective_edge(store, e) for e in store.edges.values()] + list(
        store.contrib_edges.values()
    )
    return AtlasLayout(
        nodes=[
            AtlasNode(
                id=n.id,
                type=n.type,
                label=n.label,
                x=n.x,
                y=n.y,
                cluster_id=n.cluster_id,
                centrality=n.centrality,
            )
            for n in all_nodes
        ],
        edges=[
            AtlasEdge(
                id=e.id,
                source=e.source_id,
                target=e.target_id,
                relation=e.relation,
                family=e.family,
                confidence=e.confidence,
                origin=e.origin,
                status=e.status,
                explanation=e.explanation,
            )
            for e in all_edges
        ],
        clusters=clusters(),
        data_version=store.data_version,
    )


def atlas_payload() -> tuple[bytes, str]:
    """Serialized atlas JSON and its ETag ("<data_version>.<content hash>"), cached per store."""
    store = get_graph()
    cached = store.atlas_cache
    if cached is None:
        body = atlas_layout().model_dump_json().encode()
        digest = hashlib.sha1(body).hexdigest()[:16]
        cached = (body, f'"{store.data_version or "empty"}.{digest}"')
        store.atlas_cache = cached
    return cached


# --- evidence -----------------------------------------------------------------------------

_EVIDENCE_ROWS_SQL = text(
    "SELECT id, edge_id, tier, source_type, source_id, url, quote, retrieved_at, polarity,"
    " claim_type FROM evidence WHERE edge_id = :edge_id ORDER BY id"
)


def confidence_breakdown(supporting: list[Evidence], n_contradicting: int) -> ConfidenceBreakdown:
    weights = [e.tier_weight for e in supporting]
    support_score = round(1.0 - math.prod(1.0 - w for w in weights), 6)
    penalty = round(CONTRADICTION_PENALTY * n_contradicting, 6)
    result = compute_confidence(weights, n_contradicting)
    product = " × ".join(f"(1 − {w:.2f})" for w in weights) if weights else "1"
    formula = f"1 − {product} − {CONTRADICTION_PENALTY:g} × {n_contradicting} = {result:.2f}"
    if not 0 <= support_score - penalty <= 1:
        formula += " (clamped to 0–1)"
    return ConfidenceBreakdown(
        supporting=[
            ConfidenceTerm(evidence_id=e.id, tier=e.tier, weight=e.tier_weight) for e in supporting
        ],
        support_score=support_score,
        n_contradicting=n_contradicting,
        penalty_per_contradiction=CONTRADICTION_PENALTY,
        penalty=penalty,
        result=result,
        level=confidence_level(result),
        formula=formula,
    )


def _weight_computed_rows(supporting: list[Evidence], confidence: float) -> None:
    """Computed rows carry no weight of their own: they share the link's score so that together
    they give exactly that score (capped at the computed tier's ceiling)."""
    computed = [e for e in supporting if e.tier == EvidenceTier.computed]
    if computed:
        share = 1.0 - (1.0 - confidence) ** (1.0 / len(computed))
        weight = round(min(TIER_WEIGHTS[EvidenceTier.computed], share), 6)
        for e in computed:
            e.tier_weight = weight


async def edge_evidence(db: AsyncSession, edge_id: str) -> EdgeEvidence:
    """Sources, quotes, tiers, contradictions and the confidence breakdown of one edge."""
    store = get_graph()
    edge = get_edge(edge_id)
    if edge is None:
        raise not_found()
    source, target = get_node(edge.source_id), get_node(edge.target_id)
    if source is None or target is None:
        raise not_found()

    items: list[Evidence] = []
    if edge.id in store.contrib_edges:
        items = [
            Evidence(
                id=0,
                edge_id=edge.id,
                tier=EvidenceTier.patient_reported,
                tier_weight=PATIENT_TIER_WEIGHT,
                source_type="contribution",
                polarity=Polarity.supports,
            )
        ]
    else:
        for row in (await db.execute(_EVIDENCE_ROWS_SQL, {"edge_id": edge.id})).mappings():
            tier = row["tier"]
            try:
                items.append(
                    Evidence.model_validate(
                        {**row, "tier_weight": TIER_WEIGHTS[EvidenceTier(tier)]}
                    )
                )
            except (ValueError, ValidationError):
                log.warning("evidence row %s skipped (invalid tier or polarity)", row["id"])
    supporting = [e for e in items if e.polarity == Polarity.supports]
    contradicting = [e for e in items if e.polarity == Polarity.contradicts]
    _weight_computed_rows(supporting, edge.confidence)
    return EdgeEvidence(
        edge=edge,
        source=source,
        target=target,
        supporting=supporting,
        contradicting=contradicting,
        confidence_breakdown=confidence_breakdown(supporting, len(contradicting)),
        open_flags=store.flag_counts.get(edge.id, 0),
    )
