"use client";

import { Activity, ArrowRight, Boxes, Compass, PersonStanding, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ROLE_LABELS, useLens } from "@/components/providers/lens-provider";
import { useSession } from "@/components/providers/session-provider";
import { useSearch } from "@/components/search/search-provider";
import { getProfile, unwrap } from "@/lib/api";
import type { Role } from "@/lib/graph/types";
import { setPendingChatMessage } from "@/lib/handoff";
import { cn } from "@/lib/utils";

/** The spec's example message: the demo family's journey. */
export const DEMO_MESSAGE =
  "My daughter is 2, diagnosed with STXBP1 last month. Lots of seizures, not walking yet, no problems with eating.";

type Entry = {
  role: Role;
  icon: typeof Activity;
  title: string;
  body: string;
  cta: string;
};

/**
 * Where each lens starts (system spec, "Hierarchies"): patients at their
 * disease, doctors at the symptom profile, researchers at mechanism clusters,
 * guests on the guided tour. The current lens is listed first.
 */
export function EntryPoints({ onStartFromSymptoms }: { onStartFromSymptoms: () => void }) {
  const router = useRouter();
  const { role } = useLens();
  const { user, demoMode } = useSession();
  const { openSearch } = useSearch();
  const [disease, setDisease] = useState<{ id: string; label: string } | null>(null);

  // A signed-in user's confirmed disease is their starting point.
  useEffect(() => {
    if (!user) return;
    const ctrl = new AbortController();
    unwrap(getProfile({ meta: { quiet: true }, signal: ctrl.signal }))
      .then((p) => {
        const d = p?.diseases?.[0];
        if (d) setDisease({ id: d.id, label: d.label });
      })
      .catch(() => {});
    return () => ctrl.abort();
  }, [user]);

  const entries: Entry[] = [
    {
      role: "patient",
      icon: Activity,
      title: "Patients and families",
      body: disease
        ? `Start at ${disease.label}, with similar conditions and patient groups.`
        : "Start at your condition, with similar conditions and patient groups, in plain words.",
      cta: disease ? `Open ${disease.label}` : "Find your condition",
    },
    {
      role: "doctor",
      icon: PersonStanding,
      title: "Doctors",
      body: "Start from a symptom profile, with centers of expertise, studies and variant classifications.",
      cta: "Start from symptoms",
    },
    {
      role: "researcher",
      icon: Boxes,
      title: "Researchers",
      body: "Start at mechanism clusters, with variants, pathways, papers and funding, IDs shown.",
      cta: "Browse clusters",
    },
    {
      role: "guest",
      icon: Compass,
      title: "Just looking",
      body: "A short guided tour of the atlas in very simple language. No account needed.",
      cta: "Take the tour",
    },
  ];
  const ordered = [...entries.filter((e) => e.role === role), ...entries.filter((e) => e.role !== role)];

  const act = (r: Role) => {
    switch (r) {
      case "patient":
        if (disease) router.push(`/node/${encodeURIComponent(disease.id)}`);
        else openSearch();
        return;
      case "doctor":
        onStartFromSymptoms();
        return;
      case "researcher":
        router.push("/clusters");
        return;
      default:
        router.push("/atlas?tour=1");
    }
  };

  return (
    <section aria-labelledby="entry-heading" className="mx-auto w-full max-w-5xl px-4 pb-16 sm:px-6">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-2">
        <h2 id="entry-heading" className="text-lg font-semibold tracking-tight">
          Where to start
        </h2>
        <p className="text-[13px] text-muted-foreground">
          Your view decides the starting point and the wording, never what you can see.
        </p>
      </div>

      {demoMode && (
        <div
          className="mb-4 flex flex-col gap-3 rounded-xl border border-primary/40 bg-primary/10 p-4 sm:flex-row sm:items-center"
          data-testid="demo-journey"
        >
          <Sparkles className="size-5 shrink-0 text-primary" aria-hidden />
          <div className="flex-1 text-sm">
            <p className="font-medium">Try the demo journey</p>
            <p className="text-muted-foreground">
              One family, from a new STXBP1 diagnosis to a related community, a shared registry and
              a next step.
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              if (user) {
                setPendingChatMessage(DEMO_MESSAGE);
                router.push("/chat");
              } else {
                router.push("/atlas?tour=1");
              }
            }}
            className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg bg-primary px-3.5 text-sm font-medium text-primary-foreground outline-none hover:bg-primary/85 focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {user ? "Start with Dr. Wu" : "Start the tour"}
            <ArrowRight className="size-4" aria-hidden />
          </button>
        </div>
      )}

      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {ordered.map((e) => {
          const current = e.role === role;
          const Icon = e.icon;
          return (
            <li key={e.role}>
              <button
                type="button"
                onClick={() => act(e.role)}
                data-testid={`entry-${e.role}`}
                className={cn(
                  "group flex h-full w-full flex-col items-start gap-2 rounded-xl border bg-card p-4 text-left outline-none transition-colors hover:border-primary/50 focus-visible:ring-3 focus-visible:ring-ring/50",
                  current && "border-primary/60 ring-1 ring-primary/30",
                )}
              >
                <span className="flex w-full items-center gap-2">
                  <Icon className="size-4 text-primary" aria-hidden />
                  <span className="text-[15px] font-semibold tracking-tight">{e.title}</span>
                  {current && (
                    <span className="ml-auto rounded-full bg-primary/15 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-foreground">
                      Your view
                    </span>
                  )}
                </span>
                <span className="text-sm leading-relaxed text-muted-foreground">{e.body}</span>
                <span className="mt-auto inline-flex items-center gap-1 pt-1 text-sm font-medium text-foreground">
                  {e.cta}
                  <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5 motion-reduce:transition-none" aria-hidden />
                </span>
                <span className="sr-only">({ROLE_LABELS[e.role].label} view)</span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
