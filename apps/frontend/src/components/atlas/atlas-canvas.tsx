"use client";

/**
 * The Sigma.js (WebGL) Atlas: a logo hub with one tree per category.
 * Loaded with `next/dynamic({ ssr: false })` only.
 *
 * Positions come from `/atlas/tree.json` and are never re-laid out here.
 * The graph holds every tree node and tree edge (`tree:<childId>`); real
 * edges are added on demand (selection, chains, Dr. Wu's path) and hidden
 * through the reducer afterwards instead of dropped, so showing and hiding a
 * node's connections never rebuilds the graph. React state stays outside:
 * Sigma's reducers read a ref, one `refresh()` per change.
 */
import { MultiGraph } from "graphology";
import { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useRef } from "react";
import Sigma from "sigma";
import type { EdgeProgramType, NodeProgramType } from "sigma/rendering";
import type { EdgeDisplayData, NodeDisplayData } from "sigma/types";

import type { LabelStyle } from "@/lib/graph/meta";
import { ORIGIN_META } from "@/lib/graph/meta";
import type { GraphTheme } from "@/lib/graph/style";
import type { EdgeFamily, NodeType } from "@/lib/graph/types";

import { CATEGORY_META, categoryColor, categoryLabel, categoryLabelChars, categoryShortLabel } from "./atlas-categories";
import { LABEL_CHAR_SHARE, LABEL_HEIGHT_SHARE, labelFitExtent, mixColor, nodeMinRadius, withAlpha, zoomToSizeRatio } from "./atlas-model";
import type { WuFound } from "./atlas-props";
import { EdgeDashProgram, type DashKind } from "./edge-dash-program";
import { NodeMinCircleProgram } from "./node-min-program";
import { ancestorsOf, descendantIds, type AtlasCategory, type TreeIndex, type TreeNodeKind } from "./tree-model";

export type AtlasCanvasHandle = {
  zoomIn: () => void;
  zoomOut: () => void;
  /** Whole map. */
  reset: () => void;
  /** Frame a node: an entity closely, a group or category with its subtree. */
  focusNode: (id: string) => void;
  /** Frame the endpoints of real edges. */
  focusEdges: (ids: string[]) => void;
  /** Frame a set of nodes. */
  frameNodes: (ids: string[]) => void;
};

type Props = {
  index: TreeIndex;
  theme: GraphTheme;
  labelStyle: LabelStyle;
  /** Edge families drawn when a node is clicked. */
  visibleFamilies: Set<EdgeFamily>;
  selectedId: string | null;
  /** Real edge ids drawn as a chain (`?path=`, a panel item's `via`, Dr. Wu's path). */
  chainEdgeIds: string[];
  /** Dr. Wu's finds: ringed on the map. */
  found: WuFound | null;
  /** Where the camera starts when nothing is focused: the whole map or one category. */
  startCategory: AtlasCategory | null;
  /** Pixels on the right covered by a floating panel; framing centres in the rest. */
  insetRight?: number;
  /** Share of the canvas height covered by a bottom sheet (mobile panel); framing keeps above it. */
  insetBottomShare?: number;
  onSelect: (id: string | null) => void;
  onError?: () => void;
  reducedMotion: boolean;
  labelledBy?: string;
};

const DASH: Record<string, DashKind> = { solid: 0, dashed: 1, dotted: 2 };
const LOGO_PX = 44;
/** Camera ratio below which deeper groups are labelled too. */
const DEEP_LABEL_RATIO = 0.45;

type NodeAttrs = {
  x: number;
  y: number;
  size: number;
  label: string;
  kind: TreeNodeKind;
  depth: number;
  category: AtlasCategory | null;
  entityType: NodeType | null;
  /** Label drawn to the left of the dot (left half of the map: labels point outward). */
  left: boolean;
};
type EdgeAttrs = {
  size: number;
  dash: DashKind;
  /** Tree edge (parent → child) or a real edge. */
  tree: boolean;
  category: AtlasCategory | null;
  /** Tree edge: depth of the child. */
  depth: number;
  family: EdgeFamily | null;
  flagged: boolean;
};

/** Length of the colour fade between two emphasis states (selection, chain, finds). */
const FADE_MS = 220;
/** The fade is quantised so the blended colour strings repeat (Sigma caches parsed colours by string). */
const FADE_STEPS = 16;
const blendCache = new Map<string, string>();
/** `a` → `b` at share `t` (0..1), opaque; quantised to FADE_STEPS. */
function blend(a: string | undefined, b: string | undefined, t: number): string | undefined {
  if (a === b || !a || !b) return b;
  const q = Math.round(t * FADE_STEPS);
  if (q <= 0) return a;
  if (q >= FADE_STEPS) return b;
  const key = `${a}|${b}|${q}`;
  let c = blendCache.get(key);
  if (c === undefined) {
    if (blendCache.size > 50_000) blendCache.clear();
    c = mixColor(a, b, q / FADE_STEPS);
    blendCache.set(key, c);
  }
  return c;
}

/** What is emphasised, derived from props once per change and read by the reducers. */
type Emphasis = {
  /** The selected node drawn with its name box (null when nothing on the map is selected). */
  selected: string | null;
  active: boolean;
  keep: Set<string>;
  /** Labelled first (in this order) where there is room. */
  labelled: Set<string>;
  /** Labelled even when crowded: the selection's tree ancestors. */
  must: Set<string>;
  treeEdges: Set<string>;
  real: Set<string>;
  chain: Set<string>;
  rings: Set<string>;
};

const EMPTY: Emphasis = {
  selected: null,
  active: false,
  keep: new Set(),
  labelled: new Set(),
  must: new Set(),
  treeEdges: new Set(),
  real: new Set(),
  chain: new Set(),
  rings: new Set(),
};

function treePathEdges(index: TreeIndex, id: string, into: Set<string>, nodes?: Set<string>) {
  let cur = index.nodes.get(id);
  while (cur && cur.parent_id != null) {
    into.add(`tree:${cur.id}`);
    nodes?.add(cur.parent_id);
    cur = index.nodes.get(cur.parent_id);
  }
}

