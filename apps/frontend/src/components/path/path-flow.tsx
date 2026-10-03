"use client";

import "@xyflow/react/dist/style.css";

import {
  EdgeLabelRenderer,
  getStraightPath,
  Handle,
  Position,
  ReactFlow,
  type Edge as FlowEdge,
  type EdgeProps,
  type Node as FlowNode,
  type NodeProps,
} from "@xyflow/react";
import { Flag, Hourglass, HelpCircle } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import Link from "next/link";
import { useTheme } from "next-themes";
import { memo, useEffect, useMemo, useRef, useState } from "react";

import { useLens } from "@/components/providers/lens-provider";
import { CONFIDENCE_LABEL, nodeTypeMeta, ORIGIN_META, relationLabel, type LabelStyle } from "@/lib/graph/meta";
import { edgeVisual, svgDashArray } from "@/lib/graph/style";
import { cn } from "@/lib/utils";

import type { ApiEdge, ApiNode, PathStep } from "./types";

/** Seconds between two revealed steps. */
export const STEP_STAGGER = 0.42;

type Orientation = "horizontal" | "vertical";

type WaypointData = {
  node: ApiNode | { id: string; label: string; type: string };
  index: number;
  total: number;
  ghost?: boolean;
  delay: number;
  reduce: boolean;
  orientation: Orientation;
  labelStyle: LabelStyle;
};

type TrustEdgeData = {
  edge: ApiEdge;
  reversed: boolean;
  orientation: Orientation;
  index: number;
  delay: number;
  reduce: boolean;
  highlighted: boolean;
  labelStyle: LabelStyle;
  onOpen: (edgeId: string) => void;
};

type MissingEdgeData = { delay: number; reduce: boolean; description: string };

const NODE_W = 190;
const GAP_X = 400;
const GAP_Y = 190;

const Waypoint = memo(function Waypoint({ data }: NodeProps<FlowNode<WaypointData>>) {
  const { node, index, total, ghost, delay, reduce, orientation, labelStyle } = data;
  const meta = nodeTypeMeta(node.type);
  const Icon = meta.icon;
  const isEnd = index === 0 || index === total - 1;
  const [tPos, sPos] = orientation === "horizontal" ? [Position.Left, Position.Right] : [Position.Top, Position.Bottom];
  const body = (
    <>
      <span className="flex items-center gap-1.5 text-[10.5px] text-muted-foreground">
        <span
          className={cn(
            "flex size-[18px] items-center justify-center rounded-full font-mono text-[10px] font-semibold tabular",
            ghost ? "border border-dashed border-muted-foreground" : "text-background",
          )}
          style={ghost ? undefined : { background: `var(${meta.colorVar})` }}
          aria-hidden
        >
          {ghost ? "?" : index + 1}
        </span>
        <Icon className="size-3" style={{ color: `var(${meta.colorVar})` }} aria-hidden />
        <span className="truncate uppercase tracking-[0.08em]">{meta.label[labelStyle]}</span>
      </span>
      <span className="line-clamp-2 text-[13.5px] leading-snug font-semibold text-foreground">{node.label}</span>
      {labelStyle === "technical" && <span className="font-mono text-[10px] text-muted-foreground">{node.id}</span>}
    </>
  );
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 10, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ delay: reduce ? 0 : delay, duration: reduce ? 0 : 0.38, ease: [0.22, 1, 0.36, 1] }}
      style={{ width: NODE_W }}
      data-testid="flow-node"
      data-node-id={node.id}
    >
      <Handle type="target" position={tPos} className="!pointer-events-none !opacity-0" isConnectable={false} />
      {ghost ? (
        <div className="flex flex-col gap-1 rounded-xl border-2 border-dashed border-muted-foreground/50 bg-background/60 px-3 py-2.5 opacity-80">
          {body}
        </div>
      ) : (
        <Link
          href={`/node/${encodeURIComponent(node.id)}`}
          className={cn(
            "nodrag nopan flex flex-col gap-1 rounded-xl border bg-card px-3 py-2.5 shadow-sm outline-none transition hover:-translate-y-px hover:shadow-md focus-visible:ring-3 focus-visible:ring-ring/50",
            isEnd && "ring-2 ring-offset-2 ring-offset-background",
          )}
          style={isEnd ? ({ "--tw-ring-color": `var(${meta.colorVar})` } as React.CSSProperties) : undefined}
        >
          {body}
          <span className="sr-only">Open {node.label}</span>
        </Link>
      )}
      <Handle type="source" position={sPos} className="!pointer-events-none !opacity-0" isConnectable={false} />
    </motion.div>
  );
});

