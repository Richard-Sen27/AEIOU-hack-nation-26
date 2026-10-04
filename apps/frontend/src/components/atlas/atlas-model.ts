/**
 * Pure data helpers for the Atlas: indexes over the `/atlas.json` payload
 * (neighbours, degrees, counts, cluster centroids) and the cluster palette.
 * No React, no Sigma, so it is cheap to test and safe on the server.
 */
import type { Schemas } from "@/lib/api";
import { EDGE_FAMILIES, NODE_TYPES, type EdgeFamily, type NodeType, type Role } from "@/lib/graph/types";

import type { AtlasCategory, TreeIndex } from "./tree-model";

export type AtlasPayload = Schemas.AtlasLayout;
export type AtlasNode = Schemas.AtlasNode;
export type AtlasEdge = Schemas.AtlasEdge;
export type ClusterSummary = Schemas.ClusterSummary;

export type AtlasIndex = {
  nodes: Map<string, AtlasNode>;
  /** Edge ids touching each node. */
  incident: Map<string, string[]>;
  edges: Map<string, AtlasEdge>;
  neighbors: Map<string, Set<string>>;
  typeCounts: Map<NodeType, number>;
  familyCounts: Map<EdgeFamily, number>;
  clusters: Map<string, ClusterSummary & { x: number; y: number; members: number; order: number }>;
  /** Node types present, in canonical order. */
  presentTypes: NodeType[];
  presentFamilies: EdgeFamily[];
};

/** Deterministic fallback position for nodes the pipeline left without x/y. */
export function fallbackPosition(id: string): { x: number; y: number } {
  let h = 2166136261;
  for (let i = 0; i < id.length; i++) h = Math.imul(h ^ id.charCodeAt(i), 16777619);
  const a = ((h >>> 0) % 3600) / 3600;
  const r = (((h >>> 12) % 1000) / 1000) * 100;
  return { x: Math.cos(a * Math.PI * 2) * r, y: Math.sin(a * Math.PI * 2) * r };
}

export function buildAtlasIndex(data: AtlasPayload): AtlasIndex {
  const nodes = new Map<string, AtlasNode>();
  const incident = new Map<string, string[]>();
  const neighbors = new Map<string, Set<string>>();
  const typeCounts = new Map<NodeType, number>();
  const familyCounts = new Map<EdgeFamily, number>();
  const edges = new Map<string, AtlasEdge>();

  for (const n of data.nodes) {
    nodes.set(n.id, n);
    typeCounts.set(n.type, (typeCounts.get(n.type) ?? 0) + 1);
  }
  for (const e of data.edges) {
    if (!nodes.has(e.source) || !nodes.has(e.target)) continue;
    edges.set(e.id, e);
    familyCounts.set(e.family, (familyCounts.get(e.family) ?? 0) + 1);
    for (const [a, b] of [
      [e.source, e.target],
      [e.target, e.source],
    ]) {
      let list = incident.get(a);
      if (!list) incident.set(a, (list = []));
      list.push(e.id);
      let set = neighbors.get(a);
      if (!set) neighbors.set(a, (set = new Set()));
      set.add(b);
    }
  }

  // Cluster label anchors: centroid of member positions.
  const sums = new Map<string, { x: number; y: number; n: number }>();
  for (const n of data.nodes) {
    if (!n.cluster_id || n.type === "cluster") continue;
    const p = n.x != null && n.y != null ? { x: n.x, y: n.y } : fallbackPosition(n.id);
    const s = sums.get(n.cluster_id) ?? { x: 0, y: 0, n: 0 };
    s.x += p.x;
    s.y += p.y;
    s.n += 1;
    sums.set(n.cluster_id, s);
  }
  const clusters: AtlasIndex["clusters"] = new Map();
  const summaries = new Map((data.clusters ?? []).map((c) => [c.id, c]));
  const ids = [...new Set([...summaries.keys(), ...sums.keys()])].sort(clusterSort);
  ids.forEach((id, order) => {
    const s = sums.get(id);
    const node = nodes.get(id);
    const summary = summaries.get(id) ?? {
      id,
      label: node?.label ?? id,
      member_count: s?.n ?? 0,
      origin: "inferred" as const,
    };
    const x = s ? s.x / s.n : (node?.x ?? 0);
    const y = s ? s.y / s.n : (node?.y ?? 0);
    clusters.set(id, { ...summary, x, y, members: s?.n ?? 0, order });
  });

  return {
    nodes,
    incident,
    edges,
    neighbors,
    typeCounts,
    familyCounts,
    clusters,
    presentTypes: NODE_TYPES.filter((t) => typeCounts.has(t)),
    presentFamilies: EDGE_FAMILIES.filter((f) => familyCounts.has(f)),
  };
}

