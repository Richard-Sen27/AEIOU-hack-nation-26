"use client";

import { Database, Lightbulb, Route, SearchX, TriangleAlert, WifiOff } from "lucide-react";
import { useReducedMotion } from "motion/react";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { GraphLegend } from "@/components/graph-ui";
import { useLens } from "@/components/providers/lens-provider";
import { PageContainer, PageHeader } from "@/components/shell/page-placeholder";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { announce } from "@/lib/a11y";
import type { ApiError } from "@/lib/api/errors";
import { CONFIDENCE_LABEL } from "@/lib/graph/meta";
import type { EdgeFamily } from "@/lib/graph/types";
import { cn } from "@/lib/utils";

import { ActionView } from "./action-view";
import { EdgeEvidenceSheet } from "./edge-evidence-sheet";
import { ExplanationPanel } from "./explanation-panel";
import { NoRouteReport } from "./no-route-report";
import { PathFlow } from "./path-flow";
import { PathStepsList } from "./path-steps-list";
import { hypothesisCount, RouteAlternatives } from "./route-alternatives";
import { familyLabel, RoutePicker } from "./route-picker";
import { TargetSuggestions } from "./target-suggestions";
import { parseFamily, pathHref, type ApiNode, type Endpoint, type Family, type PathT } from "./types";
import { usePathQuery, useNode } from "./use-path-data";

const PREFIX_TYPE: Record<string, string> = {
  MONDO: "disease",
  HGNC: "gene",
  HP: "phenotype",
  CLINVAR: "variant",
  PMID: "paper",
  NCT: "trial",
  ORG: "patient_org",
  REG: "registry",
  CLUSTER: "cluster",
};
function guessType(id: string) {
  return PREFIX_TYPE[id.split(":")[0]?.toUpperCase()] ?? "disease";
}

function useEndpoint(id: string | null, picked: Map<string, Endpoint>, known: ApiNode | null): Endpoint | null {
  const pick = id ? picked.get(id) : undefined;
  const fetched = useNode(pick ? null : id, known);
  if (!id) return null;
  if (pick) return pick;
  if (fetched) return { id, label: fetched.label, type: fetched.type };
  return { id, label: id, type: guessType(id) };
}

function errorView(e: ApiError): { icon: typeof WifiOff; title: string; body: string; retry: boolean } {
  switch (e.code) {
    case "not_implemented":
      return { icon: Route, title: "Route finding isn't available yet", body: "This server can't compute routes yet. Search and the graph views still work.", retry: true };
    case "not_found":
      return { icon: SearchX, title: "One of these isn't in the atlas", body: "Check the start and destination; pick them again from the search suggestions.", retry: false };
    case "validation_error":
      return { icon: SearchX, title: "That route can't be looked up", body: "One of the ids in the address isn't valid. Pick the start and destination again.", retry: false };
    case "network_error":
      return { icon: WifiOff, title: "Amber's server can't be reached", body: "Routes can't be loaded right now. Try again in a moment.", retry: true };
    case "rate_limited":
      return { icon: TriangleAlert, title: "Please wait a moment", body: "Too many requests in a short time.", retry: true };
    default:
      return { icon: TriangleAlert, title: "The route could not be loaded", body: "Something went wrong on our side. Please try again.", retry: true };
  }
}

/** One sentence on what the route rests on: data only, or hypotheses too. */
function TrustSummary({ path }: { path: PathT }) {
  const hyp = hypothesisCount(path);
  const flagged = path.steps.filter((s) => s.edge.status !== "active").length;
  const low = path.min_confidence_level === "low";
  const dataOnly = path.all_observed && hyp === 0;
  return (
    <div
      className={cn(
        "flex items-start gap-3 rounded-xl border px-4 py-3 text-sm",
        dataOnly ? "border-confidence-high/40 bg-confidence-high/5" : "border-dashed border-foreground/30 bg-card",
      )}
      data-testid="trust-summary"
      data-observed-only={dataOnly}
    >
      {dataOnly ? (
        <Database className="mt-0.5 size-4 shrink-0 text-confidence-high" aria-hidden />
      ) : (
        <Lightbulb className="mt-0.5 size-4 shrink-0 text-status-flag" aria-hidden />
      )}
      <p className="text-pretty">
        {low && <span className="font-semibold">Low confidence: treat this route with caution. </span>}
        {dataOnly ? (
          <>
            <span className="font-semibold">Only observed data.</span> Every link on this route was observed in a cited
            source (solid lines).
          </>
        ) : (
          <>
            <span className="font-semibold">
              Includes {hyp} hypothesis link{hyp === 1 ? "" : "s"}.
            </span>{" "}
            Dashed lines are inferred, not observed: leads to check, not facts.
          </>
        )}{" "}
        {flagged > 0 && (
          <span>
            {flagged} link{flagged === 1 ? " is" : "s are"} pending or under review.{" "}
          </span>
        )}
        <span className="text-muted-foreground">Weakest link: {CONFIDENCE_LABEL[path.min_confidence_level]}.</span>
      </p>
    </div>
  );
}

