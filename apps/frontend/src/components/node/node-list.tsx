"use client";

import Link from "next/link";

import { ConfidenceBadge, OriginBadge, StatusFlag } from "@/components/graph-ui";
import { useLens } from "@/components/providers/lens-provider";
import type { Schemas } from "@/lib/api";
import { EDGE_FAMILY_META, nodeTypeMeta, relationLabel } from "@/lib/graph/meta";
import type { EdgeFamily } from "@/lib/graph/types";
import { cn } from "@/lib/utils";

type NodeLite = Pick<Schemas.Node, "id" | "type" | "label">;

function NodeCell({ n, centerId }: { n: NodeLite | undefined; centerId: string }) {
  const { labelStyle } = useLens();
  if (!n) return null;
  const meta = nodeTypeMeta(n.type);
  const Icon = meta.icon;
  const body = (
    <>
      <Icon className="size-3.5 shrink-0" style={{ color: `var(${meta.colorVar})` }} aria-hidden />
      <span className="truncate">{n.label}</span>
      <span className="sr-only">({meta.label[labelStyle]})</span>
    </>
  );
  return n.id === centerId ? (
    <span className="flex max-w-[16rem] items-center gap-1.5 font-semibold">{body}</span>
  ) : (
    <Link href={`/node/${encodeURIComponent(n.id)}`} className="flex max-w-[16rem] items-center gap-1.5 rounded font-medium outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring">
      {body}
    </Link>
  );
}

/** Every node and connection of the neighbourhood as a table (graph equivalent). */
export function NodeList({
  centerId,
  edges,
  nodes,
  hiddenFamilies,
  matchingEdges = null,
  query = "",
  onClearQuery,
  selectedEdgeId,
  onEdge,
}: {
  centerId: string;
  edges: Schemas.Edge[];
  nodes: Map<string, NodeLite>;
  hiddenFamilies: Set<EdgeFamily>;
  /** Rows the filter matches; null when no filter is set. */
  matchingEdges?: Set<string> | null;
  query?: string;
  onClearQuery?: () => void;
  selectedEdgeId: string | null;
  onEdge: (id: string) => void;
}) {
  const { labelStyle } = useLens();
  const rows = edges.filter((e) => !hiddenFamilies.has(e.family) && (!matchingEdges || matchingEdges.has(e.id)));
  return (
    <div className="relative h-full overflow-auto" data-testid="node-list">
      <table className="w-full min-w-[640px] text-sm">
        <caption className="sr-only">All connections in this view, with their trust details.</caption>
        <thead className="sticky top-0 z-10 bg-card text-left text-xs text-muted-foreground">
          <tr className="border-b">
            <th scope="col" className="px-3 py-2 font-medium">From</th>
            <th scope="col" className="px-3 py-2 font-medium">Connection</th>
            <th scope="col" className="px-3 py-2 font-medium">To</th>
            <th scope="col" className="px-3 py-2 font-medium">Trust</th>
            <th scope="col" className="px-3 py-2"><span className="sr-only">Sources</span></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((e) => (
            <tr key={e.id} className={cn("border-b border-border/60 align-top", e.id === selectedEdgeId && "bg-primary/10")} data-testid="node-list-row">
              <td className="px-3 py-2"><NodeCell n={nodes.get(e.source_id)} centerId={centerId} /></td>
              <td className="px-3 py-2">
                <span className={cn("block", labelStyle === "technical" && "font-mono text-xs")}>{relationLabel(e.relation, labelStyle)}</span>
                <span className="text-[11px] text-muted-foreground">{EDGE_FAMILY_META[e.family].label[labelStyle]}</span>
              </td>
              <td className="px-3 py-2"><NodeCell n={nodes.get(e.target_id)} centerId={centerId} /></td>
              <td className="px-3 py-2">
                <span className="flex flex-wrap gap-1">
                  <ConfidenceBadge confidence={e.confidence} showScore={labelStyle === "technical"} />
                  <OriginBadge origin={e.origin} />
                  <StatusFlag status={e.status} />
                </span>
              </td>
              <td className="px-3 py-2 text-right">
                <button type="button" onClick={() => onEdge(e.id)} className="rounded px-1.5 py-0.5 text-xs font-medium underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring">
                  Sources
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 &&
        (matchingEdges ? (
          <div className="flex flex-col items-center gap-2 p-6 text-center text-sm text-muted-foreground" data-testid="filter-empty">
            <p>
              No connections match <span className="font-medium text-foreground">&ldquo;{query}&rdquo;</span>.
            </p>
            {onClearQuery && (
              <button type="button" onClick={onClearQuery} className="rounded px-1.5 py-0.5 text-xs font-medium text-foreground underline underline-offset-2 outline-none focus-visible:ring-2 focus-visible:ring-ring">
                Clear the filter
              </button>
            )}
          </div>
        ) : (
          <p className="p-6 text-center text-sm text-muted-foreground">No connections of the selected kinds.</p>
        ))}
    </div>
  );
}
