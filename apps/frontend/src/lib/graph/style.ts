/**
 * Graph style helpers shared by the three renderers:
 * Sigma (WebGL, needs rgb/hex), Cytoscape (canvas, rgb/hex) and
 * React Flow (DOM, can use CSS vars directly).
 *
 * Colours come from the CSS tokens in globals.css so light and dark both
 * work; call `readGraphTheme()` again (or use `useGraphTheme()`) after a
 * theme change.
 */
import { EDGE_FAMILY_META, NODE_TYPE_META, ORIGIN_META, confidenceLevel } from "./meta";
import {
  EDGE_FAMILIES,
  NODE_TYPES,
  type EdgeFamily,
  type EdgeStatus,
  type GraphEdge,
  type NodeType,
  type Origin,
} from "./types";

export type GraphTheme = {
  node: Record<NodeType, string>;
  edge: Record<EdgeFamily, string>;
  highlight: string;
  dim: string;
  label: string;
  background: string;
  muted: string;
  border: string;
  statusFlag: string;
  confidence: { high: string; medium: string; low: string };
  dark: boolean;
};

/** CSS `var()` reference for DOM renderers (React Flow, legends). */
export const nodeColorVar = (type: NodeType) => `var(${NODE_TYPE_META[type].colorVar})`;
export const edgeColorVar = (family: EdgeFamily) => `var(${EDGE_FAMILY_META[family].colorVar})`;

let canvasCtx: CanvasRenderingContext2D | null = null;

/** Resolve any CSS colour (oklch, color-mix, var()) to `#rrggbb` or `rgba()`. */
export function resolveCssColor(value: string, scope: Element = document.documentElement): string {
  const probe = document.createElement("span");
  probe.style.color = value;
  probe.style.display = "none";
  scope.appendChild(probe);
  const computed = getComputedStyle(probe).color;
  probe.remove();
  canvasCtx ??= (() => {
    const c = document.createElement("canvas");
    c.width = c.height = 1;
    return c.getContext("2d", { willReadFrequently: true });
  })();
  if (!canvasCtx) return computed;
  canvasCtx.clearRect(0, 0, 1, 1);
  canvasCtx.fillStyle = computed;
  canvasCtx.fillRect(0, 0, 1, 1);
  const [r, g, b, a] = canvasCtx.getImageData(0, 0, 1, 1).data;
  if (a === 255) {
    return `#${[r, g, b].map((n) => n.toString(16).padStart(2, "0")).join("")}`;
  }
  return `rgba(${r}, ${g}, ${b}, ${(a / 255).toFixed(3)})`;
}

/** Read all graph colours from the current theme. Browser only. */
export function readGraphTheme(scope: Element = document.documentElement): GraphTheme {
  const c = (v: string) => resolveCssColor(`var(${v})`, scope);
  return {
    node: Object.fromEntries(
      NODE_TYPES.map((t) => [t, c(NODE_TYPE_META[t].colorVar)]),
    ) as Record<NodeType, string>,
    edge: Object.fromEntries(
      EDGE_FAMILIES.map((f) => [f, c(EDGE_FAMILY_META[f].colorVar)]),
    ) as Record<EdgeFamily, string>,
    highlight: c("--graph-highlight"),
    dim: c("--graph-dim"),
    label: c("--graph-label"),
    background: c("--graph-bg"),
    muted: c("--muted-foreground"),
    border: c("--border"),
    statusFlag: c("--status-flag"),
    confidence: {
      high: c("--confidence-high"),
      medium: c("--confidence-medium"),
      low: c("--confidence-low"),
    },
    dark: document.documentElement.classList.contains("dark"),
  };
}

/**
 * Node radius by type and centrality (0..1). Clusters and diseases read a
 * little larger so the Atlas has landmarks.
 */
export function nodeSize(
  type: NodeType,
  centrality: number | null | undefined,
  { min = 4, max = 16 }: { min?: number; max?: number } = {},
): number {
  const c = Math.max(0, Math.min(1, centrality ?? 0));
  const base = min + Math.sqrt(c) * (max - min);
  const boost = type === "cluster" ? 1.6 : type === "disease" ? 1.15 : 1;
  return Math.round(base * boost * 10) / 10;
}

export type LineStyle = "solid" | "dashed" | "dotted";

/** Dash patterns in px for canvas renderers / SVG `stroke-dasharray`. */
export const DASH: Record<LineStyle, number[]> = {
  solid: [],
  dashed: [6, 4],
  dotted: [1.5, 3],
};

export function lineStyleFor(origin: Origin): LineStyle {
  return ORIGIN_META[origin]?.line ?? "solid";
}

export function isFlagged(status: EdgeStatus): boolean {
  return status !== "active";
}

export type EdgeVisual = {
  color: string;
  /** Stroke width; grows with confidence. */
  width: number;
  /** 0..1, lower for low confidence. */
  opacity: number;
  line: LineStyle;
  dash: number[];
  /** pending_review / under_review: render a visible flag marker. */
  flagged: boolean;
  confidence: "high" | "medium" | "low";
};

/**
 * Edge style by family (colour), origin (solid / dashed / dotted), confidence
 * (width, opacity) and status (flag). Pass a theme from `readGraphTheme()`
 * for canvas renderers, or omit it to get CSS var colours for the DOM.
 */
export function edgeVisual(
  edge: Pick<GraphEdge, "family" | "origin" | "status" | "confidence">,
  theme?: GraphTheme,
): EdgeVisual {
  const level = confidenceLevel(edge.confidence);
  const line = lineStyleFor(edge.origin);
  return {
    color: theme ? theme.edge[edge.family] : edgeColorVar(edge.family),
    width: level === "high" ? 2.25 : level === "medium" ? 1.5 : 1,
    opacity: level === "high" ? 0.95 : level === "medium" ? 0.75 : 0.5,
    line,
    dash: DASH[line],
    flagged: isFlagged(edge.status),
    confidence: level,
  };
}

/** Cytoscape `line-style` value for an origin. */
export const cytoscapeLineStyle = (origin: Origin): LineStyle => lineStyleFor(origin);

/** SVG `stroke-dasharray` string for React Flow / legends. */
export const svgDashArray = (line: LineStyle) => DASH[line].join(" ") || undefined;
