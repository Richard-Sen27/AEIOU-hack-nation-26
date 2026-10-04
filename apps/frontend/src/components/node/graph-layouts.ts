/**
 * Deterministic neighbourhood layouts for the node graph. Pure functions over
 * plain data so every layout can be checked without a renderer.
 *
 * Rule for all of them: no line of more than a readable number of nodes. A
 * big group of neighbours of the same type joined by the same relation (48
 * authors of a paper) becomes one compact block with a caption naming it once
 * ("48 researchers · wrote"); everything else keeps a labelled place.
 */

export type Point = { x: number; y: number };

/** One neighbour. `rank`: 0 direct and in a highlighted family, 1 direct, 2 not linked to the centre. */
export type LayoutItem = { id: string; type: string; relation: string | null; rank: 0 | 1 | 2 };

export type LayoutGroup = {
  key: string;
  type: string;
  relation: string;
  ids: string[];
  /** Compact blocks hide member labels (names on hover); labelled blocks keep them. */
  compact: boolean;
  caption: Point;
};

export type Placement = { positions: Record<string, Point>; groups: LayoutGroup[] };

export type LayoutMode = "ring" | "hierarchy" | "cluster";

export const LABEL_WIDTH = 110;
/** A group this big always becomes a block, in every layout. */
export const BIG_GROUP = 12;
/** Widest line of nodes in any layout. */
export const MAX_PER_LINE = 10;

const CELL = 30;
const LABELLED_CELL = { x: LABEL_WIDTH + 20, y: 54 };
const CAPTION_GAP = 26;
const CAPTION_WIDTH = 190;
const BLOCK_GAP = 64;
/** Room under the centre node for its label, before a lone block's caption. */
const CENTER_LABEL_ROOM = 40;

/** Distance between neighbours on a ring: one label width while labels fit, tighter for big hubs. */
export function ringArc(count: number) {
  return count <= 40 ? LABEL_WIDTH + 24 : count <= 120 ? 64 : 40;
}

type Block = { ids: string[]; compact: boolean; cols: number; rows: number; w: number; h: number };

function block(ids: string[], compact: boolean): Block {
  const n = ids.length;
  const cols = compact ? Math.min(MAX_PER_LINE, Math.max(2, Math.ceil(Math.sqrt(n * 1.8)))) : Math.min(3, n);
  const rows = Math.ceil(n / cols);
  const cell = compact ? { x: CELL, y: CELL } : LABELLED_CELL;
  const w = Math.max((cols - 1) * cell.x + (compact ? 20 : LABEL_WIDTH), CAPTION_WIDTH);
  const h = (rows - 1) * cell.y + CAPTION_GAP + (compact ? 20 : 40);
  return { ids, compact, cols, rows, w, h };
}

/** Grid of a block's members centred on (cx, cy) of the whole block, caption above. */
function placeBlock(b: Block, cx: number, cy: number, positions: Record<string, Point>): Point {
  const cell = b.compact ? { x: CELL, y: CELL } : LABELLED_CELL;
  const top = cy - b.h / 2;
  const gridTop = top + CAPTION_GAP + 8;
  b.ids.forEach((id, i) => {
    const row = Math.floor(i / b.cols);
    // Centre a short last row.
    const inRow = row === b.rows - 1 ? b.ids.length - row * b.cols : b.cols;
    const col = i % b.cols;
    positions[id] = { x: cx + (col - (inRow - 1) / 2) * cell.x, y: gridTop + row * cell.y };
  });
  return { x: cx, y: top };
}

/** Group direct neighbours by type and relation; groups of `min` or more become blocks. */
export function groupItems(items: LayoutItem[], min: number) {
  const byKey = new Map<string, LayoutItem[]>();
  for (const it of items) {
    if (it.rank === 2 || !it.relation) continue;
    const key = `${it.type}|${it.relation}`;
    byKey.set(key, [...(byKey.get(key) ?? []), it]);
  }
  const grouped = new Set<string>();
  const groups = [...byKey.entries()]
    .filter(([, list]) => list.length >= min)
    .map(([key, list]) => {
      list.forEach((it) => grouped.add(it.id));
      return { key, type: list[0].type, relation: list[0].relation!, ids: list.map((it) => it.id), rank: Math.min(...list.map((it) => it.rank)) };
    })
    .sort((a, b) => a.rank - b.rank || b.ids.length - a.ids.length || a.key.localeCompare(b.key));
  const loose = items.filter((it) => !grouped.has(it.id)).sort((a, b) => a.rank - b.rank);
  return { groups, loose };
}

