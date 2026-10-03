"use client";

import { CircleSlash, MessageCircleQuestion } from "lucide-react";
import Link from "next/link";

import { useLens } from "@/components/providers/lens-provider";
import { Button } from "@/components/ui/button";

import { GapSearchPanel } from "./gap-search-panel";
import { PathFlow, type MissingLinkView } from "./path-flow";
import { PathStepsList } from "./path-steps-list";
import { familyLabel } from "./route-picker";
import type { Endpoint, Family, PathResponse } from "./types";

/**
 * `status: no_supported_route`: says so plainly, then the coverage report:
 * sources queried with counts, the closest partial path (visibly
 * incomplete), the missing link and the suggested next question. Offers
 * gap search.
 */
export function NoRouteReport({
  data,
  from,
  to,
  family,
  onOpenEdge,
  highlightedEdgeId,
}: {
  data: PathResponse;
  from: Endpoint;
  to: Endpoint;
  family: Family;
  onOpenEdge: (id: string) => void;
  highlightedEdgeId: string | null;
}) {
  const { labelStyle } = useLens();
  const cov = data.coverage ?? {};
  const partial = cov.closest_partial_path ?? null;
  const steps = partial?.steps ?? [];

  const labels = new Map<string, Endpoint>([
    [from.id, from],
    [to.id, to],
  ]);
  for (const s of steps) {
    labels.set(s.from_node.id, s.from_node);
    labels.set(s.to_node.id, s.to_node);
  }
  const ml = cov.missing_link ?? null;
  const threshold = typeof data.threshold === "number" ? data.threshold : null;
  const lastId = steps.length ? steps[steps.length - 1].to_node.id : from.id;
  const startId = steps[0]?.from_node.id ?? from.id;
  const onPath = (id: string) => id === startId || steps.some((s) => s.to_node.id === id);
  const joins = (a: string, b: string) =>
    steps.find((s) => (s.from_node.id === a && s.to_node.id === b) || (s.from_node.id === b && s.to_node.id === a));
  // The partial path may reach the destination but rest on a link below the
  // threshold: then that link is the missing one, marked in place.
  const weakStep = ml ? joins(ml.from_id, ml.to_id) : undefined;
  const weakIds = steps
    .filter((s) => s === weakStep || (threshold !== null && s.edge.confidence < threshold))
    .map((s) => s.edge.id);
  const reachesTarget = onPath(to.id) && steps.length > 0;
  // Otherwise draw the gap (never a line) towards the node that can't be reached.
  let missing: MissingLinkView | null = null;
  if (ml && !weakStep) {
    const [near, far] = onPath(ml.from_id)
      ? [ml.from_id, ml.to_id]
      : onPath(ml.to_id)
        ? [ml.to_id, ml.from_id]
        : [lastId, ml.to_id];
    const farNode = labels.get(far) ?? { id: far, label: far, type: "disease" };
    missing = { fromId: near, from: labels.get(near), to: farNode, description: ml.description };
  } else if (!ml && !reachesTarget) {
    missing = {
      fromId: lastId,
      from: labels.get(lastId),
      to,
      description: "No source connects the end of this partial route to the destination.",
    };
  }
  const gapFrom = ml?.from_id ?? from.id;
  const gapTo = ml?.to_id ?? to.id;
  const sources = cov.sources_queried ?? [];
  const total = sources.reduce((n, s) => n + s.count, 0);

  return (
    <div className="space-y-6" data-testid="no-route">
      <div className="rounded-xl border-2 border-dashed border-confidence-low/50 bg-confidence-low/5 p-5" role="status">
        <p className="flex items-start gap-2 text-lg font-semibold tracking-tight text-pretty" data-testid="no-route-statement">
          <CircleSlash className="mt-1 size-5 shrink-0 text-confidence-low" aria-hidden />
          No supported route between {from.label} and {to.label}.
        </p>
        <p className="mt-1.5 max-w-prose text-sm text-muted-foreground">
          Amber found no chain of cited links where every link passes the confidence threshold
          {threshold !== null ? ` (${threshold.toFixed(2)})` : ""}
          {family !== "all" ? `, following ${familyLabel(family, labelStyle).toLowerCase()} only` : ""}. It will not draw a
          connection the evidence does not support. Here is what was checked and what is missing.
        </p>
      </div>

      <section className="space-y-3" aria-label="Closest partial route">
        <div>
          <h2 className="text-base font-semibold">Closest partial route</h2>
          <p className="text-sm text-muted-foreground">
            {partial
              ? "The best chain Amber found. It is incomplete or rests on a link below the threshold, so it is not a route."
              : "Amber found no partial chain worth showing."}
          </p>
        </div>
        {(steps.length > 0 || missing) && (
          <PathFlow
            steps={steps}
            missing={missing}
            weakEdgeIds={weakIds}
            onOpenEdge={onOpenEdge}
            highlightedEdgeId={highlightedEdgeId}
            label={`Incomplete route from ${from.label}: ${missing ? "it ends in a missing link" : "one or more links are below the threshold"}`}
          />
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-4">
          <PathStepsList
            steps={steps}
            missing={missing}
            weak={weakIds.length ? { ids: weakIds } : null}
            onOpenEdge={onOpenEdge}
            highlightedEdgeId={highlightedEdgeId}
            heading="Partial route, step by step"
          />
        </div>

        <aside className="space-y-4" aria-label="Coverage report" data-testid="coverage-report">
          <section className="rounded-xl border bg-card p-4">
            <h2 className="mb-2 text-sm font-semibold">Sources checked</h2>
            {sources.length ? (
              <table className="w-full text-sm" data-testid="sources-queried">
                <caption className="sr-only">Sources queried and how many results each contributed</caption>
                <thead>
                  <tr className="text-left text-xs text-muted-foreground">
                    <th className="pb-1 font-normal">Source</th>
                    <th className="pb-1 text-right font-normal">Results</th>
                  </tr>
                </thead>
                <tbody>
                  {sources.map((s) => (
                    <tr key={s.source} className="border-t border-border/60">
                      <td className="py-1.5">{s.source}</td>
                      <td className="py-1.5 text-right font-mono tabular">{s.count}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t text-xs text-muted-foreground">
                    <td className="pt-1.5">Total</td>
                    <td className="pt-1.5 text-right font-mono tabular">{total}</td>
                  </tr>
                </tfoot>
              </table>
            ) : (
              <p className="text-sm text-muted-foreground">The server did not list the sources it checked.</p>
            )}
          </section>

          {ml && (
            <section className="rounded-xl border bg-card p-4" data-testid="missing-link">
              <h2 className="mb-1 text-sm font-semibold">What is missing</h2>
              <p className="text-sm">{ml.description}</p>
            </section>
          )}

          {cov.suggested_question && (
            <section className="rounded-xl border bg-card p-4" data-testid="suggested-question">
              <h2 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
                <MessageCircleQuestion className="size-4 text-primary" aria-hidden /> A question worth asking next
              </h2>
              <p className="text-sm text-pretty">{cov.suggested_question}</p>
            </section>
          )}

          {family !== "all" && (
            <Button variant="outline" size="sm" nativeButton={false} render={<Link href={`/path?from=${encodeURIComponent(from.id)}&to=${encodeURIComponent(to.id)}`} />}>
              Try every kind of connection
            </Button>
          )}
        </aside>
      </div>

      <GapSearchPanel fromId={gapFrom} toId={gapTo} family={family} labels={labels} />
    </div>
  );
}