function computeEmphasis(p: Props): Emphasis {
  const { index, selectedId, chainEdgeIds, found, visibleFamilies } = p;
  const e: Emphasis = {
    selected: null,
    active: false,
    keep: new Set(),
    labelled: new Set(),
    must: new Set(),
    treeEdges: new Set(),
    real: new Set(),
    chain: new Set(),
    rings: new Set(),
  };
  const sel = selectedId ? index.nodes.get(selectedId) : undefined;
  if (sel && sel.kind !== "root") {
    e.selected = sel.id;
    e.active = true;
    e.keep.add(sel.id);
    e.labelled.add(sel.id);
    e.rings.add(sel.id);
    treePathEdges(index, sel.id, e.treeEdges, e.keep);
    for (const a of ancestorsOf(index, sel.id)) {
      e.labelled.add(a.id);
      e.must.add(a.id);
    }
    if (sel.kind === "entity") {
      const near: string[] = [];
      for (const id of index.incident.get(sel.id) ?? []) {
        const edge = index.edges.get(id);
        if (!edge || !visibleFamilies.has(edge.family) || edge.source === edge.target) continue;
        e.real.add(id);
        const other = edge.source === sel.id ? edge.target : edge.source;
        if (!e.keep.has(other)) near.push(other);
        e.keep.add(other);
      }
      if (near.length <= 12) near.forEach((n) => e.labelled.add(n));
    } else {
      // A group: its direct children are named first.
      for (const c of index.children.get(sel.id) ?? []) e.labelled.add(c);
      for (const d of descendantIds(index, sel.id)) {
        e.keep.add(d);
        e.treeEdges.add(`tree:${d}`);
      }
    }
  }
  const chainIds = [...chainEdgeIds, ...(found?.edgeIds ?? [])];
  for (const id of chainIds) {
    const edge = index.edges.get(id);
    if (!edge) continue;
    e.active = true;
    e.real.add(id);
    e.chain.add(id);
    for (const n of [edge.source, edge.target]) {
      e.keep.add(n);
      e.labelled.add(n);
    }
  }
  if (found && found.nodeIds.length > 0) {
    e.active = true;
    for (const id of found.nodeIds) {
      if (!index.nodes.has(id)) continue;
      e.keep.add(id);
      e.rings.add(id);
      if (found.nodeIds.length <= 40) e.labelled.add(id);
      treePathEdges(index, id, e.treeEdges, e.keep);
    }
  }
  return e;
}

