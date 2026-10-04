"use client";

import { ArrowRight, Database, Merge } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { NODE_TYPE_META } from "@/lib/graph/meta";
import { getNode } from "@/lib/api";
import { cn } from "@/lib/utils";

import { HERO_FOCUS_ID } from "./landing-config";
import { SectionHead } from "./section-head";
import { useInView } from "./use-atlas-preview";

// Only sources listed on the About this data page.
const SOURCES = ["MONDO", "HGNC", "HPO", "ClinVar", "Orphanet", "ClinGen", "Reactome", "Gene Ontology", "PubMed", "ClinicalTrials.gov", "NIH RePORTER"];

// A slight tilt per chip, so the names read as a pile.
const TILT = [-3, 2, -1.5, 2.5, -2, 1.5, -2.5, 3];
const MAX_CHIPS = 8;
const norm = (v: string) => v.toLowerCase().replace(/[^a-z0-9]+/g, "");

function LinkGlyph() {
  return (
    <svg viewBox="0 0 28 16" className="h-4 w-7 text-foreground" aria-hidden>
      <path d="M2 4H26" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M2 12H26" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeDasharray="3 3" />
    </svg>
  );
}

function ScoreGlyph() {
  return (
    <span className="flex items-end gap-1.5" aria-hidden>
      {(["text-confidence-high", "text-confidence-medium", "text-confidence-low"] as const).map((c, lvl) => (
        <span key={c} className={cn("flex items-end gap-[2px]", c)}>
          {[0, 1, 2].map((i) => (
            <span key={i} className={cn("w-[3px] rounded-[1px]", i < 3 - lvl ? "bg-current" : "bg-current/25")} style={{ height: 5 + i * 2.5 }} />
          ))}
        </span>
      ))}
    </span>
  );
}

const STEPS = [
  { title: "Collect", glyph: <Database className="size-4 text-primary" aria-hidden /> },
  { title: "Match", glyph: <Merge className="size-4 rotate-180 text-primary" aria-hidden /> },
  { title: "Link", glyph: <LinkGlyph /> },
  { title: "Score", glyph: <ScoreGlyph /> },
];

type Entry = { label: string; type: string; count: number; chips: string[] };

/** S3: many names for one disease become one entry. */
export function PrepSection() {
  const frame = useRef<HTMLDivElement>(null);
  const inView = useInView(frame);
  const [entry, setEntry] = useState<Entry | null | "error">(null);

  useEffect(() => {
    if (!inView) return;
    const ctrl = new AbortController();
    getNode({ path: { node_id: HERO_FOCUS_ID }, signal: ctrl.signal, meta: { quiet: true } }).then(
      ({ data, error }) => {
        if (ctrl.signal.aborted) return;
        if (error !== undefined || !data) return setEntry("error");
        const synonyms = data.synonyms ?? [];
        // Chips: names that differ from the entry and from each other beyond case and punctuation.
        const seen = new Set([norm(data.node.label)]);
        const chips = synonyms.filter((n) => !seen.has(norm(n)) && !!seen.add(norm(n))).slice(0, MAX_CHIPS);
        setEntry({ label: data.node.label, type: data.node.type, count: synonyms.length, chips });
      },
      () => !ctrl.signal.aborted && setEntry("error"),
    );
    return () => ctrl.abort();
  }, [inView]);

  const failed = entry === "error";
  const live = entry && entry !== "error" ? entry : null;
  const typeMeta = live ? (NODE_TYPE_META[live.type as keyof typeof NODE_TYPE_META] ?? NODE_TYPE_META.disease) : null;

  return (
    <section aria-labelledby="prep-heading" className="mx-auto w-full max-w-5xl px-4 py-12 sm:px-6 sm:py-14" data-testid="prep-section">
      <SectionHead id="prep-heading" title="Cleaned before you see it." sub="Public sources matched to one name, linked and scored." />
      <div ref={frame} className={cn("mt-10 grid items-center gap-8", !failed && "lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]")}>
        {!failed && (
          <div className="grid min-h-56 grid-rows-[auto_auto_auto] items-center gap-4 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,0.8fr)] sm:grid-rows-1" data-testid="prep-visual">
            <div aria-hidden className="flex min-h-40 flex-wrap content-center justify-center gap-x-2 gap-y-2.5 sm:min-h-56">
              {live?.chips.map((name, i) => (
                <span
                  key={name}
                  className="max-w-full truncate rounded-full border bg-card px-2.5 py-1 text-xs text-muted-foreground shadow-xs"
                  style={{ rotate: `${TILT[i % TILT.length]}deg` }}
                >
                  {name}
                </span>
              ))}
            </div>
            <ArrowRight className="mx-auto size-5 rotate-90 text-muted-foreground sm:rotate-0" aria-hidden />
            <div className="rounded-xl border bg-card p-4 shadow-sm">
              {live && (
                <>
                  <p className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground uppercase">
                    <span className="size-2 rounded-full" style={{ background: `var(${typeMeta!.colorVar})` }} aria-hidden />
                    {typeMeta!.label.plain}
                  </p>
                  <p className="mt-1.5 text-[15px] leading-snug font-semibold">{live.label}</p>
                  <p className="mt-3 text-sm text-muted-foreground tabular" data-testid="prep-count">
                    <span className="font-semibold text-foreground">{live.count} names</span>, 1 entry
                  </p>
                </>
              )}
            </div>
          </div>
        )}
        <div>
          <ol className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-2" data-testid="prep-steps">
            {STEPS.map((s, i) => (
              <li key={s.title} className="flex flex-col gap-3 rounded-xl border bg-card/70 p-4">
                <span className="flex h-5 items-center">{s.glyph}</span>
                <span className="text-[15px] font-semibold tracking-tight">
                  <span className="mr-1.5 font-mono text-[11px] font-normal text-muted-foreground tabular">0{i + 1}</span>
                  {s.title}
                </span>
              </li>
            ))}
          </ol>
          <Link
            href="/about-data"
            className="mt-4 inline-flex items-center gap-1 text-sm font-medium underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
          >
            How it works
            <ArrowRight className="size-3.5" aria-hidden />
          </Link>
        </div>
      </div>
      <p className="mt-10 text-center text-xs leading-relaxed text-muted-foreground/80">{SOURCES.join(" · ")}</p>
    </section>
  );
}
