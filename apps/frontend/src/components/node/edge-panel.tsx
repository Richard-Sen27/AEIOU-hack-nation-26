"use client";

import { ArrowDown, ArrowLeft, Flag, Scale, TriangleAlert, Users } from "lucide-react";
import { useEffect, useState } from "react";

import { ConfidenceBadge, EvidenceList, NodeChip, OriginBadge, StatusFlag, TIER_SHORT } from "@/components/graph-ui";
import { useLens } from "@/components/providers/lens-provider";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { getEdgeEvidence, type ApiError, type Schemas } from "@/lib/api";
import { CONFIDENCE_LABEL, EDGE_FAMILY_META, relationLabel } from "@/lib/graph/meta";
import type { EvidenceTier } from "@/lib/graph/types";
import { cn } from "@/lib/utils";

type NodeLite = Pick<Schemas.Node, "id" | "type" | "label">;

const FEATURE_LABEL: Record<string, string> = {
  shared_hpo: "Shared symptoms",
  bma_similarity: "Symptom similarity score",
  gene: "Gene",
  mechanism: "Mechanism",
  mechanisms: "Mechanisms",
  pathways: "Shared pathways",
  shared_people: "Shared researchers",
  truncating_share: "Share of truncating variants",
  missense_share: "Share of missense variants",
  frequency: "How often",
  note: "Note",
};
const HIDDEN_FEATURES = new Set(["label"]);

function isIdLike(v: unknown): v is string {
  return typeof v === "string" && /^[A-Z][A-Za-z_]*:[^\s]+$/.test(v);
}

function FeatureValue({ value, nodes }: { value: unknown; nodes: Map<string, NodeLite> }) {
  if (Array.isArray(value)) {
    return (
      <span className="flex flex-wrap gap-1">
        {value.map((v, i) => (
          <FeatureValue key={i} value={v} nodes={nodes} />
        ))}
      </span>
    );
  }
  if (isIdLike(value)) {
    const n = nodes.get(value);
    if (n) return <NodeChip id={n.id} type={n.type} label={n.label} size="sm" />;
    const mech = /^MECH:(.+)$/.exec(value);
    if (mech) return <span className="rounded border bg-background px-1.5 py-px text-xs">{mech[1].replace(/_/g, " ")}</span>;
    return <span className="rounded border bg-background px-1.5 py-px font-mono text-[11px]">{value}</span>;
  }
  if (typeof value === "number") {
    return <span className="font-mono text-xs tabular">{value <= 1 && value >= 0 && !Number.isInteger(value) ? value.toFixed(2) : value}</span>;
  }
  return <span className="text-xs">{String(value)}</span>;
}

