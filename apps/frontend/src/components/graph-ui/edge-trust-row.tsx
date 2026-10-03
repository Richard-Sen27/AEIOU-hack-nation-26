"use client";

import { useLens } from "@/components/providers/lens-provider";
import { EDGE_FAMILY_META, ORIGIN_META, relationLabel } from "@/lib/graph/meta";
import { svgDashArray } from "@/lib/graph/style";
import type { GraphEdge } from "@/lib/graph/types";
import { cn } from "@/lib/utils";

import { ConfidenceBadge } from "./confidence-badge";
import { OriginBadge } from "./origin-badge";
import { StatusFlag } from "./status-flag";

/**
 * The compact trust summary for one edge: line sample (family colour +
 * origin style), relation in the lens's words, confidence, origin, status.
 * Use it wherever an edge is listed; pair with <EvidenceList> on click.
 */
export function EdgeTrustRow({
  edge,
  className,
}: {
  edge: Pick<GraphEdge, "relation" | "family" | "confidence" | "origin" | "status" | "evidence">;
  className?: string;
}) {
  const { labelStyle } = useLens();
  const family = EDGE_FAMILY_META[edge.family];
  return (
    <div className={cn("flex flex-wrap items-center gap-1.5", className)} data-testid="edge-trust-row">
      <svg width="22" height="8" viewBox="0 0 22 8" aria-hidden className="shrink-0">
        <line
          x1="1"
          y1="4"
          x2="21"
          y2="4"
          stroke={`var(${family.colorVar})`}
          strokeWidth="2"
          strokeLinecap="round"
          strokeDasharray={svgDashArray(ORIGIN_META[edge.origin]?.line ?? "solid")}
        />
      </svg>
      <span className={cn("text-sm", labelStyle === "technical" && "font-mono text-xs")}>
        {relationLabel(edge.relation, labelStyle)}
      </span>
      <span className="sr-only">({family.label[labelStyle]})</span>
      <ConfidenceBadge confidence={edge.confidence} evidence={edge.evidence} showScore={labelStyle === "technical"} />
      <OriginBadge origin={edge.origin} />
      <StatusFlag status={edge.status} />
    </div>
  );
}
