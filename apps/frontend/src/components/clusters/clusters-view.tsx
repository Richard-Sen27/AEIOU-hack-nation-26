"use client";

import { ArrowRight, Boxes, Map as MapIcon, RotateCcw, Search, TriangleAlert, WifiOff } from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useEffect, useMemo, useState } from "react";

import { OriginBadge } from "@/components/graph-ui";
import { useLens } from "@/components/providers/lens-provider";
import { PageContainer, PageHeader } from "@/components/shell/page-placeholder";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { listClusters, type ApiError, type Schemas } from "@/lib/api";
import { announce } from "@/lib/a11y";
import { cn } from "@/lib/utils";

type Load = { kind: "loading" } | { kind: "ready"; data: Schemas.ClusterSummary[] } | { kind: "error"; code: string };

const COPY = {
  plain: {
    title: "Groups of related conditions",
    description:
      "Conditions grouped by how they go wrong in the body or by shared symptoms, not by their names. The groups and their names come from analysis, so treat them as a starting point, not a fact.",
  },
  clinical: {
    title: "Disease clusters",
    description:
      "Diseases clustered by shared mechanism and phenotype rather than nomenclature. Cluster labels and summaries are generated from members' shared genes and pathways and are hypotheses.",
  },
  technical: {
    title: "Mechanism clusters",
    description:
      "Leiden communities on the combined weighted similarity graph (shared pathway, same-gene mechanism, HPO similarity). Labels and mechanism summaries are model-written from member genes and pathways: inferred.",
  },
} as const;

function idList(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
}

