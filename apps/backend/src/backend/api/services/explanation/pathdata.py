"""Path data for explanations and proposals: edges and nodes from the in-memory graph, evidence
rows from Postgres."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.services import graph as graph_service
from backend.schemas.enums import EdgeStatus, Origin, path_id
from backend.schemas.graph import Edge, Node

_EVIDENCE_SQL = text(
    "SELECT edge_id, tier, source_type, source_id, url, quote, retrieved_at, polarity"
    " FROM evidence WHERE edge_id = ANY(:ids) ORDER BY edge_id, id"
)


@dataclass
class EvidenceItem:
    tier: str
    source_type: str
    source_id: str | None
    url: str | None
    quote: str | None
    retrieved_at: datetime | None
    polarity: str

    @property
    def contradicts(self) -> bool:
        return self.polarity == "contradicts"

    def label(self) -> str:
        return " ".join(p for p in (self.source_type, self.source_id) if p)


@dataclass
class PathData:
    edge_ids: list[str]
    edges: dict[str, Edge] = field(default_factory=dict)
    nodes: dict[str, Node] = field(default_factory=dict)
    evidence: dict[str, list[EvidenceItem]] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    data_version: str | None = None

    @property
    def path_id(self) -> str:
        return path_id(self.edge_ids)

    def ordered_edges(self) -> list[Edge]:
        return [self.edges[e] for e in self.edge_ids if e in self.edges]

    def contradicting(self, edge_id: str) -> list[EvidenceItem]:
        return [ev for ev in self.evidence.get(edge_id, []) if ev.contradicts]

    def supporting(self, edge_id: str) -> list[EvidenceItem]:
        return [ev for ev in self.evidence.get(edge_id, []) if not ev.contradicts]

    def node_label(self, node_id: str) -> str:
        node = self.nodes.get(node_id)
        return node.label if node else node_id

    def vus_nodes(self) -> list[Node]:
        return [n for n in self.nodes.values() if graph_service.is_vus(n)]


def has_contradiction(edge: Edge, data: PathData | None = None) -> bool:
    if edge.contradiction_count:
        return True
    return bool(data and data.contradicting(edge.id))


def is_supportive(edge: Edge, data: PathData | None = None) -> bool:
    """Observed, active and uncontradicted: the only edges that may back a viable action."""
    return (
        edge.origin == Origin.observed
        and edge.status == EdgeStatus.active
        and not has_contradiction(edge, data)
    )


async def load_evidence(db: AsyncSession, edge_ids: Iterable[str]) -> dict[str, list[EvidenceItem]]:
    ids = list(dict.fromkeys(edge_ids))
    out: dict[str, list[EvidenceItem]] = {e: [] for e in ids}
    if not ids:
        return out
    rows = (await db.execute(_EVIDENCE_SQL, {"ids": ids})).mappings().all()
    for r in rows:
        out.setdefault(r["edge_id"], []).append(
            EvidenceItem(
                tier=r["tier"],
                source_type=r["source_type"],
                source_id=r["source_id"],
                url=r["url"],
                quote=r["quote"],
                retrieved_at=r["retrieved_at"],
                polarity=r["polarity"],
            )
        )
    return out


async def load_path_data(
    db: AsyncSession, edge_ids: Sequence[str], *, extra_node_ids: Iterable[str] = ()
) -> PathData:
    """Edges in the given order (unknown IDs listed in `missing`), their endpoint nodes and
    evidence rows."""
    from backend.api.services.account import current_data_version

    ids = list(dict.fromkeys(edge_ids))
    data = PathData(edge_ids=ids)
    for eid in ids:
        edge = graph_service.get_edge(eid)
        if edge is None:
            data.missing.append(eid)
            continue
        data.edges[eid] = edge
    node_ids = [n for e in data.edges.values() for n in (e.source_id, e.target_id)]
    for nid in [*node_ids, *extra_node_ids]:
        node = graph_service.get_node(nid)
        if node is not None:
            data.nodes[nid] = node
    data.evidence = await load_evidence(db, data.edges)
    data.data_version = await current_data_version(db)
    return data


def compact_features(features: dict[str, Any] | None, limit: int = 6) -> dict[str, Any] | None:
    if not features:
        return None
    out: dict[str, Any] = {}
    for key, value in list(features.items())[:limit]:
        if isinstance(value, list):
            value = value[:limit]
        elif isinstance(value, str):
            value = value[:200]
        out[key] = value
    return out
