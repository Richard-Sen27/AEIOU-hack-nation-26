from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response, StreamingResponse

from backend.api.deps import DB, LensDep
from backend.api.errors import responses
from backend.api.services import export, graph, search
from backend.schemas.enums import GraphExportFormat, NodeType
from backend.schemas.graph import (
    AtlasLayout,
    ClusterSummary,
    EdgeEvidence,
    Neighborhood,
    NodeDetail,
)
from backend.schemas.search import SearchResponse

router = APIRouter(tags=["graph"])


@router.get(
    "/search",
    response_model=SearchResponse,
    responses=responses(422, 501),
    operation_id="search",
)
async def search_nodes(
    db: DB,
    q: Annotated[str, Query(min_length=1, max_length=200, description="Search text.")],
    types: Annotated[list[NodeType] | None, Query(description="Restrict to node types.")] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    expert: Annotated[bool, Query(description="Expert mode: rank clusters.")] = False,
) -> SearchResponse:
    """Typed matches with the matched synonym."""
    return await search.search(db, q, types=types, limit=limit, expert=expert)


@router.get(
    "/node/{node_id}",
    response_model=NodeDetail,
    responses=responses(404, 501),
    operation_id="getNode",
)
async def get_node(node_id: str, lens: LensDep) -> NodeDetail:
    """Node details and summary for the side panel."""
    return graph.node_detail(node_id, lens)


@router.get(
    "/neighborhood/{node_id}",
    response_model=Neighborhood,
    responses=responses(404, 501),
    operation_id="getNeighborhood",
)
async def get_neighborhood(node_id: str, lens: LensDep) -> Neighborhood:
    """Full neighborhood with positions and role presentation hints."""
    return graph.neighborhood(node_id, lens)


@router.get(
    "/clusters",
    response_model=list[ClusterSummary],
    responses=responses(501),
    operation_id="listClusters",
)
async def list_clusters() -> list[ClusterSummary]:
    """Cluster IDs, labels and sizes."""
    return graph.clusters()


ATLAS_CACHE_CONTROL = "public, max-age=60, must-revalidate"


@router.get(
    "/atlas.json",
    response_model=AtlasLayout,
    responses={304: {"description": "Not modified (If-None-Match matched the ETag)."}}
    | responses(501),
    operation_id="getAtlas",
)
async def get_atlas(request: Request) -> Response:
    """Compact whole-graph layout for the Atlas view (ETag keyed on data_version)."""
    body, etag = graph.atlas_payload()
    headers = {"ETag": etag, "Cache-Control": ATLAS_CACHE_CONTROL}
    match = request.headers.get("if-none-match", "")
    if etag in [t.strip().removeprefix("W/") for t in match.split(",")]:
        return Response(status_code=304, headers=headers)
    return Response(body, media_type="application/json", headers=headers)


@router.get(
    "/edge/{edge_id}/evidence",
    response_model=EdgeEvidence,
    responses=responses(404, 501),
    operation_id="getEdgeEvidence",
)
async def get_edge_evidence(edge_id: str, db: DB) -> EdgeEvidence:
    """Sources, quotes, tiers, contradictions and the confidence breakdown."""
    return await graph.edge_evidence(db, edge_id)


@router.get(
    "/export/graph",
    response_class=Response,
    responses={
        200: {
            "description": "The subgraph as CSV or GraphML.",
            "content": {
                "text/csv": {"schema": {"type": "string"}},
                "application/graphml+xml": {"schema": {"type": "string"}},
            },
        },
        **responses(404, 422, 501),
    },
    operation_id="exportGraph",
)
async def export_graph(
    node: Annotated[str, Query(description="Center node ID.")],
    depth: Annotated[int, Query(ge=1, le=3)] = 1,
    format: Annotated[GraphExportFormat, Query()] = GraphExportFormat.csv,
) -> Response:
    """CSV or GraphML of the subgraph around a node."""
    result = export.export_graph(node, depth=depth, format=format)
    return StreamingResponse(
        result.chunks(),
        media_type=result.media_type,
        headers={"Content-Disposition": f'attachment; filename="{result.filename}"'},
    )