export function ClustersView() {
  const { labelStyle } = useLens();
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [q, setQ] = useState("");
  const query = useDeferredValue(q.trim().toLowerCase());

  useEffect(() => {
    let alive = true;
    listClusters({ meta: { quiet: true } })
      .then(({ data, error }) => {
        if (!alive) return;
        if (data) {
          setLoad({ kind: "ready", data });
          announce(`${data.length} groups loaded.`);
        } else setLoad({ kind: "error", code: (error as unknown as ApiError | undefined)?.code ?? "unknown" });
      })
      .catch((e: ApiError) => alive && setLoad({ kind: "error", code: e?.code ?? "unknown" }));
    return () => {
      alive = false;
    };
  }, [attempt]);

  const clusters = useMemo(() => {
    if (load.kind !== "ready") return [];
    return load.data
      .filter((c) => !query || c.label.toLowerCase().includes(query) || (c.mechanism_summary ?? "").toLowerCase().includes(query) || c.id.toLowerCase().includes(query))
      .sort((a, b) => b.member_count - a.member_count || a.id.localeCompare(b.id, "en", { numeric: true }));
  }, [load, query]);

  const copy = COPY[labelStyle];
  const technical = labelStyle === "technical";

  return (
    <PageContainer>
      <PageHeader eyebrow="Clusters" title={copy.title} description={copy.description}>
        <Link href="/atlas" className={buttonVariants({ variant: "outline", size: "sm" })}>
          <MapIcon data-icon="inline-start" aria-hidden /> See them on the map
        </Link>
      </PageHeader>

      {load.kind === "ready" && load.data.length > 6 && (
        <label className="relative mt-6 block max-w-sm">
          <span className="sr-only">Filter groups</span>
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter by name, gene or mechanism" className="pl-8" maxLength={80} />
        </label>
      )}

      <div className="mt-6">
        {load.kind === "loading" && (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" role="status" aria-label="Loading groups">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-48 rounded-xl" />
            ))}
          </div>
        )}

        {load.kind === "error" && (
          <div className="flex flex-col items-start gap-3 rounded-xl border bg-card p-6" data-testid="clusters-error">
            <div className="flex items-center gap-2 font-medium">
              {load.code === "network_error" ? <WifiOff className="size-4" aria-hidden /> : <TriangleAlert className="size-4" aria-hidden />}
              {load.code === "network_error"
                ? "Amber's server can't be reached"
                : load.code === "not_implemented"
                  ? "Groups are not available yet"
                  : "The groups could not be loaded"}
            </div>
            <p className="text-sm text-muted-foreground">Please try again in a moment. Search and the Atlas may still work.</p>
            <Button
              size="sm"
              onClick={() => {
                setLoad({ kind: "loading" });
                setAttempt((a) => a + 1);
              }}
            >
              <RotateCcw data-icon="inline-start" aria-hidden /> Try again
            </Button>
          </div>
        )}

        {load.kind === "ready" && load.data.length === 0 && (
          <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed bg-card/50 p-10 text-center" data-testid="clusters-empty">
            <Boxes className="size-6 text-muted-foreground" aria-hidden />
            <p className="font-medium">No groups yet</p>
            <p className="max-w-md text-sm text-muted-foreground">
              Groups appear once the analysis step of the data pipeline has run.
            </p>
          </div>
        )}

        {load.kind === "ready" && load.data.length > 0 && (
          <>
            <p className="mb-3 text-xs text-muted-foreground" aria-live="polite">
              {clusters.length} of {load.data.length} groups
            </p>
            <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" data-testid="clusters-list">
              {clusters.map((c) => {
                const genes = idList(c.attrs?.genes);
                const pathways = idList(c.attrs?.pathways);
                const href = `/node/${encodeURIComponent(c.id)}`;
                return (
                  <li key={c.id} className="group relative flex flex-col rounded-xl border bg-card p-5 transition-shadow hover:shadow-md" data-testid="cluster-card">
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <span className="font-mono text-[11px] text-muted-foreground">{c.id}</span>
                      <OriginBadge origin={c.origin ?? "inferred"} />
                    </div>
                    <h2 className="text-base leading-snug font-semibold text-balance">
                      <Link href={href} className="outline-none after:absolute after:inset-0 after:rounded-xl focus-visible:underline">
                        {c.label}
                      </Link>
                    </h2>
                    {c.mechanism_summary && (
                      <p className="mt-2 text-sm leading-relaxed text-pretty text-muted-foreground">{c.mechanism_summary}</p>
                    )}
                    <p className="mt-1.5 text-[11px] text-muted-foreground italic">Name and summary written by analysis.</p>
                    {(technical || labelStyle === "clinical") && (genes.length > 0 || pathways.length > 0) && (
                      <dl className="mt-3 space-y-1 text-xs">
                        {genes.length > 0 && (
                          <div className="flex flex-wrap gap-1">
                            <dt className="sr-only">Genes</dt>
                            {genes.slice(0, 6).map((g) => (
                              <dd key={g} className="rounded border bg-background px-1.5 py-px font-mono text-[10.5px]">{g}</dd>
                            ))}
                          </div>
                        )}
                        {pathways.length > 0 && (
                          <div className="flex flex-wrap gap-1">
                            <dt className="sr-only">Pathways</dt>
                            {pathways.slice(0, 4).map((p) => (
                              <dd key={p} className="rounded border bg-background px-1.5 py-px font-mono text-[10.5px]">{p}</dd>
                            ))}
                          </div>
                        )}
                      </dl>
                    )}
                    <div className="mt-auto flex items-center justify-between gap-2 pt-4">
                      <span className="text-sm">
                        <span className="font-semibold tabular">{c.member_count}</span>{" "}
                        <span className="text-muted-foreground">{c.member_count === 1 ? "member" : "members"}</span>
                      </span>
                      <span className="relative z-10 flex items-center gap-1">
                        <Link
                          href={`/atlas?focus=${encodeURIComponent(c.id)}`}
                          className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "text-muted-foreground")}
                        >
                          Map<span className="sr-only">: show {c.label} on the Atlas</span>
                        </Link>
                        <Link href={href} className={buttonVariants({ variant: "outline", size: "sm" })} aria-hidden tabIndex={-1}>
                          Open <ArrowRight data-icon="inline-end" aria-hidden />
                        </Link>
                      </span>
                    </div>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </div>
    </PageContainer>
  );
}