function LoadingRoute() {
  return (
    <div className="space-y-4" role="status" aria-label="Finding the most trustworthy route">
      <Skeleton className="h-12 w-full rounded-xl" />
      <Skeleton className="h-[280px] w-full rounded-xl" />
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
      </div>
    </div>
  );
}

/**
 * `/path?from=<id>&to=<id>&family=dna|symptoms|research|all`
 * "From a disease, to a cited connection, to a shared action."
 */
export function PathView() {
  const router = useRouter();
  const params = useSearchParams();
  const { labelStyle } = useLens();
  const reduce = useReducedMotion();
  const fromId = params.get("from") || null;
  const toId = params.get("to") || null;
  const family = parseFamily(params.get("family"));
  const [attempt, setAttempt] = useState(0);
  const query = usePathQuery(fromId, toId, family, attempt);
  const [picked] = useState(() => new Map<string, Endpoint>());
  const [selected, setSelected] = useState(0);
  const [openEdge, setOpenEdge] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<string | null>(null);

  const data = query.kind === "ready" ? query.data : null;
  const paths = useMemo(() => data?.paths ?? [], [data]);
  const path = paths[Math.min(selected, Math.max(0, paths.length - 1))] ?? null;
  const knownFrom = path?.steps[0]?.from_node ?? data?.coverage?.closest_partial_path?.steps[0]?.from_node ?? null;
  const knownTo = path?.steps[path.steps.length - 1]?.to_node ?? null;
  const from = useEndpoint(fromId, picked, knownFrom?.id === fromId ? knownFrom : null);
  const to = useEndpoint(toId, picked, knownTo?.id === toId ? knownTo : null);

  // New result: back to the best route, announce it.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset on new response
    setSelected(0);
    setHighlight(null);
    if (!data) return;
    if (data.status === "no_supported_route") {
      announce("No supported route found. Showing what was checked and what is missing.");
    } else if (data.paths?.length) {
      const p = data.paths[0];
      announce(
        `Found ${data.paths.length} route${data.paths.length === 1 ? "" : "s"}. Showing the most trustworthy: ${p.steps.length} steps, ${
          hypothesisCount(p) === 0 ? "only observed data" : `${hypothesisCount(p)} hypothesis links`
        }.`,
      );
    }
  }, [data]);

  useEffect(() => {
    if (query.kind === "error") announce("The route could not be loaded.", "assertive");
  }, [query.kind]);

  const go = useCallback(
    (next: { from?: string | null; to?: string | null; family?: Family }) => {
      router.push(
        pathHref({
          from: next.from === undefined ? fromId : next.from,
          to: next.to === undefined ? toId : next.to,
          family: next.family ?? family,
        }),
        { scroll: false },
      );
    },
    [router, fromId, toId, family],
  );

  const pick = (which: "from" | "to") => (e: Endpoint | null) => {
    if (e) picked.set(e.id, e);
    go({ [which]: e?.id ?? null });
  };

  const selectRoute = (i: number) => {
    setSelected(i);
    setHighlight(null);
    const p = paths[i];
    if (p) announce(`Showing route ${i + 1} of ${paths.length}: ${p.steps.length} steps.`);
  };

  const cite = useCallback(
    (edgeId: string) => {
      setHighlight(edgeId);
      document.getElementById(`step-${edgeId}`)?.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
      announce("Highlighted the cited step.");
    },
    [reduce],
  );

  const allSteps = path?.steps ?? data?.coverage?.closest_partial_path?.steps ?? [];
  const openStep = allSteps.find((s) => s.edge.id === openEdge) ?? null;
  const families = [...new Set(allSteps.map((s) => s.edge.family))] as EdgeFamily[];

  const title =
    from && to ? (
      <>
        How <span className="text-primary">{from.label}</span> connects to{" "}
        <span className="text-primary">{to.label}</span>
      </>
    ) : (
      "How two things are connected"
    );

  return (
    <PageContainer className="space-y-8">
      <PageHeader
        eyebrow="Path"
        title={title}
        description="The most trustworthy cited route, not the shortest."
      />

      <div className="rounded-xl border bg-card/60 p-4 shadow-xs sm:p-5">
        <RoutePicker
          from={from}
          to={to}
          family={family}
          onFrom={pick("from")}
          onTo={pick("to")}
          onSwap={() => go({ from: toId, to: fromId })}
          onFamily={(f) => go({ family: f })}
        />
      </div>

      {!fromId && !toId && (
        <section className="bg-atlas-grid rounded-xl border border-dashed p-6 text-sm text-muted-foreground" data-testid="path-empty">
          <p className="max-w-prose">
            Pick a starting point (your condition, a gene or a symptom) and a destination (another condition, a patient
            group, a registry). Amber finds the chain of cited links between them that it trusts most, explains it in
            your lens, and shows what you could do together.
          </p>
        </section>
      )}

      {from && !toId && <TargetSuggestions from={from} onPick={pick("to")} />}

      {!fromId && toId && (
        <p className="text-sm text-muted-foreground" data-testid="need-from">
          Now choose where the route should start.
        </p>
      )}

      {query.kind === "loading" && <LoadingRoute />}

      {query.kind === "error" &&
        (() => {
          const v = errorView(query.error);
          const Icon = v.icon;
          return (
            <section className="flex flex-col items-center gap-3 rounded-xl border border-dashed px-6 py-10 text-center" role="alert" data-testid="path-error" data-code={query.error.code}>
              <Icon className="size-6 text-muted-foreground" aria-hidden />
              <h2 className="text-base font-semibold">{v.title}</h2>
              <p className="max-w-md text-sm text-muted-foreground">{v.body}</p>
              {v.retry && (
                <Button variant="outline" onClick={() => setAttempt((a) => a + 1)}>
                  Try again
                </Button>
              )}
            </section>
          );
        })()}

      {data && data.status === "no_supported_route" && from && to && (
        <NoRouteReport
          data={data}
          from={from}
          to={to}
          family={family}
          onOpenEdge={setOpenEdge}
          highlightedEdgeId={highlight}
        />
      )}

      {data && data.status === "ok" && !path && (
        <section className="rounded-xl border border-dashed p-6 text-sm text-muted-foreground" data-testid="path-empty-result">
          The server reported a route but sent no steps. Please try again.
        </section>
      )}

      {data && data.status === "ok" && path && from && to && (
        <div className="space-y-6" data-testid="path-result" data-path-id={path.path_id}>
          <RouteAlternatives paths={paths} selected={selected} onSelect={selectRoute} />
          <TrustSummary path={path} />
          <div className="space-y-2">
            <PathFlow
              steps={path.steps}
              highlightedEdgeId={highlight}
              onOpenEdge={setOpenEdge}
              label={`Route diagram: ${path.steps.length} steps from ${from.label} to ${to.label}. The same steps follow as a list.`}
            />
            <div className="flex flex-wrap items-center justify-between gap-2">
              <GraphLegend families={families} orientation="horizontal" className="border-0 bg-transparent p-0 backdrop-blur-none" />
              <span className="text-[11px] text-muted-foreground">
                Following: {familyLabel(family, labelStyle)} · click a link for its sources
              </span>
            </div>
          </div>
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <PathStepsList steps={path.steps} highlightedEdgeId={highlight} onOpenEdge={setOpenEdge} heading={`Route ${selected + 1}, step by step`} />
            <div className="lg:sticky lg:top-20 lg:self-start">
              <ExplanationPanel path={path} onCite={cite} />
            </div>
          </div>
          <ActionView path={path} fromLabel={from.label} toLabel={to.label} />
        </div>
      )}

      <EdgeEvidenceSheet edgeId={openEdge} step={openStep} onClose={() => setOpenEdge(null)} />
    </PageContainer>
  );
}