function TrustEdge({ id, sourceX, sourceY, targetX, targetY, data }: EdgeProps<FlowEdge<TrustEdgeData>>) {
  const [path, labelX, labelY] = getStraightPath({ sourceX, sourceY, targetX, targetY });
  if (!data) return null;
  const { edge, delay, reduce, highlighted, labelStyle, onOpen, reversed, orientation } = data;
  const arrow = orientation === "horizontal" ? (reversed ? "←" : "→") : reversed ? "↑" : "↓";
  const v = edgeVisual(edge);
  const origin = ORIGIN_META[edge.origin];
  const level = edge.confidence_level ?? v.confidence;
  const flagged = edge.status !== "active";
  const contradicted = (edge.contradiction_count ?? 0) > 0;
  return (
    <>
      <motion.path
        id={id}
        d={path}
        fill="none"
        stroke={v.color}
        strokeWidth={(v.width + 1) * (highlighted ? 1.8 : 1)}
        strokeDasharray={svgDashArray(v.line)}
        strokeLinecap="round"
        initial={reduce ? false : { opacity: 0 }}
        animate={{ opacity: highlighted ? 1 : Math.max(0.7, v.opacity) }}
        transition={{ delay: reduce ? 0 : delay, duration: reduce ? 0 : 0.45 }}
        className="react-flow__edge-path"
      />
      <EdgeLabelRenderer>
        <div
          className="nodrag nopan pointer-events-auto absolute"
          style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
        >
          <motion.div
            initial={reduce ? false : { opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: reduce ? 0 : delay + 0.12, duration: reduce ? 0 : 0.3 }}
          >
          <button
            type="button"
            onClick={() => onOpen(edge.id)}
            data-testid="flow-edge-label"
            data-edge-id={edge.id}
            data-origin={edge.origin}
            data-highlighted={highlighted || undefined}
            className={cn(
              "flex max-w-[170px] flex-col items-center gap-1 rounded-lg border bg-popover/95 px-2 py-1.5 text-center shadow-sm outline-none backdrop-blur transition hover:shadow-md focus-visible:ring-3 focus-visible:ring-ring/60",
              edge.origin !== "observed" && "border-dashed border-foreground/40",
              highlighted && "ring-3 ring-primary",
            )}
          >
            <span className={cn("text-[11.5px] leading-tight font-medium", labelStyle === "technical" && "font-mono text-[10.5px]")}>
              <span aria-hidden className="mr-1 text-muted-foreground">{arrow}</span>
              {relationLabel(edge.relation, labelStyle)}
            </span>
            <span className="flex flex-wrap items-center justify-center gap-1 text-[10px]">
              <span
                className={cn(
                  "rounded-full px-1.5 py-px font-semibold",
                  level === "high" && "bg-confidence-high/15 text-confidence-high",
                  level === "medium" && "bg-confidence-medium/25 text-foreground",
                  level === "low" && "bg-confidence-low/15 text-confidence-low",
                )}
              >
                {CONFIDENCE_LABEL[level]}
              </span>
              <span className={cn("rounded-full border px-1.5 py-px", origin.line === "solid" ? "border-solid" : "border-dashed", "border-foreground/40")}>
                {origin.label.plain}
              </span>
              {flagged && (
                <span className="inline-flex items-center gap-0.5 rounded-full bg-status-flag/15 px-1.5 py-px">
                  {edge.status === "under_review" ? <Flag className="size-2.5 text-status-flag" aria-hidden /> : <Hourglass className="size-2.5 text-status-flag" aria-hidden />}
                  {edge.status === "under_review" ? "Under review" : "Pending"}
                </span>
              )}
              {contradicted && (
                <span className="rounded-full bg-confidence-low/15 px-1.5 py-px text-confidence-low">Contradicted</span>
              )}
            </span>
            <span className="sr-only">Show evidence</span>
          </button>
          </motion.div>
        </div>
      </EdgeLabelRenderer>
    </>
  );
}

function MissingEdge({ sourceX, sourceY, targetX, targetY, data }: EdgeProps<FlowEdge<MissingEdgeData>>) {
  const [, labelX, labelY] = getStraightPath({ sourceX, sourceY, targetX, targetY });
  const dx = targetX - sourceX;
  const dy = targetY - sourceY;
  const stub = 0.14;
  const delay = data?.delay ?? 0;
  const reduce = data?.reduce ?? false;
  return (
    <>
      {/* Two stubs and a gap: never drawn as if it were a link. */}
      <path d={`M${sourceX},${sourceY} l${dx * stub},${dy * stub}`} stroke="var(--muted-foreground)" strokeWidth={2} strokeLinecap="round" opacity={0.6} />
      <path d={`M${targetX},${targetY} l${-dx * stub},${-dy * stub}`} stroke="var(--muted-foreground)" strokeWidth={2} strokeLinecap="round" opacity={0.6} />
      <EdgeLabelRenderer>
        <motion.div
          initial={reduce ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: reduce ? 0 : delay, duration: reduce ? 0 : 0.4 }}
          className="pointer-events-auto absolute flex max-w-[180px] flex-col items-center gap-1 rounded-lg border-2 border-dashed border-confidence-low/60 bg-background/95 px-2.5 py-1.5 text-center"
          style={{ x: "-50%", y: "-50%", left: labelX, top: labelY }}
          data-testid="flow-missing-link"
        >
          <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-confidence-low">
            <HelpCircle className="size-3" aria-hidden /> Missing link
          </span>
          <span className="text-[10.5px] leading-tight text-muted-foreground">No supported connection</span>
        </motion.div>
      </EdgeLabelRenderer>
    </>
  );
}

