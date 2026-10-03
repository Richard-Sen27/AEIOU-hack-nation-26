"use client";

import { FileSearch, HelpCircle } from "lucide-react";

import { EdgeTrustRow, NodeChip } from "@/components/graph-ui";
import { cn } from "@/lib/utils";

import type { MissingLinkView } from "./path-flow";
import type { PathStep } from "./types";

/**
 * The same route as an ordered list: the screen-reader and keyboard
 * equivalent of the flow diagram, and the compact view on small screens.
 */
export function PathStepsList({
  steps,
  highlightedEdgeId,
  onOpenEdge,
  missing,
  weak,
  heading = "Steps",
  idPrefix = "step",
}: {
  steps: PathStep[];
  highlightedEdgeId?: string | null;
  onOpenEdge: (edgeId: string) => void;
  missing?: MissingLinkView | null;
  /** Weak links of an unsupported route, with what is missing. */
  weak?: { ids: string[]; description?: string | null } | null;
  heading?: string;
  idPrefix?: string;
}) {
  return (
    <section aria-labelledby={`${idPrefix}-heading`} data-testid="path-steps">
      <h3 id={`${idPrefix}-heading`} className="mb-3 font-mono text-[10.5px] uppercase tracking-[0.14em] text-muted-foreground">
        {heading}
      </h3>
      {steps.length > 0 && (
        <p className="mb-2 flex items-center gap-2 text-sm">
          <span className="font-mono text-[11px] text-muted-foreground">Start</span>
          <NodeChip id={steps[0].from_node.id} type={steps[0].from_node.type} label={steps[0].from_node.label} />
        </p>
      )}
      <ol className="relative space-y-2 border-l border-dashed border-border pl-5">
        {steps.map((s, i) => {
          const hl = highlightedEdgeId === s.edge.id;
          const isWeak = !!weak?.ids.includes(s.edge.id);
          return (
            <li
              key={s.edge.id}
              id={`${idPrefix}-${s.edge.id}`}
              data-testid="path-step"
              data-edge-id={s.edge.id}
              data-highlighted={hl || undefined}
              data-weak={isWeak || undefined}
              className={cn(
                "relative scroll-mt-24 rounded-lg border bg-card p-3 transition-shadow",
                isWeak && "border-2 border-dashed border-confidence-low/60",
                hl && "ring-3 ring-primary",
              )}
            >
              <span
                aria-hidden
                className="absolute top-3.5 -left-[29px] flex size-4 items-center justify-center rounded-full border bg-background font-mono text-[9px] font-semibold tabular"
              >
                {i + 1}
              </span>
              <span className="sr-only">Step {i + 1}: </span>
              {isWeak && (
                <p className="mb-2 text-sm font-semibold text-confidence-low" data-testid="weak-link-note">
                  Missing link: this connection is below the confidence threshold
                  {weak?.description ? <span className="mt-0.5 block font-normal text-foreground">{weak.description}</span> : null}
                </p>
              )}
              {/* Read in the stored direction so the relation stays true ("group supports people with condition"). */}
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5 text-sm">
                {(() => {
                  const [a, b] = s.reversed ? [s.to_node, s.from_node] : [s.from_node, s.to_node];
                  return (
                    <>
                      <NodeChip id={a.id} type={a.type} label={a.label} size="sm" />
                      <EdgeTrustRow edge={s.edge} />
                      <NodeChip id={b.id} type={b.type} label={b.label} size="sm" />
                    </>
                  );
                })()}
              </div>
              <p className="mt-1 text-[11.5px] text-muted-foreground">
                Leads to <span className="font-medium text-foreground">{s.to_node.label}</span>
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={() => onOpenEdge(s.edge.id)}
                  className="inline-flex items-center gap-1.5 rounded-md text-[13px] font-medium text-foreground underline decoration-primary decoration-2 underline-offset-4 outline-none hover:decoration-foreground focus-visible:ring-2 focus-visible:ring-ring"
                  data-testid="open-evidence"
                >
                  <FileSearch className="size-3.5" aria-hidden />
                  Evidence{typeof s.edge.evidence_count === "number" ? ` (${s.edge.evidence_count})` : ""}
                </button>
                {(s.edge.contradiction_count ?? 0) > 0 && (
                  <span className="text-[12px] font-medium text-confidence-low">
                    {s.edge.contradiction_count} contradicting source{s.edge.contradiction_count === 1 ? "" : "s"}
                  </span>
                )}
              </div>
            </li>
          );
        })}
        {missing && (
          <li
            className="relative rounded-lg border-2 border-dashed border-confidence-low/50 bg-background/60 p-3"
            data-testid="path-step-missing"
          >
            <span aria-hidden className="absolute top-3.5 -left-[29px] flex size-4 items-center justify-center rounded-full border border-dashed bg-background">
              <HelpCircle className="size-3 text-confidence-low" />
            </span>
            <p className="text-sm font-semibold text-confidence-low">Missing link: no supported connection</p>
            <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
              to <NodeChip id={missing.to.id} type={missing.to.type} label={missing.to.label} size="sm" />
            </p>
            <p className="mt-1.5 text-sm">{missing.description}</p>
          </li>
        )}
      </ol>
    </section>
  );
}
