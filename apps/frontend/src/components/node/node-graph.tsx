"use client";

/**
 * Cytoscape.js neighbourhood graph for `/node/[id]`. Client only (loaded
 * with `next/dynamic({ ssr: false })`).
 *
 * The element set comes from the server and is identical for every lens;
 * the lens only changes the starting layout, the label wording/IDs and which
 * edge family and node types are emphasised first.
 */
import cytoscape, { type Core, type ElementDefinition, type LayoutOptions } from "cytoscape";
import fcose from "cytoscape-fcose";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useRef } from "react";

import type { Schemas } from "@/lib/api";
import { nodeTypeMeta, relationLabel, type LabelStyle } from "@/lib/graph/meta";
import { DASH, lineStyleFor, nodeSize, type GraphTheme } from "@/lib/graph/style";
import type { EdgeFamily, NodeType } from "@/lib/graph/types";

import { BIG_GROUP, groupItems, LABEL_WIDTH, labelledCount, placeNeighbourhood, ringArc, type LayoutItem, type LayoutMode } from "./graph-layouts";
import type { LayoutHints } from "./lens-hints";

let registered = false;
function register() {
  if (registered) return;
  registered = true;
  cytoscape.use(fcose);
}

export type NodeGraphHandle = { fit: () => void; zoomIn: () => void; zoomOut: () => void };

type Props = {
  centerId: string;
  nodes: Schemas.Node[];
  edges: Schemas.Edge[];
  hints: LayoutHints;
  labelStyle: LabelStyle;
  theme: GraphTheme;
  hiddenFamilies: Set<EdgeFamily>;
  /** Filter matches: everything else is faded; the camera does not move. */
  filter?: { nodes: Set<string>; edges: Set<string> } | null;
  selectedEdgeId: string | null;
  onNodeTap: (id: string) => void;
  onEdgeTap: (id: string) => void;
  reducedMotion: boolean;
  labelledBy?: string;
};

