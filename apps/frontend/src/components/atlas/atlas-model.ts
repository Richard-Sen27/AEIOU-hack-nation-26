/**
 * Small pure helpers for the Atlas view and canvas: facets for the Filters
 * popover, the lens's starting category and colour mixing. Tree indexes
 * live in `tree-model.ts`. No React, no Sigma.
 */
import { EDGE_FAMILIES, NODE_TYPES, type EdgeFamily, type NodeType, type Role } from "@/lib/graph/types";

import type { AtlasCategory, TreeIndex } from "./tree-model";

/** `#rrggbb` + alpha → `rgba()`; passes other formats through. */
export function withAlpha(color: string, alpha: number): string {
  const m = /^#([0-9a-f]{6})$/i.exec(color);
  if (!m) return color;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha.toFixed(3)})`;
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

function parseRgb(color: string): [number, number, number] | null {
  const hex = /^#([0-9a-f]{6})$/i.exec(color);
  if (hex) {
    const n = parseInt(hex[1], 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  const rgb = /^rgba?\(\s*(\d+),\s*(\d+),\s*(\d+)/i.exec(color);
  return rgb ? [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])] : null;
}

/**
 * Opaque mix of two colours (`t` = share of `b`). Sigma blends with
 * premultiplied alpha, so translucent colours turn light on any background;
 * the Atlas fades tree lines and dimmed dots towards the background instead.
 */
export function mixColor(a: string, b: string, t: number): string {
  const x = parseRgb(a);
  const y = parseRgb(b);
  if (!x || !y) return a;
  const c = x.map((v, i) => Math.round(v + (y[i] - v) * t));
  return `#${c.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}
