"use client";

/**
 * The Sigma.js (WebGL) map. Loaded with `next/dynamic({ ssr: false })` only.
 *
 * Positions are precomputed by the pipeline and never re-laid out here.
 * React state stays outside: hover/selection/filters live in a ref and
 * Sigma's reducers read it, so a 3,000-node / 20,000-edge graph stays
 * smooth (one `refresh()` per change, no React re-render of the canvas).
 */
import { MultiGraph } from "graphology";
import { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useRef } from "react";
import Sigma from "sigma";
import type { EdgeProgramType } from "sigma/rendering";
import type { EdgeDisplayData, NodeDisplayData } from "sigma/types";

import { ORIGIN_META, confidenceLevel } from "@/lib/graph/meta";
import { nodeSize, type GraphTheme } from "@/lib/graph/style";
import type { EdgeFamily, NodeType } from "@/lib/graph/types";

import { clusterColor, fallbackPosition, withAlpha, type AtlasIndex } from "./atlas-model";
import { EdgeDashProgram, type DashKind } from "./edge-dash-program";

export type ColorBy = "type" | "cluster";

export type AtlasCanvasHandle = {
  zoomIn: () => void;
  zoomOut: () => void;
  reset: () => void;
  focusNode: (id: string) => void;
};

type Props = {
  index: AtlasIndex;
  theme: GraphTheme;
  colorBy: ColorBy;
  visibleTypes: Set<NodeType>;
  visibleFamilies: Set<EdgeFamily>;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onHover?: (id: string | null) => void;
  onError?: () => void;
  reducedMotion: boolean;
  labelledBy?: string;
  describedBy?: string;
};

const DASH: Record<string, DashKind> = { solid: 0, dashed: 1, dotted: 2 };

type NodeAttrs = {
  x: number;
  y: number;
  size: number;
  label: string;
  nodeType: NodeType;
  cluster: string | null;
};
type EdgeAttrs = {
  s: string;
  t: string;
  st: NodeType;
  tt: NodeType;
  size: number;
  dash: DashKind;
  family: EdgeFamily;
  level: "high" | "medium" | "low";
  flagged: boolean;
};