function truncate(s: string, n = 26) {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

/**
 * Sizes are in graph units; at zoom 1 one unit is one CSS pixel. Fitting never
 * zooms past MAX_FIT_ZOOM, so a small neighbourhood keeps labels near the UI's
 * small text size (11 × 1.1 ≈ 12 px) instead of being blown up to fill the card.
 */
const LABEL_SIZE = 11;
const CENTER_SIZE = 34;
const NODE_SIZE = { min: 12, max: 22 };
const MAX_FIT_ZOOM = 1.1;
const MAX_ZOOM = 3;
const FIT_PADDING = 40;
/** Rendered size of a hovered node's full name and of the centre's label, whatever the zoom. */
const HOVER_LABEL_PX = 12;
/** Neighbour labels drawn smaller than this (zoomed out on a big neighbourhood) are hidden until hover or zoom-in. */
const MIN_LABEL_PX = 8;

/**
 * Neighbour labels appear once neighbours sit about a label width apart on
 * screen, so a big hub shows dots until zoomed in (names on hover) instead of
 * a pile of overlapping text.
 */
function minLabelPx(count: number) {
  return Math.max(MIN_LABEL_PX, Math.round((LABEL_SIZE * LABEL_WIDTH) / ringArc(count)));
}

/** Fit `eles` into the viewport without zooming in past MAX_FIT_ZOOM. */
function fitViewport(cy: Core, eles = cy.elements(":visible")) {
  const bb = eles.boundingBox();
  const w = cy.width();
  const h = cy.height();
  if (!bb.w || !bb.h || !w || !h) return null;
  const zoom = Math.max(cy.minZoom(), Math.min(MAX_FIT_ZOOM, (w - 2 * FIT_PADDING) / bb.w, (h - 2 * FIT_PADDING) / bb.h));
  return { zoom, pan: { x: (w - zoom * (bb.x1 + bb.x2)) / 2, y: (h - zoom * (bb.y1 + bb.y2)) / 2 } };
}

/** Smaller changes of the card's size (a scrollbar, sub-pixel rounding) keep the user's zoom and pan. */
const REFIT_MIN_RESIZE = 8;

function fitCapped(cy: Core, animate: boolean) {
  const vp = fitViewport(cy);
  if (!vp) return;
  cy.scratch("_fitSize", { w: cy.width(), h: cy.height() });
  if (animate) cy.animate(vp, { duration: 300 });
  else cy.viewport(vp);
}

/** "48 researchers · wrote": a block's caption names its type and relation once. */
function captionText(count: number, type: string, relation: string, style: LabelStyle) {
  const plural = nodeTypeMeta(type as NodeType).plural[style];
  const lower = /^[A-Z][a-z]/.test(plural) ? plural[0].toLowerCase() + plural.slice(1) : plural;
  return `${count} ${lower} · ${relationLabel(relation, style)}`;
}

/** Neighbours with their rank and their relation to the centre, for the layouts. */
function layoutItems(cy: Core, centerId: string, highlight: Set<string>): LayoutItem[] {
  const center = cy.getElementById(centerId);
  return cy
    .nodes(":not(.caption)")
    .filter((n) => n.id() !== centerId)
    .toArray()
    .map((n) => {
      const direct = (n as cytoscape.NodeSingular).edgesWith(center).toArray();
      const lead = direct.find((e) => highlight.has(e.data("family"))) ?? direct[0];
      const rank: 0 | 1 | 2 = !lead ? 2 : highlight.has(lead.data("family")) ? 0 : 1;
      return { id: n.id(), type: n.data("type") as string, relation: lead ? (lead.data("relation") as string) : null, rank };
    });
}

/** A caption is shown while at least one of its members is. */
function syncCaptions(cy: Core) {
  cy.nodes(".caption").forEach((c) => {
    const members = (c.data("members") as string[]).map((id) => cy.getElementById(id));
    c.toggleClass("hidden", members.every((m) => m.hasClass("hidden")));
  });
}

export const NodeGraph = forwardRef<NodeGraphHandle, Props>(function NodeGraph(props, ref) {
  const { theme, labelStyle, hints, edges, centerId } = props;
  const container = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const propsRef = useRef(props);
  const scaleLabelsRef = useRef<() => void>(() => {});
  const highlightKey = (hints.highlight_family ?? []).join(",");
  useLayoutEffect(() => {
    propsRef.current = props;
  });

  useImperativeHandle(ref, () => ({
    fit: () => {
      if (cyRef.current) fitCapped(cyRef.current, !propsRef.current.reducedMotion);
    },
    zoomIn: () => {
      const cy = cyRef.current;
      if (cy) cy.zoom({ level: cy.zoom() * 1.3, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
    },
    zoomOut: () => {
      const cy = cyRef.current;
      if (cy) cy.zoom({ level: cy.zoom() / 1.3, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
    },
  }));

  // Create once per element set.
  useEffect(() => {
    register();
    const el = container.current;
    if (!el) return;
    const { nodes, edges, centerId } = propsRef.current;
    const ids = new Set(nodes.map((n) => n.id));
    const elements: ElementDefinition[] = [
      ...nodes.map((n) => ({
        group: "nodes" as const,
        data: {
          id: n.id,
          type: n.type,
          name: n.label,
          fullName: n.label,
          centrality: n.centrality ?? 0,
          center: n.id === centerId,
          minLabel: minLabelPx(nodes.length - 1),
        },
        position: n.x != null && n.y != null ? { x: n.x, y: n.y } : undefined,
        classes: n.id === centerId ? "center" : undefined,
      })),
      ...edges
        .filter((e) => ids.has(e.source_id) && ids.has(e.target_id))
        .map((e) => ({
          group: "edges" as const,
          data: { id: e.id, source: e.source_id, target: e.target_id, relation: e.relation, family: e.family, origin: e.origin },
        })),
    ];
    const cy = cytoscape({
      container: el,
      elements,
      minZoom: 0.1,
      maxZoom: MAX_ZOOM,
      wheelSensitivity: 0.3,
      boxSelectionEnabled: false,
      autoungrabify: false,
      style: [],
      layout: { name: "preset" },
    });
    cyRef.current = cy;
    // The centre keeps a readable label when zoomed out.
    const scaleCenterLabel = () => {
      const c = cy.getElementById(propsRef.current.centerId);
      const size = Math.max(LABEL_SIZE + 1, HOVER_LABEL_PX / cy.zoom());
      const outline = Math.max(2.5, 3 / cy.zoom());
      if (c.nonempty()) c.style({ "font-size": size, "text-outline-width": outline });
      cy.nodes(".caption").style({ "font-size": Math.max(LABEL_SIZE, HOVER_LABEL_PX / cy.zoom()), "text-outline-width": outline });
      // Filter matches stay readable when zoomed out.
      cy.nodes(".match").style({ "font-size": Math.max(LABEL_SIZE, LABEL_SIZE / cy.zoom()), "text-outline-width": outline });
    };
    cy.on("zoom", scaleCenterLabel);
    scaleLabelsRef.current = scaleCenterLabel;
    cy.on("tap", "node", (e) => {
      const id = e.target.id();
      if (id !== propsRef.current.centerId) propsRef.current.onNodeTap(id);
    });
    cy.on("tap", "edge", (e) => propsRef.current.onEdgeTap(e.target.id()));
    cy.on("mouseover", "node, edge", (e) => {
      e.target.addClass("hover");
      // Full name at a readable size, also when the graph is zoomed out.
      if (e.target.isNode()) {
        const z = cy.zoom();
        e.target.style({
          label: e.target.data("fullName"),
          "font-size": Math.max(LABEL_SIZE, HOVER_LABEL_PX / z),
          "text-max-width": `${Math.max(LABEL_WIDTH, 240 / z)}px`,
          "text-outline-width": Math.max(2.5, 3 / z),
          "min-zoomed-font-size": 0,
          "z-index": 30,
        });
      }
      el.style.cursor = e.target.isNode() && e.target.id() === propsRef.current.centerId ? "" : "pointer";
    });
    cy.on("mouseout", "node, edge", (e) => {
      e.target.removeClass("hover");
      if (e.target.isNode()) {
        e.target.removeStyle("label font-size text-max-width text-outline-width min-zoomed-font-size z-index");
        if (e.target.id() === propsRef.current.centerId || e.target.hasClass("match")) scaleCenterLabel();
      }
      el.style.cursor = "";
    });
    // The card's height follows the viewport on desktop: tell Cytoscape when it changes.
    const observer = new ResizeObserver(() => cy.resize());
    observer.observe(el);
    return () => {
      observer.disconnect();
      cy.destroy();
      cyRef.current = null;
    };
  }, [props.nodes, props.edges, props.centerId]);

  // Data + style: lens wording, theme, statuses, emphasis.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const highlightFamilies = new Set(hints.highlight_family ?? []);
    const highlightTypes = new Set(hints.highlight_node_types ?? []);
    const byId = new Map(edges.map((e) => [e.id, e]));
    cy.batch(() => {
      cy.nodes(".caption").forEach((c) => {
        c.data("label", captionText(c.data("count"), c.data("type"), c.data("relation"), labelStyle));
      });
      cy.nodes(":not(.caption)").forEach((n) => {
        const type = n.data("type") as NodeType;
        const name = truncate(n.data("name") as string);
        const isCenter = n.id() === centerId;
        n.data({
          label: hints.show_ids ? `${name}\n${n.id()}` : name,
          color: theme.node[type] ?? theme.muted,
          size: isCenter ? CENTER_SIZE : nodeSize(type, n.data("centrality"), NODE_SIZE),
        });
        n.toggleClass("emph", !isCenter && highlightTypes.has(type));
      });
      cy.edges().forEach((ed) => {
        const e = byId.get(ed.id());
        if (!e) return;
        const level = e.confidence >= 0.8 ? "high" : e.confidence >= 0.5 ? "medium" : "low";
        const flagged = e.status !== "active";
        const line = lineStyleFor(e.origin);
        ed.data({
          color: flagged ? theme.statusFlag : theme.edge[e.family],
          width: level === "high" ? 3 : level === "medium" ? 2 : 1.4,
          lineStyle: line,
          dash: DASH[line].length ? DASH[line].map((d) => d * 1.4) : [1, 0],
          label: relationLabel(e.relation, labelStyle) + (flagged ? (e.status === "under_review" ? " · under review" : " · pending review") : ""),
        });
        ed.toggleClass("dim", highlightFamilies.size > 0 && !highlightFamilies.has(e.family));
        ed.toggleClass("flagged", flagged);
        ed.toggleClass("peripheral", e.source_id !== centerId && e.target_id !== centerId);
      });
    });
    cy.style([
      {
        selector: "node",
        style: {
          "background-color": "data(color)",
          width: "data(size)",
          height: "data(size)",
          label: "data(label)",
          color: theme.label,
          "font-family": getComputedStyle(document.body).fontFamily,
          "font-size": LABEL_SIZE,
          // Set per layout: depends on how many neighbours keep a labelled place.
          "min-zoomed-font-size": "data(minLabel)" as never,
          "text-wrap": "wrap",
          "text-max-width": `${LABEL_WIDTH}px`,
          "text-valign": "bottom",
          "text-margin-y": 4,
          "text-outline-color": theme.background,
          "text-outline-width": 2.5,
          "border-width": 1.5,
          "border-color": theme.background,
          "overlay-opacity": 0,
        },
      },
      {
        selector: "node.emph",
        style: { "border-width": 3, "border-color": theme.highlight, "font-weight": 600 },
      },
      {
        selector: "node.center",
        style: {
          "border-width": 4,
          "border-color": theme.highlight,
          "font-size": LABEL_SIZE + 1,
          "font-weight": 700,
          "min-zoomed-font-size": 0,
          "z-index": 10,
        },
      },
      // Members of a compact block: the caption names the group, each name shows on hover.
      { selector: "node.member", style: { label: "" } },
      {
        selector: "node.caption",
        style: {
          "background-opacity": 0,
          "border-width": 0,
          width: 1,
          height: 1,
          label: "data(label)",
          // Grows upwards from the caption point, so a wrapped caption never covers the block.
          "text-valign": "top",
          "text-margin-y": 0,
          "font-weight": 600,
          "text-max-width": "260px",
          "min-zoomed-font-size": 0,
          events: "no",
          "z-index": 5,
        },
      },
      { selector: "node.hover", style: { "underlay-color": theme.highlight, "underlay-opacity": 0.25, "underlay-padding": 6 } },
      {
        selector: "edge",
        style: {
          width: "data(width)",
          "line-color": "data(color)",
          "line-style": "data(lineStyle)" as never,
          "line-dash-pattern": "data(dash)" as never,
          "curve-style": "bezier",
          opacity: 0.9,
          "overlay-padding": 6,
          "overlay-opacity": 0,
          label: "",
          "font-size": 10,
          color: theme.label,
          "text-outline-color": theme.background,
          "text-outline-width": 2.5,
          "text-rotation": "autorotate",
        },
      },
      { selector: "edge.dim", style: { opacity: 0.4 } },
      // One faint line per block member: the block reads as one group, not dozens of equal spokes.
      { selector: "edge.grouped", style: { opacity: 0.16, width: 1 } },
      { selector: "edge.grouped-far", style: { opacity: 0.05, width: 1 } },
      { selector: "edge.peripheral", style: { opacity: 0.18, width: 1 } },
      { selector: "edge.flagged", style: { label: "data(label)", "font-size": 9, "text-opacity": 0.85 } },
      { selector: "edge.hover, edge.selected", style: { label: "data(label)", opacity: 1, "z-index": 20, "overlay-opacity": 0.08, "overlay-color": theme.highlight } },
      { selector: "edge.selected", style: { width: 5 } },
      // Filter: non-matches fade, matches keep full strength and show their names at any zoom.
      { selector: "node.faded", style: { opacity: 0.15 } },
      { selector: "edge.faded", style: { opacity: 0.06 } },
      {
        selector: "node.match",
        style: { label: "data(label)", "min-zoomed-font-size": 0, "font-weight": 600, "z-index": 25 },
      },
      { selector: ".hidden", style: { display: "none" } },
    ]);
  }, [theme, labelStyle, hints, edges, centerId]);

  // Family filter: hide edges, then nodes left without a visible edge.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.batch(() => {
      cy.edges().forEach((e) => {
        e.toggleClass("hidden", props.hiddenFamilies.has(e.data("family")));
      });
      cy.nodes(":not(.caption)").forEach((n) => {
        if (n.id() === props.centerId) return;
        const visible = n.connectedEdges().filter(".hidden").length < n.connectedEdges().length;
        n.toggleClass("hidden", !visible && n.connectedEdges().length > 0);
      });
      syncCaptions(cy);
    });
  }, [props.hiddenFamilies, props.centerId, props.nodes, props.edges]);

  // Neighbourhood filter. Re-applied after a layout, which recreates the captions.
  const applyFilter = useCallback(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const f = propsRef.current.filter;
    const centerId = propsRef.current.centerId;
    cy.batch(() => {
      cy.nodes(".match").removeStyle("font-size text-outline-width");
      cy.elements().removeClass("faded match");
      if (!f) return;
      cy.nodes(":not(.caption)").forEach((n) => {
        if (n.id() === centerId) return;
        const hit = f.nodes.has(n.id());
        n.toggleClass("match", hit);
        n.toggleClass("faded", !hit);
      });
      cy.edges().forEach((e) => {
        e.toggleClass("faded", !f.edges.has(e.id()));
      });
      cy.nodes(".caption").forEach((c) => {
        c.toggleClass("faded", !(c.data("members") as string[]).some((id) => f.nodes.has(id)));
      });
    });
    scaleLabelsRef.current();
  }, []);
  useEffect(() => {
    applyFilter();
  }, [props.filter, props.nodes, props.edges, applyFilter]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.edges().removeClass("selected");
    if (props.selectedEdgeId) cy.getElementById(props.selectedEdgeId).addClass("selected");
  }, [props.selectedEdgeId, props.nodes, props.edges]);

  // Layout: from the lens's starting layout. Re-runs when it changes.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const { hints, centerId, reducedMotion } = propsRef.current;
    const highlight = new Set<string>(hints.highlight_family ?? []);
    const animate = !reducedMotion && cy.nodes().length < 300;
    let options: LayoutOptions;
    // Layouts place nodes only; the viewport is fitted afterwards with a zoom cap.
    // Rings, hierarchy and clusters are computed here (graph-layouts.ts), with big
    // same-type groups as captioned blocks. The force layout is used only while no
    // such group exists; with one it falls back to the rings.
    const items = layoutItems(cy, centerId, highlight);
    const hasBigGroup = groupItems(items, BIG_GROUP).groups.length > 0;
    const mode: LayoutMode | "force" =
      hints.start_layout === "hierarchy"
        ? "hierarchy"
        : hints.start_layout === "cluster"
          ? "cluster"
          : hints.start_layout === "force" && !hasBigGroup
            ? "force"
            : "ring";
    const placement = mode === "force" ? { positions: {}, groups: [] } : placeNeighbourhood(centerId, items, mode);
    const positions = placement.positions;
    cy.batch(() => {
      cy.remove(cy.nodes(".caption"));
      cy.nodes().removeClass("member");
      cy.edges().removeClass("grouped grouped-far");
      const { labelStyle } = propsRef.current;
      for (const g of placement.groups) {
        const members = cy.nodes().filter((n) => g.ids.includes(n.id()));
        if (g.compact) {
          members.addClass("member");
          members.edgesWith(cy.getElementById(centerId)).addClass("grouped");
          members.connectedEdges().not(".grouped").addClass("grouped-far");
        }
        const id = `caption:${g.key}`;
        positions[id] = g.caption;
        cy.add({
          group: "nodes",
          data: { id, caption: true, count: g.ids.length, type: g.type, relation: g.relation, members: g.ids, label: captionText(g.ids.length, g.type, g.relation, labelStyle) },
          position: g.caption,
          classes: "caption",
        });
      }
      syncCaptions(cy);
      applyFilter();
      const labelled = mode === "force" ? items.length : labelledCount(placement, items.length);
      cy.nodes(":not(.caption)").data("minLabel", minLabelPx(labelled));
    });
    const ring: LayoutOptions = {
      name: "preset",
      positions: (n: cytoscape.NodeSingular) => positions[n.id()] ?? n.position(),
      fit: false,
      animate,
      animationDuration: 350,
    } as LayoutOptions;
    switch (mode) {
      case "force":
        options = {
          name: "fcose",
          randomize: true,
          quality: "default",
          animate,
          animationDuration: 400,
          nodeRepulsion: 12000,
          idealEdgeLength: 120,
          fit: false,
        } as unknown as LayoutOptions;
        break;
      default:
        options = ring;
    }
    const layout = cy.layout(options);
    // The ring's end positions are known up front: frame them first, then let the nodes move in.
    if (options === ring) {
      const before = cy.nodes(":not(.caption)").map((n) => ({ n, p: { ...n.position() } }));
      cy.nodes().positions((n) => positions[n.id()] ?? n.position());
      fitCapped(cy, false);
      before.forEach(({ n, p }) => n.position(p));
    }
    let running = true;
    layout.one("layoutstop", () => {
      running = false;
      if (!cy.destroyed()) fitCapped(cy, animate && options !== ring);
    });
    layout.run();
    // Refit only when the card's size really changed. Cytoscape also emits
    // "resize" during wheel and pointer interaction without any size change;
    // refitting then undid the user's zoom a moment later.
    const onResize = () => {
      if (running) return;
      const last = cy.scratch("_fitSize") as { w: number; h: number } | undefined;
      if (last && Math.abs(cy.width() - last.w) < REFIT_MIN_RESIZE && Math.abs(cy.height() - last.h) < REFIT_MIN_RESIZE) return;
      fitCapped(cy, false);
    };
    cy.on("resize", onResize);
    return () => {
      // The create effect may already have destroyed this instance.
      if (cy.destroyed()) return;
      layout.stop();
      cy.off("resize", onResize);
    };
    // The highlighted families by value: a new array with the same families is not a new layout.
  }, [props.hints.start_layout, highlightKey, props.nodes, props.edges, props.centerId, applyFilter]);

  return (
    <div
      ref={container}
      className="size-full outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
      tabIndex={0}
      role="img"
      aria-roledescription="interactive graph"
      aria-labelledby={props.labelledBy}
      data-testid="node-graph"
      onKeyDown={(e) => {
        const cy = cyRef.current;
        if (!cy) return;
        const step = 40;
        const pan: Record<string, { x: number; y: number }> = {
          ArrowLeft: { x: step, y: 0 },
          ArrowRight: { x: -step, y: 0 },
          ArrowUp: { x: 0, y: step },
          ArrowDown: { x: 0, y: -step },
        };
        if (pan[e.key]) {
          e.preventDefault();
          cy.panBy(pan[e.key]);
        } else if (e.key === "+" || e.key === "=") {
          cy.zoom({ level: cy.zoom() * 1.2, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
        } else if (e.key === "-") {
          cy.zoom({ level: cy.zoom() / 1.2, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
        } else if (e.key === "0") {
          fitCapped(cy, false);
        }
      }}
    />
  );
});

export default NodeGraph;
