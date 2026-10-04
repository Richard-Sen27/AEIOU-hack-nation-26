"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useSyncExternalStore } from "react";

import { AtlasPreview } from "./atlas-preview";
import { HeroInput } from "./hero-input";
import { HERO_FOCUS_ID } from "./landing-config";
import { useAtlasPreview, useLandingStats } from "./use-atlas-preview";

const noopSubscribe = () => () => {};

const fmt = new Intl.NumberFormat("en-US");

/** One quiet line of live counts; absent while loading or when the request fails. */
function CountsLine() {
  const stats = useLandingStats();
  return (
    <p className="mt-3 min-h-10 text-[13px] sm:min-h-5 text-muted-foreground tabular sm:text-sm">
      {stats.status === "ready" && (
        <span data-testid="landing-counts">
          {fmt.format(stats.data.diseases)} rare diseases · {fmt.format(stats.data.links_cited)} cited links ·{" "}
          {fmt.format(stats.data.links_computed)} computed hypotheses
        </span>
      )}
    </p>
  );
}

/** The live map as a wide strip under the hero; the whole strip is one link to the Atlas. */
function HeroMap() {
  const preview = useAtlasPreview();
  const model = preview.status === "ready" ? preview.data : null;
  const focusId = model ? (model.points.has(HERO_FOCUS_ID) ? HERO_FOCUS_ID : model.topDiseaseId) : null;
  return (
    <section className="mx-auto w-full max-w-5xl px-4 pb-8 sm:px-6">
      <Link
        href="/atlas"
        aria-label="Open the Atlas"
        data-testid="atlas-preview"
        data-state={preview.status}
        className="group relative block rounded-2xl outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <div className="relative aspect-[4/3] w-full overflow-hidden rounded-2xl border bg-card/70 shadow-lg shadow-primary/5 transition-colors group-hover:border-primary/40 sm:aspect-[16/10]">
          {model ? (
            <AtlasPreview model={model} focusId={focusId} />
          ) : (
            preview.status === "loading" && (
              <div aria-hidden className="absolute inset-0 m-auto size-1/2 animate-pulse rounded-full bg-muted/60 motion-reduce:animate-none" />
            )
          )}
        </div>
        <span className="mx-auto mt-4 flex h-10 w-fit items-center gap-1.5 rounded-full bg-primary px-5 text-sm font-medium text-primary-foreground shadow-md transition-colors group-hover:bg-primary/85">
          Open the Atlas
          <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5 motion-reduce:transition-none" aria-hidden />
        </span>
      </Link>
    </section>
  );
}

/**
 * Client frame of the landing hero: the server-rendered heading, the live
 * counts, the input, and the live map strip below it.
 */
export function LandingStart({ heading }: { heading: React.ReactNode }) {
  // True after hydration (false in the server render): the e2e hydration signal.
  const ready = useSyncExternalStore(noopSubscribe, () => true, () => false);
  return (
    <>
      <section className="mx-auto flex w-full max-w-4xl flex-col items-center px-4 pt-12 pb-10 text-center sm:px-6 sm:pt-14">
        {heading}
        <CountsLine />
        <div className="mt-6 w-full" id="describe">
          <HeroInput />
        </div>
        {ready && <span hidden data-testid="landing-ready" />}
      </section>
      <HeroMap />
    </>
  );
}
