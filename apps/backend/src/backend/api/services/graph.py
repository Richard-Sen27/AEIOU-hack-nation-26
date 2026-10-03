"""Graph: nodes and edges held in memory (NetworkX), loaded at startup."""

from dataclasses import dataclass, field

import networkx as nx
from sqlalchemy.ext.asyncio import AsyncSession

from backend.schemas.common import Lens
from backend.schemas.graph import (
    AtlasLayout,
    ClusterSummary,
    Edge,
    EdgeEvidence,
    Neighborhood,
    Node,
    NodeDetail,
)


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


async def load_graph(db: AsyncSession) -> GraphStore:
    """Load nodes, edges, clusters, synonyms and flag counts; install as the current store."""
    raise NotImplementedError


_store = GraphStore()


def get_graph() -> GraphStore:
    """The current in-memory store (empty GraphStore before load_graph succeeds)."""
    return _store


def set_graph(store: GraphStore) -> None:
    """Install a new store (used by load_graph and tests)."""
    global _store
    _store = store


async def refresh_flags(db: AsyncSession) -> None:
    """Reload open-flag counts via edge_flag_counts() into the current store."""
    raise NotImplementedError


def node_detail(node_id: str, lens: Lens) -> NodeDetail:
    """Node, synonyms, summary, relation counts, cluster; VUS notice for uncertain variants."""
    raise NotImplementedError


def neighborhood(node_id: str, lens: Lens) -> Neighborhood:
    """Same full neighborhood for every role; the lens only adds presentation hints."""
    raise NotImplementedError


def clusters() -> list[ClusterSummary]:
    """Cluster IDs, labels, sizes and mechanism summaries."""
    raise NotImplementedError


def atlas_layout() -> AtlasLayout:
    """Compact whole-graph layout for the Atlas view."""
    raise NotImplementedError


async def edge_evidence(db: AsyncSession, edge_id: str) -> EdgeEvidence:
    """Sources, quotes, tiers, contradictions and the confidence breakdown of one edge."""
    raise NotImplementedError
