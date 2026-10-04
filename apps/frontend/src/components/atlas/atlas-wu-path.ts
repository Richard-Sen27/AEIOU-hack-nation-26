/**
 * Dr. Wu's found route on the Atlas: the reply's `graph_focus.highlight_path` holds real edge
 * ids, which need not be links of the tree payload. Their endpoints come from
 * `GET /edge/{id}/evidence` (public graph data, cached); a link whose both ends are on the map is
 * registered in the index's real links, which the canvas draws on demand, so the whole route is
 * drawn. Route nodes that are not on the map are returned with their names for the dock's list.
 *
 * Privacy (docs/compliance.md): only public graph ids are requested, never message text.
 */
import { loadEdge } from "@/components/chat/graph-data";
import type { Schemas } from "@/lib/api";

import type { TreeIndex } from "./tree-model";

export type RouteNode = { id: string; label: string; type: string };

export type Route = {
  /** Route edge ids in path order that can be drawn (both ends on the map). */
  edgeIds: string[];
  /** Every node on the route, in path order. */
  nodes: RouteNode[];
};

type EdgeEvidence = Schemas.EdgeEvidence;

/** Register a route link in the index's real links (both ends must be entities on the map). */
function registerEdge(index: TreeIndex, e: EdgeEvidence): boolean {
  const { edge } = e;
  if (index.edges.has(edge.id)) return true;
  const onMap = (id: string) => index.nodes.get(id)?.kind === "entity";
  if (!onMap(edge.source_id) || !onMap(edge.target_id) || edge.source_id === edge.target_id) return false;
  index.edges.set(edge.id, {
    id: edge.id,
    source: edge.source_id,
    target: edge.target_id,
    relation: edge.relation,
    family: edge.family,
    confidence: edge.confidence,
    origin: edge.origin,
    status: edge.status,
    explanation: edge.explanation ?? null,
  });
  return true;
}

export async function resolveRoute(index: TreeIndex, edgeIds: string[]): Promise<Route> {
  const loaded = await Promise.all(edgeIds.map((id) => loadEdge(id)));
  const drawn: string[] = [];
  const nodes = new Map<string, RouteNode>();
  for (const [i, e] of loaded.entries()) {
    if (!e) {
      // Not loadable: still drawn when the tree payload has it.
      if (index.edges.has(edgeIds[i])) drawn.push(edgeIds[i]);
      continue;
    }
    for (const n of [e.source, e.target]) if (!nodes.has(n.id)) nodes.set(n.id, { id: n.id, label: n.label, type: n.type });
    if (registerEdge(index, e)) drawn.push(e.edge.id);
  }
  return { edgeIds: drawn, nodes: [...nodes.values()] };
}
