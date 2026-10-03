"use client";

import { ArrowUpRight, Search } from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useMemo, useState } from "react";

import { useLens } from "@/components/providers/lens-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { nodeTypeMeta } from "@/lib/graph/meta";
import type { NodeType } from "@/lib/graph/types";
import { cn } from "@/lib/utils";

import type { AtlasIndex } from "./atlas-model";

const PAGE = 100;

/**
 * The same nodes as the map, as a table: the keyboard and screen-reader
 * equivalent of the canvas. Respects the type filters; sorted by centrality.
 */
export function AtlasList({
  index,
  visibleTypes,
  selectedId,
  onSelect,
}: {
  index: AtlasIndex;
  visibleTypes: Set<NodeType>;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const { labelStyle } = useLens();
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const query = useDeferredValue(q.trim().toLowerCase());

  const rows = useMemo(() => {
    const all = [...index.nodes.values()].filter(
      (n) =>
        visibleTypes.has(n.type) &&
        (!query || n.label.toLowerCase().includes(query) || n.id.toLowerCase().includes(query)),
    );
    return all.sort((a, b) => (b.centrality ?? 0) - (a.centrality ?? 0) || a.label.localeCompare(b.label));
  }, [index, visibleTypes, query]);

  const shown = rows.slice(0, limit);

  return (
    <div className="flex h-full flex-col" data-testid="atlas-list">
      <div className="flex flex-wrap items-center gap-3 border-b px-4 py-3">
        <label className="relative w-full max-w-sm">
          <span className="sr-only">Filter the list by name or ID</span>
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setLimit(PAGE);
            }}
            placeholder="Filter by name or ID"
            className="pl-8"
            maxLength={80}
          />
        </label>
        <p className="text-xs text-muted-foreground" aria-live="polite">
          {rows.length.toLocaleString("en")} of {index.nodes.size.toLocaleString("en")} shown
        </p>
      </div>
      <div className="flex-1 overflow-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">
            Everything on the map, sorted by how connected it is. Select a name to see its summary.
          </caption>
          <thead className="sticky top-0 z-10 bg-background/95 text-left text-xs text-muted-foreground backdrop-blur">
            <tr className="border-b">
              <th scope="col" className="px-4 py-2 font-medium">Name</th>
              <th scope="col" className="px-3 py-2 font-medium">Kind</th>
              <th scope="col" className="hidden px-3 py-2 font-medium md:table-cell">Group</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Connections</th>
              <th scope="col" className="px-4 py-2"><span className="sr-only">Open</span></th>
            </tr>
          </thead>
          <tbody>
            {shown.map((n) => {
              const meta = nodeTypeMeta(n.type);
              const Icon = meta.icon;
              const cluster = n.cluster_id ? index.clusters.get(n.cluster_id) : undefined;
              const selected = n.id === selectedId;
              return (
                <tr
                  key={n.id}
                  className={cn("border-b border-border/60 hover:bg-muted/50", selected && "bg-primary/10")}
                  aria-selected={selected}
                  data-testid="atlas-list-row"
                >
                  <td className="max-w-[22rem] px-4 py-1.5">
                    <button
                      type="button"
                      onClick={() => onSelect(n.id)}
                      className="flex max-w-full items-center gap-2 rounded text-left font-medium outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
                      aria-pressed={selected}
                    >
                      <Icon className="size-3.5 shrink-0" style={{ color: `var(${meta.colorVar})` }} aria-hidden />
                      <span className="truncate">{n.label}</span>
                    </button>
                    {labelStyle === "technical" && (
                      <span className="block pl-5.5 font-mono text-[10.5px] text-muted-foreground">{n.id}</span>
                    )}
                  </td>
                  <td className="px-3 py-1.5 text-muted-foreground whitespace-nowrap">{meta.label[labelStyle]}</td>
                  <td className="hidden max-w-[16rem] truncate px-3 py-1.5 text-muted-foreground md:table-cell">
                    {cluster?.label ?? "—"}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-xs tabular">
                    {index.incident.get(n.id)?.length ?? 0}
                  </td>
                  <td className="px-4 py-1.5 text-right">
                    <Link
                      href={`/node/${encodeURIComponent(n.id)}`}
                      className="inline-flex items-center gap-0.5 rounded text-xs text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      Open<span className="sr-only"> {n.label}</span>
                      <ArrowUpRight className="size-3" aria-hidden />
                    </Link>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {rows.length > limit && (
          <div className="flex justify-center p-4">
            <Button variant="outline" size="sm" onClick={() => setLimit((l) => l + PAGE)}>
              Show {Math.min(PAGE, rows.length - limit)} more
            </Button>
          </div>
        )}
        {rows.length === 0 && (
          <p className="p-6 text-center text-sm text-muted-foreground">Nothing matches. Try another name, or clear the filters.</p>
        )}
      </div>
    </div>
  );
}