/** Edge / trust panel: everything behind one connection. */
export function EdgePanel({
  edge,
  nodes,
  onBack,
  onFlag,
}: {
  edge: Schemas.Edge;
  nodes: Map<string, NodeLite>;
  onBack: () => void;
  onFlag: () => void;
}) {
  const { labelStyle } = useLens();
  const [state, setState] = useState<{ id: string; data: Schemas.EdgeEvidence | null; error?: string } | null>(null);

  useEffect(() => {
    let alive = true;
    getEdgeEvidence({ path: { edge_id: edge.id }, meta: { quiet: true } })
      .then(({ data, error }) => {
        if (alive) setState({ id: edge.id, data: data ?? null, error: (error as unknown as ApiError | undefined)?.code });
      })
      .catch(() => alive && setState({ id: edge.id, data: null, error: "network_error" }));
    return () => {
      alive = false;
    };
  }, [edge.id]);

  const loaded = state?.id === edge.id;
  const ev = loaded ? state.data : null;
  const source = nodes.get(edge.source_id) ?? ev?.source;
  const target = nodes.get(edge.target_id) ?? ev?.target;
  const status = edge.status;
  const confidence = ev?.confidence_breakdown.result ?? edge.confidence;
  const evidence = ev ? [...ev.supporting, ...ev.contradicting] : undefined;
  const family = EDGE_FAMILY_META[edge.family];
  const features = Object.entries(edge.features ?? ev?.edge.features ?? {}).filter(([k]) => !HIDDEN_FEATURES.has(k));
  const counterexample = edge.relation === "same_gene_different_mechanism";
  const similar = edge.relation === "similar_symptoms";
  const technical = labelStyle === "technical";

  return (
    <section aria-labelledby="edge-panel-title" className="flex flex-col" data-testid="edge-panel">
      <div className="flex items-center gap-2 border-b px-4 py-2.5">
        <Button variant="ghost" size="sm" onClick={onBack} className="-ml-2">
          <ArrowLeft data-icon="inline-start" aria-hidden /> Back
        </Button>
        <span className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">
          <span className="size-2 rounded-full" style={{ background: `var(${family.colorVar})` }} aria-hidden />
          {family.label[labelStyle]}
        </span>
      </div>

      <div className="space-y-4 px-4 py-4">
        <div>
          <h2 id="edge-panel-title" className="sr-only">
            Connection: {source?.label} {relationLabel(edge.relation, labelStyle)} {target?.label}
          </h2>
          <div className="flex flex-col items-start gap-1.5">
            {source && <NodeChip id={source.id} type={source.type} label={source.label} />}
            <span className={cn("flex items-center gap-1.5 pl-2 text-sm font-medium", technical && "font-mono text-xs")} data-testid="edge-relation">
              <ArrowDown className="size-3.5 text-muted-foreground" aria-hidden />
              {relationLabel(edge.relation, labelStyle)}
            </span>
            {target && <NodeChip id={target.id} type={target.type} label={target.label} />}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <ConfidenceBadge confidence={confidence} evidence={evidence} showScore={technical} />
            <OriginBadge origin={edge.origin} />
          </div>
          {status !== "active" && <StatusFlag status={status} withDescription className="mt-2 w-full" />}
        </div>

        {counterexample && (
          <div className="flex gap-2.5 rounded-lg border border-primary/50 bg-primary/10 px-3 py-2.5 text-sm" role="note" data-testid="counterexample">
            <Scale className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
            <p>
              <span className="font-semibold">Counterexample: same gene, different mechanism.</span>{" "}
              <span className="text-muted-foreground">
                These conditions share a gene, but the gene goes wrong in different ways (for example more
                activity in one, less in the other). That is why they sit in different mechanism groups, and
                why a treatment for one may not suit the other.
              </span>
            </p>
          </div>
        )}
        {similar && (
          <div className="flex gap-2.5 rounded-lg border bg-muted/50 px-3 py-2.5 text-sm" role="note" data-testid="similar-symptoms-note">
            <Users className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
            <p>
              <span className="font-semibold">Similar experience, possibly different cause.</span>{" "}
              <span className="text-muted-foreground">
                People with these conditions share symptoms. That does not mean the same cause or the same
                treatment.
              </span>
            </p>
          </div>
        )}

        {features.length > 0 && (
          <section aria-labelledby="edge-features" data-testid="edge-features">
            <h3 id="edge-features" className="mb-1.5 text-xs font-medium text-muted-foreground">
              {edge.origin === "inferred" ? "Why the analysis suggests this" : "Details"}
            </h3>
            <dl className="space-y-2 rounded-lg border bg-background/50 p-3">
              {features.map(([k, v]) => (
                <div key={k} className="grid gap-1">
                  <dt className="text-[11px] text-muted-foreground">
                    {FEATURE_LABEL[k] ?? k.replace(/_/g, " ")}
                    {technical && <span className="ml-1 font-mono opacity-70">({k})</span>}
                  </dt>
                  <dd>
                    <FeatureValue value={v} nodes={nodes} />
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        )}

        <section aria-labelledby="edge-breakdown" data-testid="confidence-breakdown">
          <h3 id="edge-breakdown" className="mb-1.5 text-xs font-medium text-muted-foreground">
            How sure we are
          </h3>
          {!loaded ? (
            <Skeleton className="h-20 w-full" />
          ) : ev ? (
            <div className="rounded-lg border bg-background/50 p-3 text-xs">
              <table className="w-full">
                <caption className="sr-only">Confidence breakdown</caption>
                <tbody>
                  {ev.confidence_breakdown.supporting.map((t) => (
                    <tr key={t.evidence_id}>
                      <th scope="row" className="py-0.5 text-left font-normal text-muted-foreground">
                        {TIER_SHORT[t.tier as EvidenceTier] ?? t.tier}
                      </th>
                      <td className="py-0.5 text-right font-mono tabular">weight {t.weight.toFixed(1)}</td>
                    </tr>
                  ))}
                  <tr className="border-t">
                    <th scope="row" className="pt-1.5 text-left font-medium">Support from sources</th>
                    <td className="pt-1.5 text-right font-mono tabular">{ev.confidence_breakdown.support_score.toFixed(2)}</td>
                  </tr>
                  <tr>
                    <th scope="row" className={cn("py-0.5 text-left font-normal", ev.confidence_breakdown.n_contradicting ? "text-confidence-low" : "text-muted-foreground")}>
                      Contradicting sources ({ev.confidence_breakdown.n_contradicting} × {ev.confidence_breakdown.penalty_per_contradiction.toFixed(2)})
                    </th>
                    <td className="py-0.5 text-right font-mono tabular">−{ev.confidence_breakdown.penalty.toFixed(2)}</td>
                  </tr>
                  <tr className="border-t">
                    <th scope="row" className="pt-1.5 text-left font-semibold">Confidence</th>
                    <td className="pt-1.5 text-right font-mono font-semibold tabular">
                      {ev.confidence_breakdown.result.toFixed(2)} · {CONFIDENCE_LABEL[ev.confidence_breakdown.level]}
                    </td>
                  </tr>
                </tbody>
              </table>
              {technical && (
                <p className="mt-2 border-t pt-2 font-mono text-[10.5px] break-all text-muted-foreground">{ev.confidence_breakdown.formula}</p>
              )}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              Confidence {confidence.toFixed(2)} ({CONFIDENCE_LABEL[confidence >= 0.8 ? "high" : confidence >= 0.5 ? "medium" : "low"]}). The
              breakdown could not be loaded.
            </p>
          )}
        </section>

        <section aria-labelledby="edge-sources">
          <h3 id="edge-sources" className="mb-1.5 text-xs font-medium text-muted-foreground">
            Sources
          </h3>
          {!loaded ? (
            <div className="space-y-2">
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-16 w-full" />
            </div>
          ) : ev ? (
            <>
              {ev.contradicting.length > 0 && (
                <p className="mb-2 flex items-start gap-1.5 text-sm" role="note" data-testid="contradiction-note">
                  <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-confidence-low" aria-hidden />
                  {ev.contradicting.length} source{ev.contradicting.length === 1 ? "" : "s"} contradict
                  {ev.contradicting.length === 1 ? "s" : ""} this connection, shown next to the supporting ones.
                </p>
              )}
              <EvidenceList evidence={evidence ?? []} className="md:grid-cols-1 2xl:grid-cols-2" />
            </>
          ) : (
            <p className="text-sm text-muted-foreground" role="status">
              {state?.error === "not_implemented"
                ? "Source details are not available yet."
                : state?.error === "network_error"
                  ? "Sources could not be loaded because the server is not reachable."
                  : "Sources could not be loaded right now."}
            </p>
          )}
        </section>

        <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-3">
          <p className="text-[11px] text-muted-foreground">
            {technical && <span className="font-mono">{edge.id} · </span>}
            {ev?.open_flags ? `${ev.open_flags} open flag${ev.open_flags === 1 ? "" : "s"} · ` : ""}
            Data version {edge.data_version ?? ev?.edge.data_version ?? "unknown"}
          </p>
          <Button variant="outline" size="sm" onClick={onFlag} data-testid="flag-edge">
            <Flag data-icon="inline-start" aria-hidden /> Flag this connection
          </Button>
        </div>
      </div>
    </section>
  );
}