export const AtlasCanvas = forwardRef<AtlasCanvasHandle, Props>(function AtlasCanvas(props, ref) {
  const container = useRef<HTMLDivElement>(null);
  const overlay = useRef<HTMLCanvasElement>(null);
  const labelLayer = useRef<HTMLDivElement>(null);
  const logo = useRef<HTMLButtonElement>(null);
  const sigmaRef = useRef<Sigma<NodeAttrs, EdgeAttrs> | null>(null);
  const emphasis = useRef<Emphasis>(EMPTY);
  /** State the fade starts from, and the fade's eased progress (1 = settled on `emphasis`). */
  const fromEmphasis = useRef<Emphasis>(EMPTY);
  const fade = useRef(1);
  const hoverPath = useRef<Set<string>>(new Set());
  const hovered = useRef<string | null>(null);
  const propsRef = useRef(props);
  const frameRef = useRef<(ids: string[], close?: boolean) => void>(() => {});
  useLayoutEffect(() => {
    propsRef.current = props;
  });

  const animate = (state: { x?: number; y?: number; ratio?: number }) => {
    const sigma = sigmaRef.current;
    if (!sigma) return;
    const camera = sigma.getCamera();
    if (propsRef.current.reducedMotion) camera.setState(state);
    else void camera.animate(state, { duration: 450 });
  };

  /** Whole map, centred in the part of the canvas not covered by the panel. */
  const home = () => {
    const el = container.current;
    const w = el?.clientWidth ?? 1;
    const h = el?.clientHeight ?? 1;
    const inset = Math.min(propsRef.current.insetRight ?? 0, w * 0.5);
    const room = Math.min(w - inset, h) / Math.max(1, Math.min(w, h));
    const ratio = 1 / Math.max(0.5, room);
    return { x: 0.5 + ((inset / 2) * ratio) / Math.max(1, Math.min(w, h)), y: 0.5, ratio };
  };

  useImperativeHandle(ref, () => ({
    zoomIn: () => {
      const c = sigmaRef.current?.getCamera();
      if (c) animate({ ratio: c.getState().ratio / 1.6 });
    },
    zoomOut: () => {
      const c = sigmaRef.current?.getCamera();
      if (c) animate({ ratio: Math.min(c.getState().ratio * 1.6, 1.6) });
    },
    reset: () => animate(home()),
    focusNode: (id: string) => {
      const { index } = propsRef.current;
      const n = index.nodes.get(id);
      if (!n) return;
      if (n.kind === "root") animate(home());
      else if (n.kind === "entity") frameRef.current([id], true);
      else frameRef.current([id, ...descendantIds(index, id)]);
    },
    focusEdges: (ids: string[]) => {
      const { index } = propsRef.current;
      const nodes = ids.flatMap((id) => {
        const e = index.edges.get(id);
        return e ? [e.source, e.target] : [];
      });
      frameRef.current(nodes);
    },
    frameNodes: (ids: string[]) => frameRef.current(ids, ids.length === 1),
  }));

  // Build the graph and the renderer once per payload.
  useEffect(() => {
    const el = container.current;
    if (!el) return;
    const { index } = propsRef.current;
    const graph = new MultiGraph<NodeAttrs, EdgeAttrs>();

    // Largest subtree per category, for trunk thickness and group sizes.
    const catMax = new Map<string, number>();
    for (const n of index.nodes.values()) {
      if (n.kind === "group" && n.category) catMax.set(n.category, Math.max(catMax.get(n.category) ?? 1, n.entity_count));
    }
    let maxCentrality = 0;
    for (const n of index.nodes.values()) if (n.centrality != null) maxCentrality = Math.max(maxCentrality, n.centrality);

    for (const n of index.tree.nodes) {
      let size: number;
      if (n.kind === "root") size = 4;
      else if (n.kind === "category") size = 8;
      else if (n.kind === "group") size = 2.6 + 4 * Math.sqrt(n.entity_count / (catMax.get(n.category ?? "") ?? 1));
      else size = 1.3 + 2.7 * Math.sqrt((n.centrality ?? 0) / (maxCentrality || 1));
      graph.addNode(n.id, {
        x: n.x,
        y: n.y,
        size,
        label: n.label,
        kind: n.kind,
        depth: n.depth,
        category: n.category,
        entityType: n.entity_type,
        left: Math.cos(n.angle) < -0.05,
      });
    }
    for (const n of index.tree.nodes) {
      if (n.parent_id == null || !graph.hasNode(n.parent_id)) continue;
      const share = n.entity_count / (catMax.get(n.category ?? "") ?? n.entity_count);
      const size = n.kind === "category" ? 2.4 : n.kind === "group" ? 0.7 + 1.5 * Math.sqrt(Math.min(1, share)) : 0.5;
      graph.addEdgeWithKey(`tree:${n.id}`, n.parent_id, n.id, {
        size,
        dash: 0,
        tree: true,
        category: n.category,
        depth: n.depth,
        family: null,
        flagged: false,
      });
    }

    /** Adds the real edges the emphasis needs; returns how many were new. */
    const syncRealEdges = () => {
      let added = 0;
      for (const id of emphasis.current.real) {
        if (graph.hasEdge(id)) continue;
        const e = index.edges.get(id);
        if (!e || e.source === e.target || !graph.hasNode(e.source) || !graph.hasNode(e.target)) continue;
        graph.addEdgeWithKey(id, e.source, e.target, {
          size: 1,
          dash: DASH[ORIGIN_META[e.origin]?.line ?? "solid"] ?? 0,
          tree: false,
          category: null,
          depth: 0,
          family: e.family,
          flagged: e.status !== "active",
        });
        added += 1;
      }
      return added;
    };

    // Category colours per theme, resolved once per theme object.
    let colorTheme: GraphTheme | null = null;
    const colors = new Map<
      string,
      { solid: string; group: string; edge: string; trunk: string; dim: string; text: string; dot: string }
    >();
    const palette = (category: AtlasCategory | null) => {
      const t = propsRef.current.theme;
      if (colorTheme !== t) {
        colors.clear();
        colorTheme = t;
      }
      const key = category ?? "";
      let c = colors.get(key);
      if (!c) {
        const solid = category ? categoryColor(category, t) : t.muted;
        // Opaque fades towards the background (Sigma blends premultiplied).
        const bg = t.background;
        c = {
          solid,
          group: mixColor(solid, bg, 0.12),
          edge: mixColor(solid, bg, t.dark ? 0.62 : 0.66),
          trunk: mixColor(solid, bg, t.dark ? 0.35 : 0.4),
          dim: mixColor(solid, bg, 0.9),
          text: mixColor(t.label, solid, 0.4),
          dot: mixColor(t.muted, bg, t.dark ? 0.72 : 0.78),
        };
        colors.set(key, c);
      }
      return c;
    };

    const ratioNow = () => sigmaRef.current?.getCamera().getState().ratio ?? 1;
    /** On-screen radius of a dot as the node program draws it (Sigma's size with a floor when zoomed in). */
    const drawnRadius = (size: number) => Math.max(sigmaRef.current?.scaleSize(size) ?? size, nodeMinRadius(ratioNow()));
    // Dots are sized in screen pixels; on a small canvas the same map needs smaller dots.
    const dotScale = () => Math.min(1, Math.max(0.55, Math.min(el.clientWidth, el.clientHeight) / 700));
    let sizeScale = dotScale();

    // During a fade every item is drawn between its look in the old and the new emphasis state.
    function reduceNode(node: string, data: NodeAttrs & NodeDisplayData): Partial<NodeDisplayData> {
      const to = nodeLook(node, data, emphasis.current);
      const k = fade.current;
      if (k >= 1) return to;
      const from = nodeLook(node, data, fromEmphasis.current);
      return {
        ...to,
        color: blend(from.color, to.color, k),
        size: (from.size ?? 0) + ((to.size ?? 0) - (from.size ?? 0)) * k,
        zIndex: Math.max(from.zIndex ?? 0, to.zIndex ?? 0),
      };
    }

    function reduceEdge(edge: string, data: EdgeAttrs & EdgeDisplayData): Partial<EdgeDisplayData> {
      const to = edgeLook(edge, data, emphasis.current);
      const k = fade.current;
      if (k >= 1) return to;
      const from = edgeLook(edge, data, fromEmphasis.current);
      if (from.hidden && to.hidden) return to;
      // A connection drawn in (or out) grows from a thin line in the background colour.
      const bg = propsRef.current.theme.background;
      const a = from.hidden ? { ...to, color: bg, size: (to.size ?? 1) * 0.3 } : from;
      const b = to.hidden ? { ...from, color: bg, size: (from.size ?? 1) * 0.3 } : to;
      return {
        ...b,
        hidden: false,
        color: blend(a.color, b.color, k),
        size: (a.size ?? 0) + ((b.size ?? 0) - (a.size ?? 0)) * k,
        zIndex: Math.max(a.zIndex ?? 0, b.zIndex ?? 0),
      };
    }

    function nodeLook(node: string, data: NodeAttrs & NodeDisplayData, em: Emphasis): Partial<NodeDisplayData> {
      const t = propsRef.current.theme;
      const res: Partial<NodeDisplayData> & { label?: string | null; left?: boolean } = {
        ...data,
        size: data.size * sizeScale,
      };
      if (data.kind === "root") return { ...res, color: "rgba(0,0,0,0)", label: null, zIndex: 0 };
      const pal = palette(data.category);
      res.color =
        data.kind === "entity" && data.entityType ? (t.node[data.entityType] ?? pal.solid) : data.kind === "group" ? pal.group : pal.solid;
      // Names are drawn on the overlay (categories as HTML); Sigma keeps a label only for the hover box.
      if (data.kind === "category" || (data.kind === "group" && node !== hovered.current)) res.label = null;
      const onHover = hoverPath.current.has(node);
      if (em.active && !em.keep.has(node) && !onHover) {
        res.color = data.kind === "entity" ? pal.dot : pal.dim;
        res.size = data.size * sizeScale * 0.7;
        res.label = null;
        res.zIndex = 0;
        return res;
      }
      res.zIndex = em.active ? 2 : data.kind === "entity" ? 1 : 2;
      // Sigma draws the hover box; the selected dot's name is drawn on the overlay, on top of all names.
      if (node === hovered.current) res.highlighted = true;
      return res;
    }

    function edgeLook(edge: string, data: EdgeAttrs & EdgeDisplayData, em: Emphasis): Partial<EdgeDisplayData> {
      const t = propsRef.current.theme;
      if (data.tree) {
        const pal = palette(data.category);
        const base = data.depth <= 2 ? pal.trunk : pal.edge;
        if (em.treeEdges.has(edge) || hoverPath.current.has(edge)) {
          return { ...data, color: pal.solid, size: data.size * 1.4 + 0.6, zIndex: 3 };
        }
        if (em.active) return { ...data, color: pal.dim, zIndex: 0 };
        return { ...data, color: base, zIndex: 0 };
      }
      if (!em.real.has(edge)) return { hidden: true };
      const color = data.flagged ? t.statusFlag : data.family ? t.edge[data.family] : t.muted;
      if (em.chain.has(edge)) return { ...data, color, size: 3, zIndex: 5 };
      return { ...data, color, size: 1.1, zIndex: 4 };
    }

    let sigma: Sigma<NodeAttrs, EdgeAttrs>;
    try {
      const font = getComputedStyle(document.body).fontFamily || "sans-serif";
      sigma = new Sigma<NodeAttrs, EdgeAttrs>(graph, el, {
        defaultEdgeType: "dash",
        edgeProgramClasses: { dash: EdgeDashProgram as unknown as EdgeProgramType<NodeAttrs, EdgeAttrs> },
        nodeProgramClasses: { circle: NodeMinCircleProgram as unknown as NodeProgramType<NodeAttrs, EdgeAttrs> },
        renderEdgeLabels: false,
        renderLabels: false,
        labelFont: font,
        labelSize: 12,
        labelWeight: "500",
        labelColor: { color: propsRef.current.theme.label },
        zIndex: true,
        minCameraRatio: 0.008,
        maxCameraRatio: 1.6,
        // The tree is large, so selecting zooms far in; capped growth keeps lines thin there.
        zoomToSizeRatioFunction: zoomToSizeRatio,
        stagePadding: 16,
        defaultDrawNodeHover: (ctx, data, settings) => {
          const t = propsRef.current.theme;
          const size = settings.labelSize;
          const left = (data as unknown as NodeAttrs).left;
          const r = Math.max(data.size, nodeMinRadius(ratioNow()));
          ctx.font = `600 ${size}px ${settings.labelFont}`;
          ctx.beginPath();
          ctx.arc(data.x, data.y, r + 3, 0, Math.PI * 2);
          ctx.lineWidth = 2;
          ctx.strokeStyle = t.highlight;
          ctx.stroke();
          if (typeof data.label !== "string" || !data.label) return;
          const w = ctx.measureText(data.label).width;
          const x = left ? data.x - r - 7 - w : data.x + r + 7;
          const h = size + 8;
          ctx.fillStyle = t.dark ? "#1f2725" : "#ffffff";
          ctx.strokeStyle = t.border;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.roundRect(x - 5, data.y - h / 2, w + 10, h, 6);
          ctx.fill();
          ctx.stroke();
          ctx.fillStyle = t.label;
          ctx.fillText(data.label, x, data.y + size / 3);
        },
        nodeReducer: (node, data) => reduceNode(node, data as unknown as NodeAttrs & NodeDisplayData),
        edgeReducer: (edge, data) => reduceEdge(edge, data as unknown as EdgeAttrs & EdgeDisplayData),
      });
    } catch {
      propsRef.current.onError?.();
      return;
    }
    sigmaRef.current = sigma;

    // Frame the tree and the category labels, not just the nodes.
    {
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      const add = (x: number, y: number) => {
        minX = Math.min(minX, x);
        maxX = Math.max(maxX, x);
        minY = Math.min(minY, y);
        maxY = Math.max(maxY, y);
      };
      graph.forEachNode((_, a) => add(a.x, a.y));
      for (const c of index.categories.values()) add(c.label_x, c.label_y);
      // Centred on the hub so the logo sits in the middle; a thin margin keeps the rotated
      // category names inside, and Sigma fits the box to the canvas's aspect, so the map fills it.
      const pad = Math.max(maxX - minX, maxY - minY) * 0.04;
      const halfX = Math.max(Math.abs(minX), Math.abs(maxX)) + pad;
      const halfY = Math.max(Math.abs(minY), Math.abs(maxY)) + pad;
      if (Number.isFinite(halfX) && Number.isFinite(halfY)) sigma.setCustomBBox({ x: [-halfX, halfX], y: [-halfY, halfY] });
    }

    const frame = (ids: string[], close = false) => {
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (const id of ids) {
        if (!graph.hasNode(id)) continue;
        const d = sigma.getNodeDisplayData(id);
        if (!d) continue;
        minX = Math.min(minX, d.x);
        maxX = Math.max(maxX, d.x);
        minY = Math.min(minY, d.y);
        maxY = Math.max(maxY, d.y);
      }
      if (!Number.isFinite(minX)) return;
      const extent = Math.max(maxX - minX, maxY - minY);
      // Keep the framed nodes clear of a floating panel on the right.
      const w = el.clientWidth;
      const h = el.clientHeight;
      const inset = Math.min(propsRef.current.insetRight ?? 0, w * 0.5);
      const below = Math.min(propsRef.current.insetBottomShare ?? 0, 0.7) * h;
      const fit = Math.min(w, h) / Math.max(1, Math.min(w - inset, h - below));
      const ratio = close && extent === 0 ? 0.12 : Math.min(1.2, Math.max(0.05, extent * 1.35 * fit));
      const unit = ratio / Math.max(1, Math.min(w, h));
      animate({ x: (minX + maxX) / 2 + (inset / 2) * unit, y: (minY + maxY) / 2 - (below / 2) * unit, ratio });
    };
    frameRef.current = frame;

    emphasis.current = fromEmphasis.current = computeEmphasis(propsRef.current);
    fade.current = 1;
    syncRealEdges();
    sigma.refresh();

    // Initial camera: `?path=`, then `?focus=`, then the lens's category.
    {
      const p = propsRef.current;
      const set = (fn: () => void) => {
        const motion = p.reducedMotion;
        propsRef.current = { ...p, reducedMotion: true };
        fn();
        propsRef.current = { ...propsRef.current, reducedMotion: motion };
      };
      const chainNodes = p.chainEdgeIds.flatMap((id) => {
        const e = index.edges.get(id);
        return e ? [e.source, e.target] : [];
      });
      const sel = p.selectedId ? index.nodes.get(p.selectedId) : undefined;
      if (chainNodes.length > 0) set(() => frame(chainNodes));
      else if (sel && sel.kind === "entity") set(() => frame([sel.id], true));
      else if (sel && sel.kind !== "root") set(() => frame([sel.id, ...descendantIds(index, sel.id)]));
      else if (p.startCategory) {
        const node = index.categories.get(p.startCategory)?.node_id;
        if (node) set(() => frame([node, ...descendantIds(index, node)]));
      } else sigma.getCamera().setState(home());
    }

    // Hover: emphasise the ancestor path only (partial refresh, no re-index).
    const setHover = (node: string | null) => {
      const prev = hoverPath.current;
      const next = new Set<string>();
      if (node && index.nodes.get(node)?.kind !== "root") {
        next.add(node);
        treePathEdges(index, node, next, next);
      }
      hovered.current = node;
      hoverPath.current = next;
      const nodes: string[] = [];
      const edges: string[] = [];
      for (const k of new Set([...prev, ...next])) {
        if (k.startsWith("tree:")) {
          if (graph.hasEdge(k)) edges.push(k);
        } else if (graph.hasNode(k)) nodes.push(k);
      }
      sigma.refresh({ partialGraph: { nodes, edges }, skipIndexation: true });
    };
    sigma.on("enterNode", ({ node }) => {
      if (index.nodes.get(node)?.kind === "root") return;
      el.style.cursor = "pointer";
      setHover(node);
    });
    sigma.on("leaveNode", () => {
      el.style.cursor = "";
      setHover(null);
    });
    sigma.on("clickNode", ({ node }) => {
      if (index.nodes.get(node)?.kind === "root") {
        propsRef.current.onSelect(null);
        animate(home());
        return;
      }
      propsRef.current.onSelect(node);
    });
    sigma.on("clickStage", () => propsRef.current.onSelect(null));

    // Names of groups and entities, drawn on the overlay with collision avoidance so labels
    // never pile up: selection-related names first, then groups (shallow and large first),
    // then entities (larger dots first) once they are big enough on screen. Deeper groups
    // join when zoomed in. Sigma's own label layer is off; it only draws the hover label.
    const labelOrder = index.tree.nodes
      .filter((n) => n.kind === "group" || n.kind === "entity")
      .sort((a, b) =>
        a.kind !== b.kind
          ? a.kind === "group" ? -1 : 1
          : a.kind === "group"
            ? a.depth - b.depth || b.entity_count - a.entity_count
            : graph.getNodeAttribute(b.id, "size") - graph.getNodeAttribute(a.id, "size"),
      )
      .map((n) => n.id);
    const widths = new Map<string, number>();
    const LABEL_FONT_PX = 11.5;
    const ENTITY_LABEL_MIN_PX = 4.2;
    const MAX_LABELS = 320;
    const CELL = 48;
    /** Box of the label card Sigma's hover style draws for a dot (also used for the selected dot). */
    const nameBox = (ctx: CanvasRenderingContext2D, id: string, font: string) => {
      const n = index.nodes.get(id);
      const d = sigma.getNodeDisplayData(id);
      if (!n || !d || n.kind === "root" || n.kind === "category") return null;
      ctx.font = `600 12px ${font}`;
      const tw = ctx.measureText(n.label).width;
      const p = sigma.framedGraphToViewport(d);
      const r = drawnRadius(d.size);
      const x = graph.getNodeAttribute(id, "left") ? p.x - r - 7 - tw : p.x + r + 7;
      const box: [number, number, number, number] = [x - 6, p.y - 11, x + tw + 6, p.y + 11];
      return { n, x, y: p.y, tw, box };
    };
    const drawSelectedName = (ctx: CanvasRenderingContext2D, id: string | null) => {
      if (!id || id === hovered.current) return;
      const t = propsRef.current.theme;
      const font = getComputedStyle(document.body).fontFamily || "sans-serif";
      const b = nameBox(ctx, id, font);
      if (!b) return;
      ctx.textBaseline = "middle";
      ctx.fillStyle = t.dark ? "#1f2725" : "#ffffff";
      ctx.strokeStyle = t.border;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.roundRect(b.x - 5, b.y - 10, b.tw + 10, 20, 6);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = t.label;
      ctx.fillText(b.n.label, b.x, b.y + 0.5);
    };

    type PlacedLabel = { id: string; text: string; x: number; y: number; group: boolean; category: AtlasCategory | null };
    /** Where the names go for one emphasis state (collision-avoided), without drawing them. */
    const layoutLabels = (
      ctx: CanvasRenderingContext2D,
      w: number,
      h: number,
      blocked: Array<[number, number, number, number]>,
      em: Emphasis,
      font: string,
    ): PlacedLabel[] => {
      const out: PlacedLabel[] = [];
      const ratio = ratioNow();
      // Grid hash of placed boxes, for cheap overlap tests.
      const grid = new Map<number, Array<[number, number, number, number]>>();
      const cells = (b: [number, number, number, number], fn: (k: number) => boolean | void) => {
        for (let cx = Math.floor(b[0] / CELL); cx <= Math.floor(b[2] / CELL); cx++)
          for (let cy = Math.floor(b[1] / CELL); cy <= Math.floor(b[3] / CELL); cy++) if (fn(cx * 4096 + cy)) return true;
        return false;
      };
      const hits = (b: [number, number, number, number]) =>
        cells(b, (k) => grid.get(k)?.some(([a, c, d, e]) => b[0] < d && b[2] > a && b[1] < e && b[3] > c));
      const place = (b: [number, number, number, number]) =>
        void cells(b, (k) => {
          let list = grid.get(k);
          if (!list) grid.set(k, (list = []));
          list.push(b);
        });
      blocked.forEach(place);
      let currentFont = "";
      // The selected and the hovered dot's name boxes win: every other name, the selection's
      // ancestors included, goes around them or is dropped.
      const reserved: Array<[number, number, number, number]> = [];
      for (const id of [em.selected, hovered.current]) {
        const b = id ? nameBox(ctx, id, font) : null;
        if (!b) continue;
        reserved.push(b.box);
        place(b.box);
      }
      const hitsReserved = (b: [number, number, number, number]) =>
        reserved.some(([a, c, d, e]) => b[0] < d && b[2] > a && b[1] < e && b[3] > c);
      const order = em.active ? [...em.labelled, ...labelOrder] : labelOrder;
      const seen = new Set<string>();
      let count = 0;
      for (const id of order) {
        if (count >= MAX_LABELS) break;
        if (seen.has(id)) continue;
        seen.add(id);
        // The hovered and the selected dot get Sigma's label box instead.
        if (id === hovered.current || id === em.selected) continue;
        const n = index.nodes.get(id);
        if (!n || (n.kind !== "group" && n.kind !== "entity")) continue;
        const forced = em.labelled.has(id);
        if (em.active && !forced && !em.keep.has(id)) continue;
        const group = n.kind === "group";
        if (!forced && group && n.depth > 2 && ratio >= DEEP_LABEL_RATIO) continue;
        const d = sigma.getNodeDisplayData(id);
        if (!d || d.hidden) continue;
        const r = drawnRadius(d.size);
        // Names appear with zoom as if dots grew at Sigma's default rate, although their growth is capped.
        if (!forced && !group && d.size / Math.sqrt(ratio) < ENTITY_LABEL_MIN_PX) continue;
        const p = sigma.framedGraphToViewport(d);
        if (p.x < -300 || p.y < -20 || p.x > w + 300 || p.y > h + 20) continue;
        const f = `${group ? 600 : 500} ${LABEL_FONT_PX}px ${font}`;
        if (f !== currentFont) ctx.font = currentFont = f;
        let tw = widths.get(id);
        if (tw === undefined) widths.set(id, (tw = ctx.measureText(n.label).width));
        const left = graph.getNodeAttribute(id, "left");
        // Preferred side first (outward), then the other side.
        let x0 = NaN;
        let box: [number, number, number, number] = [0, 0, 0, 0];
        for (const side of [left, !left]) {
          const x = side ? p.x - r - 4 - tw : p.x + r + 4;
          const b: [number, number, number, number] = [x - 2, p.y - 7, x + tw + 2, p.y + 7];
          if (b[2] < 0 || b[0] > w) continue;
          if (em.must.has(id) ? hitsReserved(b) : hits(b)) continue;
          x0 = x;
          box = b;
          break;
        }
        if (Number.isNaN(x0)) continue;
        place(box);
        count += 1;
        out.push({ id, text: n.label, x: x0, y: p.y, group, category: n.category });
      }
      return out;
    };
    const paintLabels = (ctx: CanvasRenderingContext2D, items: PlacedLabel[], alpha: number, font: string) => {
      if (items.length === 0 || alpha <= 0) return;
      const t = propsRef.current.theme;
      ctx.globalAlpha = alpha;
      ctx.lineJoin = "round";
      ctx.textBaseline = "middle";
      ctx.lineWidth = 3;
      ctx.strokeStyle = t.background;
      let currentFont = "";
      for (const l of items) {
        const f = `${l.group ? 600 : 500} ${LABEL_FONT_PX}px ${font}`;
        if (f !== currentFont) ctx.font = currentFont = f;
        ctx.strokeText(l.text, l.x, l.y);
        ctx.fillStyle = l.group ? palette(l.category).text : t.label;
        ctx.fillText(l.text, l.x, l.y);
      }
      ctx.globalAlpha = 1;
    };
    let fadeLabels: { key: string; from: Emphasis; to: Emphasis; prev: PlacedLabel[]; next: PlacedLabel[] } | null = null;
    /** Names for the settled state, or cross-faded between the old and the new state during a fade. */
    const drawLabels = (ctx: CanvasRenderingContext2D, w: number, h: number, blocked: Array<[number, number, number, number]>) => {
      const font = getComputedStyle(document.body).fontFamily || "sans-serif";
      const k = fade.current;
      if (k >= 1) {
        fadeLabels = null;
        paintLabels(ctx, layoutLabels(ctx, w, h, blocked, emphasis.current, font), 1, font);
        return;
      }
      // During a fade both layouts are computed once and reused while the camera stands still.
      const cam = sigma.getCamera().getState();
      const key = `${cam.x}|${cam.y}|${cam.ratio}|${cam.angle}|${w}|${h}|${hovered.current}`;
      if (!fadeLabels || fadeLabels.key !== key || fadeLabels.from !== fromEmphasis.current || fadeLabels.to !== emphasis.current) {
        fadeLabels = {
          key,
          from: fromEmphasis.current,
          to: emphasis.current,
          prev: layoutLabels(ctx, w, h, blocked, fromEmphasis.current, font),
          next: layoutLabels(ctx, w, h, blocked, emphasis.current, font),
        };
      }
      const { prev, next } = fadeLabels;
      const at = new Map(prev.map((l) => [l.id, l]));
      const both: PlacedLabel[] = [];
      const fresh: PlacedLabel[] = [];
      const kept = new Set<string>();
      for (const l of next) {
        const p = at.get(l.id);
        if (p && p.x === l.x && p.y === l.y) {
          both.push(l);
          kept.add(l.id);
        } else fresh.push(l);
      }
      paintLabels(ctx, both, 1, font);
      paintLabels(
        ctx,
        prev.filter((l) => !kept.has(l.id)),
        1 - k,
        font,
      );
      paintLabels(ctx, fresh, k, font);
    };

    // Category labels (HTML, rotated along the outer edge) and the logo on the hub.
    const layer = labelLayer.current;
    const labelEls = new Map<string, HTMLDivElement>();
    const LABEL_CLASS = "whitespace-nowrap font-heading font-semibold leading-none tracking-[0.01em]";
    // Each name is drawn inside the box the layout keeps free for it (no node, no other name):
    // its size follows the map, capped when zoomed in; small canvases switch to a short name.
    const fitExtent = labelFitExtent(index);
    const LABEL_MAX_PX = 17;
    const LABEL_READABLE_PX = 9.5;
    const measure = document.createElement("span");
    measure.className = `${LABEL_CLASS} pointer-events-none invisible absolute top-0 left-0`;
    measure.style.fontSize = "100px";
    const widthPerPx = new Map<string, number>();
    const textWidth = (text: string) => {
      let w = widthPerPx.get(text);
      if (w === undefined) {
        measure.textContent = text;
        w = measure.getBoundingClientRect().width / 100;
        if (w > 0) widthPerPx.set(text, w);
      }
      return w || text.length * 0.75;
    };
    if (layer) {
      layer.replaceChildren(measure);
      for (const c of index.categories.values()) {
        const d = document.createElement("div");
        d.className = `absolute top-0 left-0 ${LABEL_CLASS}`;
        d.style.color = `color-mix(in oklab, var(${CATEGORY_META[c.id].colorVar}) 80%, var(--foreground))`;
        d.style.textShadow = "0 0 3px var(--background), 0 0 6px var(--background)";
        d.dataset.testid = "atlas-category-label";
        d.setAttribute("data-testid", "atlas-category-label");
        d.dataset.category = c.id;
        layer.appendChild(d);
        labelEls.set(c.id, d);
      }
    }
    const placeOverlays = () => {
      const { labelStyle } = propsRef.current;
      const origin = sigma.graphToViewport({ x: 0, y: 0 });
      const unit = sigma.graphToViewport({ x: 1000, y: 0 });
      const pxPerUnit = Math.hypot(unit.x - origin.x, unit.y - origin.y) / 1000;
      const boxH = LABEL_HEIGHT_SHARE * fitExtent * pxPerUnit;
      // Pick each name (short where the full one would be unreadable) and its largest fitting
      // size; all names share one size unless their box forces one smaller.
      const picks = new Map<string, { text: string; size: number }>();
      let common = LABEL_MAX_PX;
      for (const c of index.categories.values()) {
        const boxW = categoryLabelChars(c.id) * LABEL_CHAR_SHARE * fitExtent * pxPerUnit;
        // Mixed case: ascender to baseline is about 0.75 of the font size (few descenders).
        const fit = (t: string) => Math.min(LABEL_MAX_PX, boxH / 0.95, boxW / textWidth(t));
        let text = categoryLabel(c.id, labelStyle);
        let size = fit(text);
        if (size < LABEL_READABLE_PX) {
          const short = categoryShortLabel(c.id, labelStyle);
          const shortSize = fit(short);
          if (shortSize > size) {
            text = short;
            size = shortSize;
          }
        }
        picks.set(c.id, { text, size });
        common = Math.min(common, size);
      }
      common = Math.max(common, LABEL_READABLE_PX);
      for (const c of index.categories.values()) {
        const d = labelEls.get(c.id);
        const pick = picks.get(c.id);
        if (!d || !pick) continue;
        const { text } = pick;
        const size = Math.min(pick.size, common);
        if (d.textContent !== text) d.textContent = text;
        d.style.fontSize = `${size.toFixed(2)}px`;
        // The layout writes the name along the tangent at the label's own angle.
        const mid = Math.atan2(c.label_y, c.label_x);
        const p = sigma.graphToViewport({ x: c.label_x, y: c.label_y });
        const dir = sigma.graphToViewport({ x: Math.cos(mid) * 100, y: Math.sin(mid) * 100 });
        // Text runs along the tangent of the outer edge; flipped where it would read upside down.
        let rot = (Math.atan2(dir.y - origin.y, dir.x - origin.x) * 180) / Math.PI + 90;
        rot = ((rot + 540) % 360) - 180;
        if (rot > 90) rot -= 180;
        else if (rot < -90) rot += 180;
        d.style.transform = `translate(${p.x}px, ${p.y}px) translate(-50%, -50%) rotate(${rot.toFixed(1)}deg)`;
      }
      const btn = logo.current;
      if (btn) {
        const px = Math.round(Math.min(84, Math.max(32, LOGO_PX / Math.pow(sigma.getCamera().getState().ratio, 0.35))));
        btn.style.width = btn.style.height = `${px}px`;
        btn.style.padding = `${Math.round(px * 0.14)}px`;
        btn.style.transform = `translate(${origin.x}px, ${origin.y}px) translate(-50%, -50%)`;
      }
      drawRings();
    };

    // Rings around the selection and Dr. Wu's finds (2D overlay, few items).
    const drawRings = () => {
      const cvs = overlay.current;
      if (!cvs) return;
      const dpr = window.devicePixelRatio || 1;
      const w = el.clientWidth;
      const h = el.clientHeight;
      if (cvs.width !== Math.round(w * dpr) || cvs.height !== Math.round(h * dpr)) {
        cvs.width = Math.round(w * dpr);
        cvs.height = Math.round(h * dpr);
        cvs.style.width = `${w}px`;
        cvs.style.height = `${h}px`;
      }
      const ctx = cvs.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      // Category names are never covered by group names.
      const host = el.getBoundingClientRect();
      const blocked: Array<[number, number, number, number]> = [];
      for (const d of labelEls.values()) {
        const r = d.getBoundingClientRect();
        blocked.push([r.left - host.left, r.top - host.top, r.right - host.left, r.bottom - host.top]);
      }
      drawLabels(ctx, w, h, blocked);
      const k = fade.current;
      const next = emphasis.current;
      const prev = fromEmphasis.current;
      if (k < 1) {
        // Rings and the name box of the old state fade out, the new ones fade in.
        ctx.globalAlpha = 1 - k;
        drawRingSet(ctx, w, h, prev, next.rings);
        if (prev.selected !== next.selected) drawSelectedName(ctx, prev.selected);
        ctx.globalAlpha = k;
        drawRingSet(ctx, w, h, next, prev.rings);
        if (prev.selected !== next.selected) drawSelectedName(ctx, next.selected);
        ctx.globalAlpha = 1;
        drawRingSet(ctx, w, h, next, null, prev.rings);
        if (prev.selected === next.selected) drawSelectedName(ctx, next.selected);
        return;
      }
      drawRingSet(ctx, w, h, next);
      drawSelectedName(ctx, next.selected);
    };
    /** Rings of one state; `skip` leaves out ids, `only` keeps just those. */
    const drawRingSet = (
      ctx: CanvasRenderingContext2D,
      w: number,
      h: number,
      em: Emphasis,
      skip: Set<string> | null = null,
      only: Set<string> | null = null,
    ) => {
      const { theme: t, found } = propsRef.current;
      const selectedId = em.selected;
      const foundSet = new Set(found?.nodeIds ?? []);
      for (const id of em.rings) {
        if (skip?.has(id) || (only && !only.has(id))) continue;
        if (!graph.hasNode(id)) continue;
        const a = graph.getNodeAttributes(id);
        const d = sigma.getNodeDisplayData(id);
        if (!d) continue;
        const p = sigma.graphToViewport({ x: a.x, y: a.y });
        if (p.x < -20 || p.y < -20 || p.x > w + 20 || p.y > h + 20) continue;
        const r = drawnRadius(d.size) + 5;
        ctx.beginPath();
        ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
        ctx.lineWidth = id === selectedId ? 2.5 : 2;
        ctx.strokeStyle = foundSet.has(id) && id !== selectedId ? t.statusFlag : t.highlight;
        ctx.stroke();
        if (foundSet.has(id)) {
          ctx.beginPath();
          ctx.arc(p.x, p.y, r + 4, 0, Math.PI * 2);
          ctx.lineWidth = 1;
          ctx.strokeStyle = withAlpha(t.statusFlag.startsWith("#") ? t.statusFlag : t.highlight, 0.45);
          ctx.stroke();
        }
      }
    };
    sigma.on("resize", () => {
      const next = dotScale();
      if (Math.abs(next - sizeScale) > 0.02) {
        sizeScale = next;
        sigma.refresh({ schedule: true });
      }
    });
    sigma.on("afterRender", placeOverlays);
    placeOverlays();
    // A change of emphasis fades over FADE_MS: one eased value read by the reducers. Frames in
    // between re-run the reducers only (partial refresh, no re-index, Sigma's own render loop);
    // the first and the last frame are full refreshes (new edges, draw order). Nothing renders
    // once the fade has settled.
    const treeEdgeIds = graph.filterEdges((_, a) => a.tree);
    let fadeFrame = 0;
    const settle = () => {
      fadeFrame = 0;
      fade.current = 1;
      fromEmphasis.current = emphasis.current;
    };
    restyle.current = () => {
      cancelAnimationFrame(fadeFrame);
      const prev = emphasis.current;
      emphasis.current = computeEmphasis(propsRef.current);
      const added = syncRealEdges();
      sigma.setSetting("labelColor", { color: propsRef.current.theme.label });
      if (propsRef.current.reducedMotion || prev === emphasis.current) {
        settle();
        sigma.refresh();
        return;
      }
      fromEmphasis.current = prev;
      fade.current = 0;
      // New edges need indexing once; otherwise the fade starts on partial refreshes straight away.
      if (added > 0) sigma.refresh();
      const nodes = graph.nodes();
      const edges = [...treeEdgeIds, ...new Set([...prev.real, ...emphasis.current.real])].filter((id) => graph.hasEdge(id));
      const start = performance.now();
      const step = (now: number) => {
        const p = Math.min(1, (now - start) / FADE_MS);
        if (p >= 1) {
          settle();
          sigma.refresh({ schedule: true });
          return;
        }
        // Ease-out (cubic).
        fade.current = 1 - Math.pow(1 - p, 3);
        sigma.refresh({ partialGraph: { nodes, edges }, skipIndexation: true, schedule: true });
        fadeFrame = requestAnimationFrame(step);
      };
      fadeFrame = requestAnimationFrame(step);
    };

    return () => {
      cancelAnimationFrame(fadeFrame);
      restyle.current = null;
      sigma.kill();
      sigmaRef.current = null;
      layer?.replaceChildren();
    };
  }, [props.index]);

  const restyle = useRef<(() => void) | null>(null);

  // Re-style on any visual input change (one refresh; real edges added, never rebuilt).
  useEffect(() => {
    restyle.current?.();
  }, [props.theme, props.labelStyle, props.visibleFamilies, props.selectedId, props.chainEdgeIds, props.found]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    const sigma = sigmaRef.current;
    if (!sigma) return;
    const camera = sigma.getCamera();
    const s = camera.getState();
    const step = 0.08 * s.ratio;
    const move: Record<string, Partial<typeof s>> = {
      ArrowLeft: { x: s.x - step },
      ArrowRight: { x: s.x + step },
      ArrowUp: { y: s.y + step },
      ArrowDown: { y: s.y - step },
      "+": { ratio: s.ratio / 1.4 },
      "=": { ratio: s.ratio / 1.4 },
      "-": { ratio: Math.min(s.ratio * 1.4, 1.6) },
      "0": home(),
    };
    if (move[e.key]) {
      e.preventDefault();
      // A short glide per key press; held keys stay responsive because each press starts afresh.
      if (props.reducedMotion) camera.setState({ ...s, ...move[e.key] });
      else void camera.animate({ ...s, ...move[e.key] }, { duration: 160, easing: "quadraticOut" });
    } else if (e.key === "Escape") {
      props.onSelect(null);
    }
  };

  return (
    <div className="relative size-full overflow-hidden">
      <div
        ref={container}
        className="size-full outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
        tabIndex={0}
        role="img"
        aria-roledescription="interactive map"
        aria-labelledby={props.labelledBy}
        onKeyDown={onKeyDown}
        data-testid="atlas-canvas"
      />
      <canvas ref={overlay} className="pointer-events-none absolute inset-0" aria-hidden />
      <div ref={labelLayer} className="pointer-events-none absolute inset-0" aria-hidden />
      <button
        ref={logo}
        type="button"
        onClick={() => {
          props.onSelect(null);
          animate(home());
        }}
        aria-label="Show the whole map"
        title="Show the whole map"
        className="absolute top-0 left-0 flex size-16 items-center justify-center rounded-full border bg-card p-2 shadow-md outline-none hover:ring-2 hover:ring-primary/40 focus-visible:ring-2 focus-visible:ring-ring"
        data-testid="atlas-logo"
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- scaled every frame with the camera */}
        <img src="/amber-logo-128.png" alt="" className="size-full object-contain" draggable={false} />
      </button>
    </div>
  );
});

export default AtlasCanvas;
