/**
 * Pure transform of `GET /atlas/tree.json` into what the landing preview
 * draws: per category one path for the branch lines, one for the group dots
 * and one for the entity dots (27 paths instead of thousands of elements),
 * the category labels at the outer edge, and each entity's real links.
 *
 * Coordinates are the payload's (graph coordinates, y up) flipped to screen
 * (y down) and rounded; positions always come from the backend.
 */
import { ATLAS_CATEGORIES, CATEGORY_META } from "@/components/atlas/atlas-categories";
import type { AtlasCategory, AtlasTree, AtlasTreeEdge } from "@/components/atlas/tree-model";

export type PreviewPoint = {
  id: string;
  x: number;
  y: number;
  label: string;
  category: AtlasCategory | null;
};

export type PreviewLink = {
  edge: AtlasTreeEdge;
  /** The endpoint that is not the focus. */
  other: PreviewPoint;
};

export type PreviewCategory = {
  id: AtlasCategory;
  colorVar: string;
  /** Parent-to-child branch lines. */
  links: string;
  /** Group nodes, drawn as larger dots (zero-length segments with round caps). */
  groups: string;
  /** Entity nodes, drawn as small dots. */
  dots: string;
};

export type PreviewLabel = {
  id: AtlasCategory;
  text: string;
  colorVar: string;
  x: number;
  y: number;
  /** Degrees, tangential to the circle and kept upright. */
  rotate: number;
};

export type Bounds = { minX: number; minY: number; maxX: number; maxY: number };

export type AtlasPreviewModel = {
  bounds: Bounds;
  categories: PreviewCategory[];
  labels: PreviewLabel[];
  points: Map<string, PreviewPoint>;
  /** Real links of an entity, strongest first. */
  linksOf: (id: string) => PreviewLink[];
  /** The patient group (community category) with the most links, if any. */
  topCommunityId: string | null;
  /** The disease with the most links, the hero fallback. */
  topDiseaseId: string | null;
};

const r = Math.round;

function uprightTangent(midAngle: number): number {
  // Screen angle of the radial direction is -mid (y flipped); the tangent is 90 degrees on.
  let deg = (-midAngle * 180) / Math.PI + 90;
  deg = ((deg % 360) + 360) % 360;
  if (deg > 90 && deg <= 270) deg -= 180;
  if (deg > 180) deg -= 360;
  return +deg.toFixed(1);
}