/** Rings around the centre, each holding as many nodes as fit one arc apart. Returns the outer radius used. */
function ringsAround(ids: string[], positions: Record<string, Point>): number {
  const count = ids.length;
  if (!count) return 40;
  const arc = ringArc(count);
  const gap = count <= 40 ? 96 : 52;
  let radius = count <= 8 ? 120 : 140;
  let placed = 0;
  let ring = 0;
  let outer = radius;
  while (placed < count) {
    const capacity = Math.max(4, Math.floor((2 * Math.PI * radius) / arc));
    const onRing = Math.min(count - placed, capacity);
    const offset = ring % 2 ? Math.PI / onRing : 0;
    for (let i = 0; i < onRing; i++) {
      const a = -Math.PI / 2 + offset + (2 * Math.PI * i) / onRing;
      positions[ids[placed + i]] = { x: radius * Math.cos(a), y: radius * Math.sin(a) };
    }
    placed += onRing;
    outer = radius;
    radius += gap;
    ring += 1;
  }
  return outer + 30;
}

/** Blocks on a circle around the inner rings, far enough apart not to touch each other or the rings. */
function blocksAround(blocks: Block[], inner: number, positions: Record<string, Point>): Point[] {
  const k = blocks.length;
  if (!k) return [];
  const radii = blocks.map((b) => Math.hypot(b.w / 2, b.h / 2));
  const maxb = Math.max(...radii);
  if (k === 1) {
    // One block: below the centre, so the few other neighbours stand out above it. A tall
    // block is shown zoomed out, where the centre's label grows (it keeps a readable size on
    // screen): keep about a sixth of the block's height free under the centre for it, so the
    // label does not cover the block's caption.
    const b = blocks[0];
    const gap = Math.max(inner + BLOCK_GAP / 2, CENTER_LABEL_ROOM + b.h / 6);
    return [placeBlock(b, 0, gap + b.h / 2, positions)];
  }
  const R = Math.max(inner + BLOCK_GAP / 2 + maxb, (2 * maxb + BLOCK_GAP) / (2 * Math.sin(Math.PI / k)));
  return blocks.map((b, i) => {
    const a = Math.PI / 2 + (2 * Math.PI * i) / k;
    return placeBlock(b, R * Math.cos(a), R * Math.sin(a), positions);
  });
}

/** Wrapped, evenly filled rows centred under y; returns the y below the last row. */
function rows(ids: string[], y: number, positions: Record<string, Point>): number {
  if (!ids.length) return y;
  const roomy = ids.length <= 40;
  const max = roomy ? 7 : MAX_PER_LINE;
  const perRow = Math.ceil(ids.length / Math.ceil(ids.length / max));
  const dx = roomy ? LABEL_WIDTH + 20 : 44;
  const dy = roomy ? 70 : 40;
  for (let i = 0; i < ids.length; i += perRow) {
    const line = ids.slice(i, i + perRow);
    line.forEach((id, j) => (positions[id] = { x: (j - (line.length - 1) / 2) * dx, y }));
    y += dy;
  }
  return y + 20;
}

/** Blocks packed left to right in shelves no wider than `limit`, each shelf centred. */
function shelves(blocks: Block[], y: number, limit: number, positions: Record<string, Point>): { captions: Point[]; y: number } {
  const captions: Point[] = new Array(blocks.length);
  let i = 0;
  while (i < blocks.length) {
    const shelf: number[] = [];
    let width = 0;
    while (i < blocks.length && (shelf.length === 0 || width + BLOCK_GAP + blocks[i].w <= limit)) {
      width += (shelf.length ? BLOCK_GAP : 0) + blocks[i].w;
      shelf.push(i++);
    }
    const height = Math.max(...shelf.map((j) => blocks[j].h));
    let x = -width / 2;
    for (const j of shelf) {
      const b = blocks[j];
      captions[j] = placeBlock(b, x + b.w / 2, y + b.h / 2, positions);
      x += b.w + BLOCK_GAP;
    }
    y += height + BLOCK_GAP;
  }
  return { captions, y };
}

/** How many neighbours keep a labelled place (not in a compact block): the label density follows this. */
export function labelledCount(placement: Placement, total: number) {
  return total - placement.groups.filter((g) => g.compact).reduce((n, g) => n + g.ids.length, 0);
}

export function placeNeighbourhood(centerId: string, items: LayoutItem[], mode: LayoutMode): Placement {
  const positions: Record<string, Point> = { [centerId]: { x: 0, y: 0 } };
  // Clusters group every shared type and relation; the other layouts only the big groups.
  const { groups, loose } = groupItems(items, mode === "cluster" ? 2 : BIG_GROUP);
  const blocks = groups.map((g) => block(g.ids, g.ids.length >= BIG_GROUP));
  let captions: Point[];
  if (mode === "hierarchy") {
    const direct = loose.filter((it) => it.rank < 2).map((it) => it.id);
    const far = loose.filter((it) => it.rank === 2).map((it) => it.id);
    let y = rows(direct, 110, positions);
    const packed = shelves(blocks, direct.length ? y : 110, 900, positions);
    captions = packed.captions;
    y = packed.y;
    rows(far, y, positions);
  } else {
    const inner = ringsAround(
      loose.map((it) => it.id),
      positions,
    );
    captions = blocksAround(blocks, inner, positions);
  }
  return {
    positions,
    groups: groups.map((g, i) => ({ key: g.key, type: g.type, relation: g.relation, ids: g.ids, compact: blocks[i].compact, caption: captions[i] })),
  };
}
