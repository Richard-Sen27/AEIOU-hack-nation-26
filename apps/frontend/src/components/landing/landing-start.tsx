"use client";

import { useRef } from "react";

import { EntryPoints } from "./entry-points";
import { HeroInput, type HeroInputHandle } from "./hero-input";

/**
 * Client frame of the landing page: the hero (server-rendered heading passed
 * in), the input, the summary points, and the role entry points, one of
 * which focuses the input.
 */
export function LandingStart({
  heading,
  summary,
}: {
  heading: React.ReactNode;
  summary: React.ReactNode;
}) {
  const input = useRef<HeroInputHandle>(null);
  return (
    <>
      <section className="mx-auto flex w-full max-w-4xl flex-col items-center px-4 pt-12 pb-10 text-center sm:px-6 sm:pt-16">
        {heading}
        <div className="mt-8 w-full" id="describe">
          <HeroInput ref={input} />
        </div>
      </section>
      {summary}
      <EntryPoints
        onStartFromSymptoms={() => {
          document.getElementById("describe")?.scrollIntoView({ block: "center" });
          input.current?.focus();
        }}
      />
    </>
  );
}
