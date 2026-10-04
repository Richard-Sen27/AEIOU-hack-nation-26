"use client";

import { useSyncExternalStore } from "react";

import { HeroInput } from "./hero-input";
import { HeroMap } from "./hero-map";
import { useLandingStats } from "./use-atlas-preview";

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
