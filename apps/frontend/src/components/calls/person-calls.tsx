"use client";

import { CallRow } from "./call-parts";
import { usePublishedCalls } from "./use-published-calls";

/** An expert's published, open calls, for their card page. Nothing when there are none. */
export function PersonCalls({ cardId, className }: { cardId: string; className?: string }) {
  const calls = usePublishedCalls({ silent: true });
  if (calls.kind !== "ready") return null;
  const theirs = calls.items.filter((c) => c.publisher?.card_id === cardId);
  if (!theirs.length) return null;
  return (
    <section aria-labelledby="person-calls-title" className={className} data-testid="person-calls">
      <h2 id="person-calls-title" className="mb-2 text-sm font-semibold">
        Open calls · {theirs.length}
      </h2>
      <ul className="space-y-1.5">
        {theirs.map((c) => (
          <li key={c.id}>
            <CallRow call={c} compact />
          </li>
        ))}
      </ul>
    </section>
  );
}
