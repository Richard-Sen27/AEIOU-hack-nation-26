"use client";

import Link from "next/link";

import { CallRow } from "./call-parts";
import { usePublishedCalls } from "./use-published-calls";

const SHOWN = 3;

/**
 * Open calls for one disease, on its node page. Signed-in readers only; the
 * full list is fetched and filtered here, so the disease id never goes into a
 * request. Nothing is shown when there are none.
 */
export function DiseaseCalls({ diseaseId, className }: { diseaseId: string; className?: string }) {
  const calls = usePublishedCalls({ silent: true });
  if (calls.kind !== "ready") return null;
  const matching = calls.items.filter((c) => c.diseases.some((d) => d.id === diseaseId));
  if (!matching.length) return null;
  return (
    <section aria-labelledby="disease-calls-title" className={className} data-testid="disease-calls">
      <div className="mb-2 flex items-baseline gap-2">
        <h2 id="disease-calls-title" className="text-sm font-semibold">
          Looking for participants · {matching.length}
        </h2>
        <Link href="/calls" className="ml-auto text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline">
          All studies
        </Link>
      </div>
      <ul className="space-y-1.5">
        {matching.slice(0, SHOWN).map((c) => (
          <li key={c.id}>
            <CallRow call={c} compact />
          </li>
        ))}
      </ul>
    </section>
  );
}