const nodeTypes = { waypoint: Waypoint };
const edgeTypes = { trust: TrustEdge, missing: MissingEdge };

export type MissingLinkView = {
  fromId: string;
  to: { id: string; label: string; type: string };
  description: string;
};

/**
 * One route as an ordered flow: waypoints (nodes) and links (edges) revealed
 * in traversal order. Every link label shows relation (lens wording),
 * confidence, origin (solid = data, dashed = hypothesis) and status.
 */
export function PathFlow({
  steps,
  highlightedEdgeId,
  onOpenEdge,
  missing,
  className,
  label,
}: {
  steps: PathStep[];
  highlightedEdgeId?: string | null;
  onOpenEdge: (edgeId: string) => void;
  /** Render the route as incomplete, ending in a missing link. */
  missing?: MissingLinkView | null;
  className?: string;
  label: string;
}) {
  const { labelStyle } = useLens();
  const { resolvedTheme } = useTheme();
  const reduce = useReducedMotion() ?? false;
  const wrap = useRef<HTMLDivElement>(null);
  const [orientation, setOrientation] = useState<Orientation>("horizontal");

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      setOrientation(entry.contentRect.width < 640 ? "vertical" : "horizontal");
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const routeKey = steps.map((s) => s.edge.id).join("|") + (missing ? `|missing:${missing.to.id}` : "");

  const { nodes, edges, count } = useMemo(() => {
    const list: WaypointData["node"][] = [];
    if (steps.length) {
      list.push(steps[0].from_node);
      steps.forEach((s) => list.push(s.to_node));
    }
    let missingFromIndex = -1;
    if (missing) {
      if (list.length === 0) list.push({ id: missing.fromId, label: missing.fromId, type: "disease" });
      missingFromIndex = list.findIndex((n) => n.id === missing.fromId);
      if (missingFromIndex < 0) missingFromIndex = list.length - 1;
      list.push(missing.to);
    }
    const total = list.length;
    const pos = (i: number) =>
      orientation === "horizontal" ? { x: i * GAP_X, y: 0 } : { x: 0, y: i * GAP_Y };
    const nodes: FlowNode<WaypointData>[] = list.map((n, i) => ({
      id: `n${i}`,
      type: "waypoint",
      position: pos(i),
      data: {
        node: n,
        index: i,
        total,
        ghost: !!missing && i === total - 1,
        delay: i * STEP_STAGGER,
        reduce,
        orientation,
        labelStyle,
      },
      draggable: false,
      selectable: false,
    }));
    const edges: FlowEdge[] = steps.map((s, i) => ({
      id: `e${i}`,
      source: `n${i}`,
      target: `n${i + 1}`,
      type: "trust",
      data: {
        edge: s.edge,
        reversed: !!s.reversed,
        orientation,
        index: i,
        delay: i * STEP_STAGGER + STEP_STAGGER / 2,
        reduce,
        highlighted: highlightedEdgeId === s.edge.id,
        labelStyle,
        onOpen: onOpenEdge,
      } satisfies TrustEdgeData,
      selectable: false,
    }));
    if (missing) {
      edges.push({
        id: "missing",
        source: `n${missingFromIndex}`,
        target: `n${total - 1}`,
        type: "missing",
        data: { delay: (total - 1) * STEP_STAGGER, reduce, description: missing.description } satisfies MissingEdgeData,
        selectable: false,
      });
    }
    return { nodes, edges, count: total };
  }, [steps, missing, orientation, reduce, labelStyle, highlightedEdgeId, onOpenEdge]);

  const height = orientation === "horizontal" ? 230 : Math.max(260, count * GAP_Y - 40);

  return (
    <div
      ref={wrap}
      className={cn("path-flow bg-atlas-grid relative overflow-hidden rounded-xl border bg-card/40", className)}
      style={{ height }}
      role="group"
      aria-label={label}
      data-testid="path-flow"
      data-orientation={orientation}
    >
      <ReactFlow
        key={`${routeKey}-${orientation}`}
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        colorMode={resolvedTheme === "dark" ? "dark" : "light"}
        fitView
        fitViewOptions={{ padding: orientation === "horizontal" ? 0.05 : 0.08, maxZoom: 1 }}
        minZoom={0.3}
        maxZoom={1.6}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        zoomOnScroll={false}
        zoomOnDoubleClick={false}
        panOnScroll={false}
        preventScrolling={false}
        panOnDrag={orientation === "horizontal"}
        proOptions={{ hideAttribution: true }}
        style={{ background: "transparent" }}
      />
    </div>
  );
}
