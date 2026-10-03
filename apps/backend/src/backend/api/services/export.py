"""Graph export: CSV or GraphML of a subgraph around a node."""

from dataclasses import dataclass

from backend.schemas.enums import GraphExportFormat


@dataclass(frozen=True)
class GraphExport:
    content: str
    media_type: str  # text/csv or application/graphml+xml
    filename: str


def export_graph(
    node_id: str, *, depth: int = 1, format: GraphExportFormat = GraphExportFormat.csv
) -> GraphExport:
    """Subgraph within `depth` hops of node_id; 404 for unknown nodes."""
    raise NotImplementedError
