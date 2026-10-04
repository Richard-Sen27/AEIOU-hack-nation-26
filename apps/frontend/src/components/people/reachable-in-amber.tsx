"use client";

import Link from "next/link";

import { nodeTypeMeta } from "@/lib/graph/meta";
import { cn } from "@/lib/utils";

import { cardHref } from "./public-card";
import { usePeopleForDisease } from "./use-people";
import { VerificationLabel } from "./verification-label";

const ROLE_LABEL: Record<string, string> = { doctor: "Doctor", researcher: "Researcher" };

/**
 * "Reachable in Amber": verified doctors and researchers with a visible card
 * whose confirmed atlas entry is linked to this disease. Professionals only;
 * patients are never listed or counted. Renders nothing for guests, while
 * loading, on errors and when nobody is listed (no empty boxes).
 */
export function ReachableInAmber({ diseaseId, className }: { diseaseId: string; className?: string }) {
  const people = usePeopleForDisease(diseaseId);
  if (people.kind !== "ready" || people.data.length === 0) return null;
  return (
    <section aria-labelledby="reachable-h" className={cn("space-y-2", className)} data-testid="reachable-in-amber">
      <h2 id="reachable-h" className="text-sm font-semibold">
        Reachable in Amber
      </h2>
      <ul className="flex flex-wrap gap-2">
        {people.data.map((p) => {
          const meta = nodeTypeMeta(p.role);
          const Icon = meta.icon;
          return (
            <li key={p.card_id} className="max-w-full">
              <Link
                href={cardHref(p.card_id)}
                className="flex max-w-full items-start gap-2 rounded-lg border bg-card px-3 py-2 outline-none transition-colors hover:bg-muted/60 focus-visible:ring-3 focus-visible:ring-ring/50"
                data-testid="reachable-person"
              >
                <Icon className="mt-0.5 size-4 shrink-0" style={{ color: `var(${meta.colorVar})` }} aria-hidden />
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">{p.name}</span>
                  <span className="block text-xs text-muted-foreground">
                    {ROLE_LABEL[p.role] ?? p.role}
                    {p.institutions?.[0] && <> · {p.institutions[0].label}</>}
                  </span>
                  <VerificationLabel verification={p.verification} short className="mt-0.5" />
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
