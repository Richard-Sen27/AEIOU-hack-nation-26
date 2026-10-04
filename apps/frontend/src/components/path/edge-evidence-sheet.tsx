"use client";

import { ArrowRight, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { ConfidenceBadge, EvidenceList, NodeChip, OriginBadge, StatusFlag, TIER_SHORT } from "@/components/graph-ui";
import { useLens } from "@/components/providers/lens-provider";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { getEdgeEvidence } from "@/lib/api";
import type { ApiError } from "@/lib/api/errors";
import { CONFIDENCE_LABEL, EDGE_FAMILY_META, ORIGIN_META, relationLabel } from "@/lib/graph/meta";
import type { Evidence as GraphEvidence } from "@/lib/graph/types";
import { cn } from "@/lib/utils";

import type { EdgeEvidence, PathStep } from "./types";

type State =
  | { kind: "loading" }
  | { kind: "ready"; data: EdgeEvidence }
  | { kind: "error"; error: ApiError };

function errorCopy(e: ApiError) {
  if (e.code === "not_implemented") return "Evidence lookup is not available on this server yet.";
  if (e.code === "not_found") return "This link is no longer in the atlas (the data may have been updated).";
  if (e.code === "network_error") return "Amber's server can't be reached, so the sources can't be loaded right now.";
  return "The sources for this link could not be loaded. Please try again.";
}

const capitalize = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);