export const AtlasCanvas = forwardRef<AtlasCanvasHandle, Props>(function AtlasCanvas(props, ref) {
  const container = useRef<HTMLDivElement>(null);
  const labelLayer = useRef<HTMLDivElement>(null);
  const sigmaRef = useRef<Sigma<NodeAttrs, EdgeAttrs> | null>(null);
  const hovered = useRef<string | null>(null);
  const propsRef = useRef(props);
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

  useImperativeHandle(ref, () => ({
    zoomIn: () => {
      const c = sigmaRef.current?.getCamera();
      if (c) animate({ ratio: c.getState().ratio / 1.6 });
    },
    zoomOut: () => {
      const c = sigmaRef.current?.getCamera();
      if (c) animate({ ratio: Math.min(c.getState().ratio * 1.6, 4) });
    },
    reset: () => animate({ x: 0.5, y: 0.5, ratio: 1 }),
    focusNode: (id: string) => {
      const sigma = sigmaRef.current;
      if (!sigma || !sigma.getGraph().hasNode(id)) return;
      const d = sigma.getNodeDisplayData(id);
      if (d) animate({ x: d.x, y: d.y, ratio: 0.3 });
    },
  }));

  // Build the graph and the renderer once per payload.
  useEffect(() => {
    const el = container.current;
    if (!el) return;
    const { index } = propsRef.current;
    const graph = new MultiGraph<NodeAttrs, EdgeAttrs>();
    for (const n of index.nodes.values()) {
      const p = n.x != null && n.y != null ? { x: n.x, y: n.y } : fallbackPosition(n.id);
      graph.addNode(n.id, {
        x: p.x,
        y: p.y,
        size: nodeSize(n.type, n.centrality, { min: 2.5, max: 11 }),
        label: n.label,
        nodeType: n.type,
        cluster: n.cluster_id ?? null,
      });
    }
    for (const e of index.edges.values()) {
      if (e.source === e.target) continue;
      const level = confidenceLevel(e.confidence);
      graph.addEdgeWithKey(e.id, e.source, e.target, {
        s: e.source,
        t: e.target,
        st: index.nodes.get(e.source)!.type,
        tt: index.nodes.get(e.target)!.type,
        size: level === "high" ? 1.1 : level === "medium" ? 0.8 : 0.6,
        dash: DASH[ORIGIN_META[e.origin]?.line ?? "solid"] ?? 0,
        family: e.family,
        level,
        flagged: e.status !== "active",
      });
    }

    function focusSet(): { focus: string | null; near: Set<string> | null } {
      const focus = hovered.current ?? propsRef.current.selectedId;
      if (!focus || !graph.hasNode(focus)) return { focus: null, near: null };
      return { focus, near: propsRef.current.index.neighbors.get(focus) ?? new Set() };
    }
    let cache = { key: "", value: focusSet() };
    const getFocus = () => {
      const key = `${hovered.current}|${propsRef.current.selectedId}`;
      if (cache.key !== key) cache = { key, value: focusSet() };
      return cache.value;
    };

    let sigma: Sigma<NodeAttrs, EdgeAttrs>;
    try {
      const font = getComputedStyle(document.body).fontFamily || "sans-serif";
      sigma = new Sigma<NodeAttrs, EdgeAttrs>(graph, el, {
        defaultEdgeType: "dash",
        edgeProgramClasses: { dash: EdgeDashProgram as unknown as EdgeProgramType<NodeAttrs, EdgeAttrs> },
        renderEdgeLabels: false,
        hideEdgesOnMove: graph.size > 4000,
        labelFont: font,
        labelSize: 12,
        labelWeight: "500",
        labelColor: { color: propsRef.current.theme.label },
        labelRenderedSizeThreshold: 7,
        labelDensity: 0.6,
        labelGridCellSize: 110,
        zIndex: true,
        minCameraRatio: 0.02,
        maxCameraRatio: 4,
        stagePadding: 24,
        defaultDrawNodeLabel: (ctx, data, settings) => {
          if (!data.label) return;
          const t = propsRef.current.theme;
          ctx.font = `${settings.labelWeight} ${settings.labelSize}px ${settings.labelFont}`;
          const x = data.x + data.size + 4;
          const y = data.y + settings.labelSize / 3;
          ctx.lineJoin = "round";
          ctx.lineWidth = 3;
          ctx.strokeStyle = withAlpha(t.background, 0.85);
          ctx.strokeText(data.label, x, y);
          ctx.fillStyle = t.label;
          ctx.fillText(data.label, x, y);
        },
        defaultDrawNodeHover: (ctx, data, settings) => {
          const t = propsRef.current.theme;
          const size = settings.labelSize;
          ctx.font = `600 ${size}px ${settings.labelFont}`;
          ctx.beginPath();
          ctx.arc(data.x, data.y, data.size + 3, 0, Math.PI * 2);
          ctx.lineWidth = 2;
          ctx.strokeStyle = t.highlight;
          ctx.stroke();
          if (typeof data.label !== "string" || !data.label) return;
          const w = ctx.measureText(data.label).width;
          const x = data.x + data.size + 7;
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
    const initial = propsRef.current.selectedId;
    if (initial && graph.hasNode(initial)) {
      const d = sigma.getNodeDisplayData(initial);
      if (d) sigma.getCamera().setState({ x: d.x, y: d.y, ratio: 0.3 });
    }

    function nodeColor(attrs: NodeAttrs) {
      const { theme, colorBy, index: idx } = propsRef.current;
      if (colorBy === "cluster" && attrs.nodeType !== "cluster") {
        const c = attrs.cluster ? idx.clusters.get(attrs.cluster) : undefined;
        return c ? clusterColor(c.order, theme.dark) : withAlpha(theme.muted, 0.7);
      }
      return theme.node[attrs.nodeType] ?? theme.muted;
    }

    function reduceNode(node: string, data: NodeAttrs & NodeDisplayData): Partial<NodeDisplayData> {
      const { visibleTypes, theme, selectedId } = propsRef.current;
      const res: Partial<NodeDisplayData> & { label?: string | null } = { ...data, color: nodeColor(data) };
      if (!visibleTypes.has(data.nodeType)) return { ...res, hidden: true };
      const { focus, near } = getFocus();
      if (focus) {
        if (node === focus || near?.has(node)) {
          res.zIndex = node === focus ? 2 : 1;
          res.forceLabel = node === focus || (near?.size ?? 0) <= 40;
          if (node === selectedId || node === focus) res.highlighted = true;
        } else {
          res.color = theme.border;
          res.size = data.size * 0.6;
          res.label = null;
          res.zIndex = 0;
        }
      }
      return res;
    }

    function reduceEdge(_edge: string, data: EdgeAttrs & EdgeDisplayData): Partial<EdgeDisplayData> {
      const { visibleFamilies, visibleTypes, theme } = propsRef.current;
      if (!visibleFamilies.has(data.family)) return { hidden: true };
      const { s, t } = data;
      if (!visibleTypes.has(data.st) || !visibleTypes.has(data.tt)) return { hidden: true };
      const { focus } = getFocus();
      const base = data.flagged ? theme.statusFlag : theme.edge[data.family];
      if (focus) {
        if (s !== focus && t !== focus) return { hidden: true };
        return {
          ...data,
          color: withAlpha(base, data.level === "low" ? 0.6 : 0.95),
          size: data.size * 2.2,
          zIndex: 1,
        };
      }
      const alpha = data.level === "high" ? 0.55 : data.level === "medium" ? 0.42 : 0.3;
      return { ...data, color: withAlpha(base, data.flagged ? Math.max(alpha, 0.6) : alpha) };
    }

    sigma.on("enterNode", ({ node }) => {
      hovered.current = node;
      el.style.cursor = "pointer";
      propsRef.current.onHover?.(node);
      sigma.refresh({ skipIndexation: true });
    });
    sigma.on("leaveNode", () => {
      hovered.current = null;
      el.style.cursor = "";
      propsRef.current.onHover?.(null);
      sigma.refresh({ skipIndexation: true });
    });
    sigma.on("clickNode", ({ node }) => propsRef.current.onSelect(node));
    sigma.on("clickStage", () => propsRef.current.onSelect(null));

    // Cluster names at low zoom, as an HTML layer (crisp text, theme-aware).
    const layer = labelLayer.current;
    const labelEls = new Map<string, HTMLDivElement>();
    if (layer) {
      layer.replaceChildren();
      for (const c of [...index.clusters.values()].sort((a, b) => b.members - a.members)) {
        if (c.members === 0) continue;
        const d = document.createElement("div");
        d.className =
          "absolute max-w-[220px] -translate-x-1/2 -translate-y-1/2 rounded-md border bg-background/80 px-2 py-0.5 text-center text-[11px] leading-tight font-medium text-foreground shadow-xs backdrop-blur-sm transition-opacity";
        d.textContent = c.label;
        d.dataset.cluster = c.id;
        layer.appendChild(d);
        labelEls.set(c.id, d);
      }
    }
    const placeLabels = () => {
      const { colorBy, index: idx } = propsRef.current;
      const ratio = sigma.getCamera().getState().ratio;
      const show = ratio > 0.35 && !hovered.current;
      const w = el.clientWidth;
      const h = el.clientHeight;
      const placed: DOMRect[] = [];
      for (const [id, d] of labelEls) {
        const c = idx.clusters.get(id);
        if (!c) continue;
        const p = sigma.graphToViewport({ x: c.x, y: c.y });
        const inView = p.x > -50 && p.y > -20 && p.x < w + 50 && p.y < h + 20;
        d.style.left = `${p.x}px`;
        d.style.top = `${p.y}px`;
        let visible = show && inView;
        if (visible) {
          const bw = d.offsetWidth;
          const bh = d.offsetHeight;
          const r = new DOMRect(p.x - bw / 2, p.y - bh / 2, bw, bh);
          if (placed.some((o) => r.left < o.right && r.right > o.left && r.top < o.bottom && r.bottom > o.top)) visible = false;
          else placed.push(r);
        }
        d.style.opacity = visible ? "1" : "0";
        d.style.borderLeft =
          colorBy === "cluster" ? `3px solid ${clusterColor(c.order, propsRef.current.theme.dark)}` : "";
      }
    };
    sigma.on("afterRender", placeLabels);
    placeLabels();

    return () => {
      sigma.kill();
      sigmaRef.current = null;
      layer?.replaceChildren();
    };
  }, [props.index]);

  // Re-style on any visual input change.
  useEffect(() => {
    const sigma = sigmaRef.current;
    if (!sigma) return;
    sigma.setSetting("labelColor", { color: props.theme.label });
    sigma.refresh();
  }, [props.theme, props.colorBy, props.visibleTypes, props.visibleFamilies, props.selectedId]);

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
      "-": { ratio: Math.min(s.ratio * 1.4, 4) },
      "0": { x: 0.5, y: 0.5, ratio: 1 },
    };
    if (move[e.key]) {
      e.preventDefault();
      camera.setState({ ...s, ...move[e.key] });
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
        aria-describedby={props.describedBy}
        onKeyDown={onKeyDown}
        data-testid="atlas-canvas"
      />
      <div ref={labelLayer} className="pointer-events-none absolute inset-0" aria-hidden data-testid="atlas-cluster-labels" />
    </div>
  );
});

export default AtlasCanvas;
