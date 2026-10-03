"use client";

import { ArrowRight } from "lucide-react";
import { useEffect, useState } from "react";

import { useLens } from "@/components/providers/lens-provider";
import { getNeighborhood } from "@/lib/api";
import { nodeTypeMeta } from "@/lib/graph/meta";

import type { ApiNode, Endpoint } from "./types";

/** Node types worth routing to from a starting point, in order. */
const PREFERRED = ["disease", "registry", "patient_org", "trial", "researcher", "grant", "gene", "mechanism", "pathway"];

/**
 * Only `from` is set: suggest destinations from its neighbourhood so the
 * user can pick one in a click, or search for any other.
 */
export function TargetSuggestions({ from, onPick }: { from: Endpoint; onPick: (e: Endpoint) => void }) {
  const { labelStyle } = useLens();
  const [nodes, setNodes] = useState<ApiNode[] | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- new start node
    setNodes(null);
    getNeighborhood({ path: { node_id: from.id }, signal: ctrl.signal, meta: { quiet: true } }).then(({ data }) => {
      if (ctrl.signal.aborted) return;
      const list = ((data as { nodes?: ApiNode[] } | undefined)?.nodes ?? []).filter(
        (n) => n.id !== from.id && PREFERRED.includes(n.type),
      );
      list.sort((a, b) => PREFERRED.indexOf(a.type) - PREFERRED.indexOf(b.type) || (b.centrality ?? 0) - (a.centrality ?? 0));
      setNodes(list.slice(0, 8));
    });
    return () => ctrl.abort();
  }, [from.id]);

  return (
    <section className="rounded-xl border border-dashed bg-card/50 p-5" data-testid="target-suggestions" aria-labelledby="suggest-heading">
      <h2 id="suggest-heading" className="text-base font-semibold">
        Where should the route from {from.label} lead?
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Search for any disease, gene, patient group or registry in the “To” field
        {nodes && nodes.length > 0 ? ", or start with one of its neighbours:" : "."}
      </p>
      {nodes && nodes.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2">
          {nodes.map((n) => {
            const meta = nodeTypeMeta(n.type);
            const Icon = meta.icon;
            return (
              <li key={n.id}>
                <button
                  type="button"
                  onClick={() => onPick({ id: n.id, label: n.label, type: n.type })}
                  className="group inline-flex h-8 items-center gap-1.5 rounded-full border bg-card px-3 text-[13px] outline-none transition hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50"
                  data-testid="suggested-target"
                >
                  <Icon className="size-3.5" style={{ color: `var(${meta.colorVar})` }} aria-hidden />
                  <span className="max-w-[220px] truncate">{n.label}</span>
                  <span className="sr-only">({meta.label[labelStyle]})</span>
                  <ArrowRight className="size-3 text-muted-foreground transition group-hover:translate-x-0.5" aria-hidden />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
