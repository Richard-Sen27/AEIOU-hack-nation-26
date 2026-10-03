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
import { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useRef } from "react";

import type { Schemas } from "@/lib/api";
import { relationLabel, type LabelStyle } from "@/lib/graph/meta";
import { DASH, lineStyleFor, nodeSize, type GraphTheme } from "@/lib/graph/style";
import type { EdgeFamily, NodeType } from "@/lib/graph/types";

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
  selectedEdgeId: string | null;
  onNodeTap: (id: string) => void;
  onEdgeTap: (id: string) => void;
  reducedMotion: boolean;
  labelledBy?: string;
};

function truncate(s: string, n = 26) {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

export const NodeGraph = forwardRef<NodeGraphHandle, Props>(function NodeGraph(props, ref) {
  const { theme, labelStyle, hints, edges, centerId } = props;
  const container = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const propsRef = useRef(props);
  useLayoutEffect(() => {
    propsRef.current = props;
  });

  useImperativeHandle(ref, () => ({
    fit: () => cyRef.current?.animate({ fit: { eles: cyRef.current.elements(":visible"), padding: 40 } }, { duration: propsRef.current.reducedMotion ? 0 : 300 }),
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
        data: { id: n.id, type: n.type, name: n.label, centrality: n.centrality ?? 0, center: n.id === centerId },
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
      minZoom: 0.15,
      maxZoom: 4,
      wheelSensitivity: 0.3,
      boxSelectionEnabled: false,
      autoungrabify: false,
      style: [],
      layout: { name: "preset" },
    });
    cyRef.current = cy;
    cy.on("tap", "node", (e) => {
      const id = e.target.id();
      if (id !== propsRef.current.centerId) propsRef.current.onNodeTap(id);
    });
    cy.on("tap", "edge", (e) => propsRef.current.onEdgeTap(e.target.id()));
    cy.on("mouseover", "node, edge", (e) => {
      e.target.addClass("hover");
      el.style.cursor = e.target.isNode() && e.target.id() === propsRef.current.centerId ? "" : "pointer";
    });
    cy.on("mouseout", "node, edge", (e) => {
      e.target.removeClass("hover");
      el.style.cursor = "";
    });
    return () => {
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
      cy.nodes().forEach((n) => {
        const type = n.data("type") as NodeType;
        const name = truncate(n.data("name") as string);
        const isCenter = n.id() === centerId;
        n.data({
          label: hints.show_ids ? `${name}\n${n.id()}` : name,
          color: theme.node[type] ?? theme.muted,
          size: isCenter ? 46 : nodeSize(type, n.data("centrality"), { min: 14, max: 30 }),
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
          "font-size": 11,
          "min-zoomed-font-size": 7,
          "text-wrap": "wrap",
          "text-max-width": "120px",
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
          "font-size": 12,
          "font-weight": 700,
          "min-zoomed-font-size": 0,
          "z-index": 10,
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
      { selector: "edge.peripheral", style: { opacity: 0.18, width: 1 } },
      { selector: "edge.flagged", style: { label: "data(label)", "font-size": 9, "text-opacity": 0.85 } },
      { selector: "edge.hover, edge.selected", style: { label: "data(label)", opacity: 1, "z-index": 20, "overlay-opacity": 0.08, "overlay-color": theme.highlight } },
      { selector: "edge.selected", style: { width: 5 } },
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
      cy.nodes().forEach((n) => {
        if (n.id() === props.centerId) return;
        const visible = n.connectedEdges().filter(".hidden").length < n.connectedEdges().length;
        n.toggleClass("hidden", !visible && n.connectedEdges().length > 0);
      });
    });
  }, [props.hiddenFamilies, props.centerId, props.nodes, props.edges]);

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
    const highlight = new Set(hints.highlight_family ?? []);
    const center = cy.getElementById(centerId);
    const hasPositions = cy.nodes().filter((n) => n.position("x") === 0 && n.position("y") === 0).length === 0;
    const animate = !reducedMotion && cy.nodes().length < 300;
    let options: LayoutOptions;
    const ring: LayoutOptions = {
      name: "concentric",
      concentric: (n) => {
        if (n.id() === centerId) return 3;
        const direct = n.edgesWith(center);
        if (direct.length === 0) return 0;
        return direct.some((e) => highlight.has(e.data("family"))) ? 2 : 1;
      },
      levelWidth: () => 1,
      minNodeSpacing: 34,
      spacingFactor: 1.15,
      avoidOverlap: true,
      animate,
      animationDuration: 350,
      padding: 30,
    } as LayoutOptions;
    switch (hints.start_layout) {
      case "force":
        options = {
          name: "fcose",
          randomize: !hasPositions,
          quality: "default",
          animate,
          animationDuration: 400,
          nodeRepulsion: 12000,
          idealEdgeLength: 120,
          padding: 30,
        } as unknown as LayoutOptions;
        break;
      case "hierarchy":
        options = { name: "breadthfirst", roots: [centerId], directed: false, spacingFactor: 1.1, animate, padding: 30 } as LayoutOptions;
        break;
      case "cluster":
        options = hasPositions ? ({ name: "preset", fit: true, padding: 30 } as LayoutOptions) : ring;
        break;
      default:
        options = ring;
    }
    const layout = cy.layout(options);
    layout.run();
    return () => {
      layout.stop();
    };
  }, [props.hints.start_layout, props.hints.highlight_family, props.nodes, props.edges, props.centerId]);

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
          cy.fit(undefined, 40);
        }
      }}
    />
  );
});

export default NodeGraph;
