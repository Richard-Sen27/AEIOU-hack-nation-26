"use client";

import { CONFIDENCE_LABEL } from "@/lib/graph/meta";
import { cn } from "@/lib/utils";

import type { PathT } from "./types";

export function hypothesisCount(p: PathT) {
  return p.steps.filter((s) => s.edge.origin !== "observed").length;
}

/** Top-k routes, most trustworthy first; one is selected. */
export function RouteAlternatives({
  paths,
  selected,
  onSelect,
}: {
  paths: PathT[];
  selected: number;
  onSelect: (i: number) => void;
}) {
  if (paths.length < 2) return null;
  return (
    <fieldset data-testid="route-alternatives">
      <legend className="mb-2 font-mono text-[10.5px] uppercase tracking-[0.14em] text-muted-foreground">
        {paths.length} routes, most trustworthy first
      </legend>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {paths.map((p, i) => {
          const hyp = hypothesisCount(p);
          const flagged = p.steps.filter((s) => s.edge.status !== "active").length;
          const active = i === selected;
          return (
            <label
              key={p.path_id}
              className={cn(
                "relative flex cursor-pointer flex-col gap-1 rounded-lg border bg-card px-3 py-2.5 text-sm transition",
                "has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-ring/50",
                active ? "border-primary ring-1 ring-primary" : "hover:bg-muted/60",
              )}
              data-testid="route-option"
              data-selected={active || undefined}
            >
              <input
                type="radio"
                name="route"
                className="sr-only"
                checked={active}
                onChange={() => onSelect(i)}
              />
              <span className="flex items-center justify-between gap-2">
                <span className="font-semibold">
                  Route {i + 1}
                  {i === 0 && <span className="ml-1.5 text-xs font-normal text-muted-foreground">most trustworthy</span>}
                </span>
                <span className="font-mono text-[11px] text-muted-foreground tabular">
                  {p.steps.length} step{p.steps.length === 1 ? "" : "s"}
                </span>
              </span>
              <span className="text-xs text-muted-foreground">
                Weakest link: {CONFIDENCE_LABEL[p.min_confidence_level]} ·{" "}
                {hyp === 0 ? "data only" : `${hyp} hypothesis link${hyp === 1 ? "" : "s"}`}
                {flagged > 0 ? ` · ${flagged} under review` : ""}
              </span>
              <span className="line-clamp-2 text-xs">
                via {p.steps.slice(0, -1).map((s) => s.to_node.label).join(" → ") || "a direct link"}
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