/** CLUSTER:2 before CLUSTER:10. */
export function clusterSort(a: string, b: string) {
  return a.localeCompare(b, "en", { numeric: true });
}

function hslToHex(h: number, s: number, l: number) {
  const a = s * Math.min(l, 1 - l);
  const f = (n: number) => {
    const k = (n + h / 30) % 12;
    const c = l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1));
    return Math.round(c * 255)
      .toString(16)
      .padStart(2, "0");
  };
  return `#${f(0)}${f(8)}${f(4)}`;
}

/**
 * Cluster colours: golden-angle hues, tuned per theme so they stay readable
 * on the background. Colour is never the only signal: cluster names are
 * written on the map and in the side panel.
 */
export function clusterColor(order: number, dark: boolean): string {
  const hue = (order * 137.508 + 28) % 360;
  return dark ? hslToHex(hue, 0.55, 0.62) : hslToHex(hue, 0.6, 0.42);
}

/** `#rrggbb` + alpha → `rgba()`; passes other formats through. */
export function withAlpha(color: string, alpha: number): string {
  const m = /^#([0-9a-f]{6})$/i.exec(color);
  if (!m) return color;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha.toFixed(3)})`;
}

/** Search the atlas labels and ids locally (no network, no query in a URL). */
export function searchAtlas(index: AtlasIndex, q: string, limit = 8): AtlasNode[] {
  const t = q.trim().toLowerCase();
  if (t.length < 1) return [];
  const starts: AtlasNode[] = [];
  const contains: AtlasNode[] = [];
  for (const n of index.nodes.values()) {
    const label = n.label.toLowerCase();
    const id = n.id.toLowerCase();
    if (label.startsWith(t) || id === t || id.startsWith(t)) starts.push(n);
    else if (label.includes(t)) contains.push(n);
    if (starts.length >= limit) break;
  }
  const byCentrality = (a: AtlasNode, b: AtlasNode) => (b.centrality ?? 0) - (a.centrality ?? 0);
  return [...starts.sort(byCentrality), ...contains.sort(byCentrality)].slice(0, limit);
}

/** Edge families and node types present in the tree, with counts (Filters popover and Key). */
export function treeFacets(index: TreeIndex) {
  const familyCounts = new Map<EdgeFamily, number>();
  for (const e of index.edges.values()) familyCounts.set(e.family, (familyCounts.get(e.family) ?? 0) + 1);
  const typeCounts = new Map<NodeType, number>();
  for (const n of index.nodes.values()) {
    if (n.kind === "entity" && n.entity_type) typeCounts.set(n.entity_type, (typeCounts.get(n.entity_type) ?? 0) + 1);
  }
  return {
    familyCounts,
    typeCounts,
    presentFamilies: EDGE_FAMILIES.filter((f) => familyCounts.has(f)),
    presentTypes: NODE_TYPES.filter((t) => typeCounts.has(t)),
  };
}

/** Where the camera starts per lens: guests see the whole map. */
export function lensStartCategory(role: Role): AtlasCategory | null {
  if (role === "patient" || role === "researcher") return "diseases";
  if (role === "doctor") return "symptoms";
  return null;
}