export function buildAtlasPreview(tree: AtlasTree): AtlasPreviewModel {
  const points = new Map<string, PreviewPoint>();
  const parts = new Map<AtlasCategory, { links: string[]; groups: string[]; dots: string[] }>();
  for (const c of ATLAS_CATEGORIES) parts.set(c, { links: [], groups: [], dots: [] });

  for (const n of tree.nodes) {
    points.set(n.id, { id: n.id, x: r(n.x), y: r(-n.y), label: n.label, category: n.category });
  }

  let minX = 0;
  let minY = 0;
  let maxX = 0;
  let maxY = 0;
  for (const n of tree.nodes) {
    const p = points.get(n.id)!;
    minX = Math.min(minX, p.x);
    maxX = Math.max(maxX, p.x);
    minY = Math.min(minY, p.y);
    maxY = Math.max(maxY, p.y);
    if (!n.category || n.kind === "root") continue;
    const bucket = parts.get(n.category);
    if (!bucket) continue;
    const parent = n.parent_id ? points.get(n.parent_id) : undefined;
    if (parent) bucket.links.push(`M${parent.x} ${parent.y}L${p.x} ${p.y}`);
    if (n.kind === "entity") bucket.dots.push(`M${p.x} ${p.y}h0`);
    else bucket.groups.push(`M${p.x} ${p.y}h0`);
  }

  const labels: PreviewLabel[] = [];
  for (const c of tree.categories) {
    const meta = CATEGORY_META[c.id];
    if (!meta) continue;
    const x = r(c.label_x);
    const y = r(-c.label_y);
    labels.push({
      id: c.id,
      text: meta.label.plain,
      colorVar: meta.colorVar,
      x,
      y,
      rotate: uprightTangent((c.angle_start + c.angle_end) / 2),
    });
    minX = Math.min(minX, x);
    maxX = Math.max(maxX, x);
    minY = Math.min(minY, y);
    maxY = Math.max(maxY, y);
  }

  // Real links between entities, indexed by endpoint.
  const incident = new Map<string, AtlasTreeEdge[]>();
  const degree = new Map<string, number>();
  for (const e of tree.edges) {
    if (!points.has(e.source) || !points.has(e.target) || e.source === e.target) continue;
    for (const id of [e.source, e.target]) {
      let list = incident.get(id);
      if (!list) incident.set(id, (list = []));
      list.push(e);
      degree.set(id, (degree.get(id) ?? 0) + 1);
    }
  }

  let topCommunityId: string | null = null;
  let topDiseaseId: string | null = null;
  let bestCommunity = 0;
  let bestDisease = 0;
  for (const n of tree.nodes) {
    if (n.kind !== "entity") continue;
    const d = degree.get(n.id) ?? 0;
    if (n.category === "community" && d > bestCommunity) [bestCommunity, topCommunityId] = [d, n.id];
    if (n.entity_type === "disease" && d > bestDisease) [bestDisease, topDiseaseId] = [d, n.id];
  }

  const sorted = new Map<string, PreviewLink[]>();
  const linksOf = (id: string): PreviewLink[] => {
    let out = sorted.get(id);
    if (!out) {
      out = (incident.get(id) ?? [])
        .map((edge) => ({ edge, other: points.get(edge.source === id ? edge.target : edge.source)! }))
        .sort((a, b) => b.edge.confidence - a.edge.confidence);
      sorted.set(id, out);
    }
    return out;
  };

  return {
    bounds: { minX, minY, maxX, maxY },
    categories: ATLAS_CATEGORIES.map((id) => {
      const b = parts.get(id)!;
      return {
        id,
        colorVar: CATEGORY_META[id].colorVar,
        links: b.links.join(""),
        groups: b.groups.join(""),
        dots: b.dots.join(""),
      };
    }),
    labels,
    points,
    linksOf,
    topCommunityId,
    topDiseaseId,
  };
}

/**
 * A viewBox of the given aspect (width / height) that contains `box` with
 * `pad` (fraction of the larger side) around it, centred on the box.
 */
export function fitViewBox(box: Bounds, aspect: number, pad = 0.04): Bounds {
  const w0 = box.maxX - box.minX || 1;
  const h0 = box.maxY - box.minY || 1;
  let w = w0 * (1 + 2 * pad);
  let h = h0 * (1 + 2 * pad);
  if (w / h < aspect) w = h * aspect;
  else h = w / aspect;
  const cx = (box.minX + box.maxX) / 2;
  const cy = (box.minY + box.maxY) / 2;
  return { minX: cx - w / 2, minY: cy - h / 2, maxX: cx + w / 2, maxY: cy + h / 2 };
}

/**
 * A box centred on the focus node, large enough for most of its strongest links
 * (the 60th percentile endpoint distance of the `limit` strongest), so the
 * neighbourhood fills the frame and far endpoints run off the edge.
 */
export function focusBounds(model: AtlasPreviewModel, id: string, limit = 24): Bounds | null {
  const p = model.points.get(id);
  if (!p) return null;
  const dists = model
    .linksOf(id)
    .slice(0, limit)
    .map(({ other }) => Math.hypot(other.x - p.x, other.y - p.y))
    .sort((a, b) => a - b);
  const reach = Math.max(dists[Math.floor(dists.length * 0.6)] ?? 0, 400);
  return { minX: p.x - reach, minY: p.y - reach, maxX: p.x + reach, maxY: p.y + reach };
}
