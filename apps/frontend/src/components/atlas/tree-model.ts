/**
 * Pure data helpers for the Atlas tree (`/atlas/tree.json`): parent/child
 * indexes, ancestors, descendants, real-edge adjacency, counts and local
 * search. No React, no Sigma.
 */
import type { Schemas } from "@/lib/api";

export type AtlasTree = Schemas.AtlasTree;
export type AtlasTreeNode = Schemas.AtlasTreeNode;
export type AtlasTreeEdge = Schemas.AtlasEdge;
export type AtlasCategory = Schemas.AtlasCategory;
export type AtlasCategorySummary = Schemas.AtlasCategorySummary;
export type TreeNodeKind = Schemas.TreeNodeKind;
export type GroupBasis = Schemas.GroupBasis;

export type TreeIndex = {
  tree: AtlasTree;
  rootId: string;
  /** Every tree node (root, categories, groups, entities) by id. */
  nodes: Map<string, AtlasTreeNode>;
  /** Child ids per parent id, in payload order (= layout order). */
  children: Map<string, string[]>;
  /** Category summaries by category id, in angular order. */
  categories: Map<AtlasCategory, AtlasCategorySummary>;
  /** Real edges by id (only edges whose both ends are in the tree). */
  edges: Map<string, AtlasTreeEdge>;
  /** Real edge ids touching each entity id. */
  incident: Map<string, string[]>;
  /** Entity ids linked to each entity id by a real edge. */
  neighbors: Map<string, Set<string>>;
  /** Number of entity nodes (each store node appears exactly once). */
  entityCount: number;
  /** Number of real edges. */
  connectionCount: number;
};

export function buildTreeIndex(tree: AtlasTree): TreeIndex {
  const nodes = new Map<string, AtlasTreeNode>();
  const children = new Map<string, string[]>();
  let entityCount = 0;
  for (const n of tree.nodes) {
    nodes.set(n.id, n);
    if (n.kind === "entity") entityCount += 1;
    if (n.parent_id != null) {
      let list = children.get(n.parent_id);
      if (!list) children.set(n.parent_id, (list = []));
      list.push(n.id);
    }
  }

  const edges = new Map<string, AtlasTreeEdge>();
  const incident = new Map<string, string[]>();
  const neighbors = new Map<string, Set<string>>();
  for (const e of tree.edges) {
    if (!nodes.has(e.source) || !nodes.has(e.target)) continue;
    edges.set(e.id, e);
    for (const [a, b] of [
      [e.source, e.target],
      [e.target, e.source],
    ]) {
      let list = incident.get(a);
      if (!list) incident.set(a, (list = []));
      if (list[list.length - 1] !== e.id) list.push(e.id);
      let set = neighbors.get(a);
      if (!set) neighbors.set(a, (set = new Set()));
      if (a !== b) set.add(b);
    }
  }

  return {
    tree,
    rootId: tree.root_id,
    nodes,
    children,
    categories: new Map(tree.categories.map((c) => [c.id, c])),
    edges,
    incident,
    neighbors,
    entityCount,
    connectionCount: edges.size,
  };
}

/** Tree ancestors of a node, root first, parent last (empty for the root or unknown ids). */
export function ancestorsOf(index: TreeIndex, id: string): AtlasTreeNode[] {
  const out: AtlasTreeNode[] = [];
  let parent = index.nodes.get(id)?.parent_id;
  while (parent != null) {
    const node = index.nodes.get(parent);
    if (!node) break;
    out.push(node);
    parent = node.parent_id;
  }
  return out.reverse();
}

/** Ids of all nodes below `id` (groups and entities, pre-order; `id` itself excluded). */
export function descendantIds(index: TreeIndex, id: string): string[] {
  const out: string[] = [];
  const stack = [...(index.children.get(id) ?? [])].reverse();
  while (stack.length > 0) {
    const next = stack.pop()!;
    out.push(next);
    const kids = index.children.get(next);
    if (kids) for (let i = kids.length - 1; i >= 0; i--) stack.push(kids[i]);
  }
  return out;
}

/** Entity ids in the subtree of `id` (includes `id` when it is an entity). */
export function entityIdsUnder(index: TreeIndex, id: string): string[] {
  const self = index.nodes.get(id);
  const ids = descendantIds(index, id).filter((d) => index.nodes.get(d)?.kind === "entity");
  return self?.kind === "entity" ? [id, ...ids] : ids;
}

/** Real edge ids touching a node (empty for groups). */
export function incidentEdgeIds(index: TreeIndex, id: string): string[] {
  return index.incident.get(id) ?? [];
}

/** Ids linked to a node by a real edge (empty for groups). */
export function neighborIds(index: TreeIndex, id: string): Set<string> {
  return index.neighbors.get(id) ?? new Set();
}

/**
 * Search tree labels and ids locally (no network, no query in a URL), over
 * all tree nodes including groups and categories (not the root, not
 * alphabetical ranges). Prefix and exact-id
 * matches first, then substring matches; within each, larger subtrees and
 * more central entities first.
 */
export function searchTree(index: TreeIndex, query: string, limit = 8): AtlasTreeNode[] {
  const t = query.trim().toLowerCase();
  if (t.length < 1) return [];
  const starts: AtlasTreeNode[] = [];
  const contains: AtlasTreeNode[] = [];
  for (const n of index.nodes.values()) {
    // Alphabetical ranges ("A–Ch") are not meaningful search targets.
    if (n.kind === "root" || n.group_basis === "alpha_range") continue;
    const label = n.label.toLowerCase();
    const id = n.kind === "entity" ? n.id.toLowerCase() : "";
    if (label.startsWith(t) || id === t || (id && id.startsWith(t))) starts.push(n);
    else if (label.includes(t)) contains.push(n);
    if (starts.length >= limit) break;
  }
  const rank = (a: AtlasTreeNode, b: AtlasTreeNode) =>
    b.entity_count - a.entity_count || (b.centrality ?? 0) - (a.centrality ?? 0);
  return [...starts.sort(rank), ...contains.sort(rank)].slice(0, limit);
}
