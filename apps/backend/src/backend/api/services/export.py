"""Graph export: CSV or GraphML of a subgraph around a node.

Pipeline graph data only: the contributions overlay (user data) is never exported.
"""

import csv
import io
import re
from collections.abc import Iterator
from dataclasses import dataclass

import networkx as nx

from backend.api.errors import not_found
from backend.api.services.graph import GraphStore, effective_edge, get_graph
from backend.schemas.enums import GraphExportFormat
from backend.schemas.graph import Edge

CSV_COLUMNS = (
    "edge_id",
    "source_id",
    "source_label",
    "source_type",
    "relation",
    "target_id",
    "target_label",
    "target_type",
    "family",
    "confidence",
    "confidence_level",
    "origin",
    "status",
    "flagged",
    "evidence_count",
    "contradiction_count",
    "evidence_sources",
    "evidence_source_ids",
    "data_version",
)


@dataclass(frozen=True)
class GraphExport:
    content: str
    media_type: str  # text/csv or application/graphml+xml
    filename: str

    def chunks(self, size: int = 64 * 1024) -> Iterator[str]:
        for start in range(0, len(self.content), size):
            yield self.content[start : start + size]


def subgraph(store: GraphStore, node_id: str, depth: int) -> tuple[list[str], list[Edge]]:
    """Nodes within `depth` hops (direction ignored) and the edges among them."""
    seen, frontier = {node_id}, [node_id]
    for _ in range(depth):
        nxt = []
        for nid in frontier:
            for eid in store.incident.get(nid, ()):
                e = store.edges[eid]
                other = e.target_id if e.source_id == nid else e.source_id
                if other not in seen:
                    seen.add(other)
                    nxt.append(other)
        frontier = nxt
    edges = {
        eid: store.edges[eid]
        for nid in seen
        for eid in store.incident.get(nid, ())
        if store.edges[eid].source_id in seen and store.edges[eid].target_id in seen
    }
    nodes = [node_id] + sorted(seen - {node_id})
    return nodes, [effective_edge(store, edges[k]) for k in sorted(edges)]


def _sources(store: GraphStore, eid: str) -> tuple[str, str]:
    types = ";".join(f"{s}:{n}" for s, n in sorted(store.edge_sources.get(eid, {}).items()))
    ids = ";".join(dict.fromkeys(store.edge_source_ids.get(eid, ())))
    return types, ids


def _csv(store: GraphStore, edges: list[Edge]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for e in edges:
        s, t = store.nodes[e.source_id], store.nodes[e.target_id]
        types, ids = _sources(store, e.id)
        writer.writerow(
            [
                e.id,
                s.id,
                s.label,
                s.type.value,
                e.relation.value,
                t.id,
                t.label,
                t.type.value,
                e.family.value,
                e.confidence,
                e.confidence_level.value,
                e.origin.value,
                e.status.value,
                str(e.flagged).lower(),
                e.evidence_count,
                e.contradiction_count,
                types,
                ids,
                e.data_version or "",
            ]
        )
    return buf.getvalue()


def _graphml(store: GraphStore, nodes: list[str], edges: list[Edge]) -> str:
    g = nx.MultiDiGraph(data_version=store.data_version or "")
    for nid in nodes:
        n = store.nodes[nid]
        attrs = {"label": n.label, "type": n.type.value}
        for key in ("cluster_id", "x", "y", "centrality", "url"):
            value = getattr(n, key)
            if value is not None:
                attrs[key] = value
        g.add_node(nid, **attrs)
    for e in edges:
        types, ids = _sources(store, e.id)
        g.add_edge(
            e.source_id,
            e.target_id,
            key=e.id,
            id=e.id,
            relation=e.relation.value,
            family=e.family.value,
            confidence=e.confidence,
            confidence_level=e.confidence_level.value,
            origin=e.origin.value,
            status=e.status.value,
            flagged=e.flagged,
            evidence_count=e.evidence_count,
            contradiction_count=e.contradiction_count,
            evidence_sources=types,
            evidence_source_ids=ids,
        )
    return "\n".join(nx.generate_graphml(g, named_key_ids=True)) + "\n"


def export_graph(
    node_id: str, *, depth: int = 1, format: GraphExportFormat = GraphExportFormat.csv
) -> GraphExport:
    """Subgraph within `depth` hops of node_id; 404 for unknown nodes."""
    store = get_graph()
    if node_id not in store.nodes:
        raise not_found()
    nodes, edges = subgraph(store, node_id, depth)
    stem = "amber-" + re.sub(r"[^A-Za-z0-9]+", "-", node_id).strip("-") + f"-depth{depth}"
    if store.data_version:
        stem += "-" + re.sub(r"[^A-Za-z0-9.]+", "-", store.data_version)
    if format == GraphExportFormat.graphml:
        return GraphExport(
            _graphml(store, nodes, edges), "application/graphml+xml", stem + ".graphml"
        )
    return GraphExport(_csv(store, edges), "text/csv", stem + ".csv")
