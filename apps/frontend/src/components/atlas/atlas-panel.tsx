"use client";

import { ArrowRight, Boxes, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { EdgeTrustRow } from "@/components/graph-ui";
import { useLens } from "@/components/providers/lens-provider";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { getNode, type Schemas } from "@/lib/api";
import { EDGE_FAMILY_META, nodeTypeMeta } from "@/lib/graph/meta";
import { EDGE_FAMILIES, type EdgeFamily } from "@/lib/graph/types";
import { cn } from "@/lib/utils";

import type { AtlasIndex } from "./atlas-model";

const MAX_LISTED = 10;

/** Summary-first side panel for the node selected on the Atlas. */
export function AtlasPanel({
  index,
  nodeId,
  onSelect,
  onClose,
  className,
}: {
  index: AtlasIndex;
  nodeId: string;
  onSelect: (id: string) => void;
  onClose: () => void;
  className?: string;
}) {
  const { labelStyle, role } = useLens();
  const node = index.nodes.get(nodeId);
  const [detail, setDetail] = useState<{ id: string; data: Schemas.NodeDetail | null } | null>(null);

  useEffect(() => {
    let alive = true;
    getNode({ path: { node_id: nodeId }, query: { role }, meta: { quiet: true } })
      .then(({ data }) => alive && setDetail({ id: nodeId, data: data ?? null }))
      .catch(() => alive && setDetail({ id: nodeId, data: null }));
    return () => {
      alive = false;
    };
  }, [nodeId, role]);

  const connections = useMemo(() => {
    const ids = index.incident.get(nodeId) ?? [];
    const edges = ids.map((id) => index.edges.get(id)!).filter(Boolean);
    const byFamily = new Map<EdgeFamily, number>();
    edges.forEach((e) => byFamily.set(e.family, (byFamily.get(e.family) ?? 0) + 1));
    const sorted = [...edges].sort((a, b) => b.confidence - a.confidence);
    return { total: edges.length, byFamily, top: sorted.slice(0, MAX_LISTED) };
  }, [index, nodeId]);

  if (!node) return null;
  const meta = nodeTypeMeta(node.type);
  const Icon = meta.icon;
  const cluster = node.cluster_id ? index.clusters.get(node.cluster_id) : undefined;
  const loaded = detail?.id === nodeId;
  const summary = loaded ? (detail.data?.summary ?? detail.data?.node.description) : null;
  const href = `/node/${encodeURIComponent(node.id)}`;

  return (
    <aside
      aria-labelledby="atlas-panel-title"
      className={cn("flex flex-col overflow-hidden rounded-xl border bg-card/95 shadow-lg backdrop-blur", className)}
      data-testid="atlas-panel"
    >
      <div className="flex items-start gap-3 border-b px-4 py-3">
        <span
          className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border bg-background"
          style={{ color: `var(${meta.colorVar})` }}
        >
          <Icon className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-medium text-muted-foreground">{meta.label[labelStyle]}</p>
          <h2 id="atlas-panel-title" className="text-[15px] leading-snug font-semibold text-balance">
            {node.label}
          </h2>
          <p className="font-mono text-[10.5px] text-muted-foreground">{node.id}</p>
        </div>
        <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close summary">
          <X aria-hidden />
        </Button>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-3">
        {!loaded ? (
          <div className="space-y-1.5" aria-hidden>
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-4/5" />
          </div>
        ) : summary ? (
          <p className="text-sm leading-relaxed text-pretty text-muted-foreground">{summary}</p>
        ) : null}

        {cluster && (
          <Link
            href={`/node/${encodeURIComponent(cluster.id)}`}
            className="flex items-center gap-2 rounded-lg border bg-background/60 px-2.5 py-2 text-xs transition-colors hover:bg-muted"
          >
            <Boxes className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
            <span className="min-w-0 flex-1">
              <span className="block text-muted-foreground">In the group (hypothesis)</span>
              <span className="block truncate font-medium text-foreground">{cluster.label}</span>
            </span>
          </Link>
        )}

        <section aria-labelledby="atlas-panel-connections">
          <h3 id="atlas-panel-connections" className="mb-2 text-xs font-medium text-muted-foreground">
            {connections.total} connection{connections.total === 1 ? "" : "s"}
          </h3>
          <ul className="mb-3 flex flex-wrap gap-x-3 gap-y-1 text-xs">
            {EDGE_FAMILIES.filter((f) => connections.byFamily.has(f)).map((f) => (
              <li key={f} className="flex items-center gap-1.5">
                <span className="size-2 rounded-full" style={{ background: `var(${EDGE_FAMILY_META[f].colorVar})` }} aria-hidden />
                {EDGE_FAMILY_META[f].label[labelStyle]}
                <span className="font-mono tabular text-muted-foreground">{connections.byFamily.get(f)}</span>
              </li>
            ))}
          </ul>
          <ul className="space-y-2">
            {connections.top.map((e) => {
              const otherId = e.source === nodeId ? e.target : e.source;
              const other = index.nodes.get(otherId);
              if (!other) return null;
              const om = nodeTypeMeta(other.type);
              const OIcon = om.icon;
              return (
                <li key={e.id} className="rounded-lg border bg-background/50 px-2.5 py-2">
                  <button
                    type="button"
                    onClick={() => onSelect(otherId)}
                    className="flex w-full items-center gap-1.5 rounded text-left text-[13px] font-medium outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <OIcon className="size-3.5 shrink-0" style={{ color: `var(${om.colorVar})` }} aria-hidden />
                    <span className="truncate">{other.label}</span>
                    <span className="sr-only">({om.label[labelStyle]}). Show on map</span>
                  </button>
                  <EdgeTrustRow edge={e} className="mt-1" />
                </li>
              );
            })}
          </ul>
          {connections.total > MAX_LISTED && (
            <p className="mt-2 text-xs text-muted-foreground">
              Showing the {MAX_LISTED} strongest. Open the full view to see all {connections.total}.
            </p>
          )}
        </section>
      </div>

      <div className="border-t px-4 py-3">
        <Link href={href} className={cn(buttonVariants(), "w-full")} data-testid="atlas-open-node">
          Open {node.label.length > 28 ? "full view" : node.label}
          <ArrowRight data-icon="inline-end" aria-hidden />
        </Link>
      </div>
    </aside>
  );
}