function FeatureList({ features }: { features: Record<string, unknown> }) {
  // "explanation" is shown as its own line above this list.
  const entries = Object.entries(features).filter(([k, v]) => k !== "explanation" && v !== null && v !== undefined && v !== "");
  if (!entries.length) return null;
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
      {entries.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted-foreground">{k.replace(/_/g, " ")}</dt>
          <dd className="font-mono break-words">{Array.isArray(v) ? v.join(", ") : typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * `GET /edge/{id}/evidence`: sources with links, tier, quote and retrieved
 * date; the confidence breakdown; contradicting evidence beside what it
 * contradicts.
 */
export function EdgeEvidenceSheet({
  edgeId,
  step,
  onClose,
}: {
  edgeId: string | null;
  /** The path step for this edge, shown while the evidence loads. */
  step?: PathStep | null;
  onClose: () => void;
}) {
  const { labelStyle } = useLens();
  const [state, setState] = useState<State>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!edgeId) return;
    const ctrl = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- new edge, new request
    setState({ kind: "loading" });
    getEdgeEvidence({ path: { edge_id: edgeId }, signal: ctrl.signal, meta: { quiet: true } }).then(({ data, error }) => {
      if (ctrl.signal.aborted) return;
      if (error) {
        const err = error as unknown as ApiError;
        if (err.code !== "aborted") setState({ kind: "error", error: err });
      } else if (data) setState({ kind: "ready", data: data as EdgeEvidence });
    });
    return () => ctrl.abort();
  }, [edgeId, attempt]);

  const ready = state.kind === "ready" ? state.data : null;
  const edge = ready?.edge ?? step?.edge ?? null;
  const source = ready?.source ?? (step ? (step.reversed ? step.to_node : step.from_node) : null);
  const target = ready?.target ?? (step ? (step.reversed ? step.from_node : step.to_node) : null);
  const evidence: GraphEvidence[] = ready ? [...ready.supporting, ...ready.contradicting] : [];
  const bd = ready?.confidence_breakdown;

  return (
    <Sheet open={!!edgeId} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full gap-0 overflow-y-auto data-[side=right]:w-full data-[side=right]:sm:max-w-xl" data-testid="evidence-sheet">
        <SheetHeader className="gap-3 border-b p-5 pr-12">
          <p className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-muted-foreground">
            Evidence for one link
          </p>
          <SheetTitle className="text-lg leading-snug font-semibold">
            {edge ? (labelStyle === "technical" ? relationLabel(edge.relation, labelStyle) : capitalize(relationLabel(edge.relation, labelStyle))) : "Loading link…"}
          </SheetTitle>
          {source && target && (
            <div className="flex flex-wrap items-center gap-1.5">
              <NodeChip id={source.id} type={source.type} label={source.label} size="sm" />
              <ArrowRight className="size-3.5 text-muted-foreground" aria-hidden />
              <NodeChip id={target.id} type={target.type} label={target.label} size="sm" />
            </div>
          )}
          {edge && (
            <div className="flex flex-wrap items-center gap-1.5">
              <ConfidenceBadge confidence={edge.confidence} evidence={evidence.length ? evidence : undefined} showScore />
              <OriginBadge origin={edge.origin} />
              <StatusFlag status={edge.status} withDescription />
              <span className="text-[11px] text-muted-foreground">{EDGE_FAMILY_META[edge.family].label[labelStyle]}</span>
            </div>
          )}
          <SheetDescription className="text-[13px]">
            {edge?.origin === "observed"
              ? "Data: this link was observed in the cited sources below."
              : edge
                ? `${ORIGIN_META[edge.origin].label.plain}: ${ORIGIN_META[edge.origin].description} Treat it as a lead, not a fact.`
                : "Sources, quotes and how confident Amber is in this link."}
          </SheetDescription>
        </SheetHeader>

        <div className="space-y-6 p-5">
          {state.kind === "loading" && (
            <div className="space-y-3" role="status" aria-label="Loading evidence">
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-24 w-full" />
            </div>
          )}

          {state.kind === "error" && (
            <div className="flex items-start gap-3 rounded-lg border border-dashed p-4 text-sm" role="alert">
              <TriangleAlert className="mt-0.5 size-4 shrink-0 text-status-flag" aria-hidden />
              <div className="space-y-2">
                <p>{errorCopy(state.error)}</p>
                {state.error.code !== "not_found" && (
                  <button
                    type="button"
                    onClick={() => setAttempt((a) => a + 1)}
                    className="text-[13px] font-medium underline underline-offset-4"
                  >
                    Try again
                  </button>
                )}
              </div>
            </div>
          )}

          {ready && (
            <>
              {ready.contradicting.length > 0 && (
                <p
                  className="flex items-start gap-2 rounded-lg border border-confidence-low/40 bg-confidence-low/5 px-3 py-2 text-sm"
                  data-testid="contradiction-notice"
                >
                  <TriangleAlert className="mt-0.5 size-4 shrink-0 text-confidence-low" aria-hidden />
                  <span>
                    {ready.contradicting.length} source{ready.contradicting.length === 1 ? "" : "s"} contradict
                    {ready.contradicting.length === 1 ? "s" : ""} this link. They are shown beside the supporting
                    sources and lower its confidence.
                  </span>
                </p>
              )}

              <section aria-labelledby="ev-sources">
                <h3 id="ev-sources" className="mb-2 text-sm font-semibold">
                  Sources
                </h3>
                <EvidenceList evidence={evidence} />
              </section>

              {bd && (
                <section aria-labelledby="ev-breakdown" className="rounded-lg border bg-muted/40 p-4" data-testid="confidence-breakdown">
                  <h3 id="ev-breakdown" className="mb-1 text-sm font-semibold">
                    How confidence is calculated
                  </h3>
                  <p className="mb-3 text-xs text-muted-foreground">
                    Each supporting source counts by how strong that kind of source is; each contradicting source
                    subtracts a penalty.
                  </p>
                  <table className="w-full text-xs">
                    <caption className="sr-only">Supporting sources and their weights</caption>
                    <thead>
                      <tr className="text-left text-muted-foreground">
                        <th className="pb-1 font-normal">Supporting source</th>
                        <th className="pb-1 text-right font-normal">Weight</th>
                      </tr>
                    </thead>
                    <tbody className="font-mono tabular">
                      {bd.supporting.map((t) => (
                        <tr key={t.evidence_id} className="border-t border-border/60">
                          <td className="py-1 font-sans">{TIER_SHORT[t.tier] ?? t.tier}</td>
                          <td className="py-1 text-right">{t.weight.toFixed(2)}</td>
                        </tr>
                      ))}
                      <tr className="border-t">
                        <td className="py-1 font-sans">Support 1 − ∏(1 − w)</td>
                        <td className="py-1 text-right">{bd.support_score.toFixed(2)}</td>
                      </tr>
                      <tr>
                        <td className={cn("py-1 font-sans", bd.n_contradicting > 0 && "text-confidence-low")}>
                          Contradictions {bd.n_contradicting} × {bd.penalty_per_contradiction.toFixed(2)}
                        </td>
                        <td className={cn("py-1 text-right", bd.n_contradicting > 0 && "text-confidence-low")}>
                          −{bd.penalty.toFixed(2)}
                        </td>
                      </tr>
                      <tr className="border-t font-semibold">
                        <td className="py-1 font-sans">Confidence ({CONFIDENCE_LABEL[bd.level]})</td>
                        <td className="py-1 text-right">{bd.result.toFixed(2)}</td>
                      </tr>
                    </tbody>
                  </table>
                  {bd.formula && <p className="mt-2 font-mono text-[10.5px] break-words text-muted-foreground">{bd.formula}</p>}
                </section>
              )}

              {edge?.features && Object.keys(edge.features).length > 0 && (
                <section aria-labelledby="ev-features" className="space-y-2">
                  <h3 id="ev-features" className="text-sm font-semibold">
                    {edge.origin === "inferred" ? "Why this was inferred" : "Details"}
                  </h3>
                  {edge.origin === "inferred" && edge.explanation && (
                    <p className="rounded-lg border border-dashed px-3 py-2 text-[13px]" data-testid="evidence-explanation">
                      {edge.explanation} <span className="text-muted-foreground">A hypothesis from the analysis, not an established fact.</span>
                    </p>
                  )}
                  <FeatureList features={edge.features} />
                </section>
              )}

              {(ready.open_flags ?? 0) > 0 && (
                <p className="text-xs text-muted-foreground">
                  {ready.open_flags} open flag{ready.open_flags === 1 ? "" : "s"} from users: this link is being re-checked.
                </p>
              )}
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
