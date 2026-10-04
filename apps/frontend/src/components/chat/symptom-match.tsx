"use client";

import { ChevronDown, ListOrdered } from "lucide-react";
import Link from "next/link";
import { useId, useState } from "react";

import { atlasHandoffClick } from "@/components/atlas/atlas-handoff";
import { OffMapMark } from "@/components/atlas/atlas-offmap";
import { nodeTypeMeta } from "@/lib/graph/meta";
import { cn } from "@/lib/utils";

import { EdgeItem } from "./edge-item";
import { useEdges } from "./graph-data";
import type { Schemas } from "./types";

type SymptomMatch = Schemas.SymptomMatch;
type Item = Schemas.SymptomMatchItem;
type Term = Schemas.SymptomMatchTerm;

export const SYMPTOM_MATCH_NOTE = "Symptom overlap in the atlas data, not a diagnosis.";

const MATCH_HINT: Record<Term["match"], string | null> = {
  same: null,
  broader: "broader term",
  more_specific: "narrower term",
};

/** The cited has_phenotype links of one condition, loaded when opened. */
function Sources({ ids }: { ids: string[] }) {
  const edges = useEdges(ids);
  return (
    <div className="mt-2 space-y-2">
      {ids.map((id) => (
        <EdgeItem key={id} id={id} data={edges[id]} />
      ))}
    </div>
  );
}

/** Filled dots for the overlap count, out of the user's symptoms (text says the same). */
function OverlapDots({ overlap, of }: { overlap: number; of: number }) {
  if (of < 1 || of > 8) return null;
  return (
    <span className="inline-flex items-center gap-[3px]" aria-hidden>
      {Array.from({ length: of }, (_, i) => (
        <span key={i} className={cn("size-1.5 rounded-full", i < overlap ? "bg-primary" : "bg-muted-foreground/25")} />
      ))}
    </span>
  );
}

function ConditionLink({
  item,
  onMap,
  onSelect,
}: {
  item: Item;
  onMap: boolean;
  onSelect?: (id: string) => void;
}) {
  const cls =
    "min-w-0 rounded text-left text-sm font-medium underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring";
  // On the Atlas page a condition on the map is selected there; elsewhere it is handed to the
  // Atlas in memory (no id in the URL). Conditions not on the map open their node page.
  if (onMap && onSelect) {
    return (
      <button type="button" className={cls} onClick={() => onSelect(item.id)} data-testid="symptom-match-link">
        {item.label}
        <span className="sr-only"> (show on the map)</span>
      </button>
    );
  }
  if (onMap) {
    return (
      <Link href="/atlas" onClick={atlasHandoffClick({ nodeIds: [item.id], edgeIds: [] })} className={cls} data-testid="symptom-match-link">
        {item.label}
        <span className="sr-only"> (open in Atlas)</span>
      </Link>
    );
  }
  return (
    <Link href={`/node/${encodeURIComponent(item.id)}`} className={cls} data-testid="symptom-match-link">
      {item.label}
    </Link>
  );
}

function Row({
  item,
  rank,
  onMap,
  onSelect,
}: {
  item: Item;
  rank: number;
  onMap: boolean;
  onSelect?: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const disease = nodeTypeMeta("disease");
  const symptom = nodeTypeMeta("phenotype");
  const shared = item.shared.filter((t, i, all) => all.findIndex((x) => x.recorded_as === t.recorded_as) === i);
  const absent = [...new Set(item.absent.map((t) => t.recorded_as))];
  const edgeIds = [...new Set([...item.shared, ...item.absent].map((t) => t.edge_id))];
  return (
    <li className="rounded-lg border bg-background/50 px-2.5 py-2" data-testid="symptom-match-item" data-node-id={item.id} data-on-map={onMap ? "true" : "false"}>
      <div className="flex items-start gap-1.5">
        <span className="mt-px w-4 shrink-0 text-right font-mono text-xs text-muted-foreground tabular-nums" aria-hidden>
          {rank}
        </span>
        <disease.icon className="mt-[3px] size-3.5 shrink-0" style={{ color: `var(${disease.colorVar})` }} aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="leading-snug">
            <ConditionLink item={item} onMap={onMap} onSelect={onSelect} />
            {!onMap && <OffMapMark className="ml-1.5 align-[1px]" />}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-1">
            <span className="mr-0.5 inline-flex items-center gap-1.5 text-xs text-muted-foreground" data-testid="symptom-match-overlap">
              <OverlapDots overlap={item.overlap} of={item.of} />
              {item.of === 1 ? "Your symptom:" : `${item.overlap} of your ${item.of} symptoms:`}
            </span>
            <ul role="list" className="contents" aria-label="Shared symptoms">
            {shared.map((t) => {
              const hint = MATCH_HINT[t.match];
              return (
                <li
                  key={t.edge_id}
                  className="inline-flex max-w-full items-center gap-1 rounded-full border bg-card px-2 text-[11.5px] leading-5"
                  title={hint ? `Recorded as a ${hint} than your “${t.user_symptom}”` : undefined}
                  data-testid="symptom-match-shared"
                >
                  <span className="size-1.5 shrink-0 rounded-full" style={{ background: `var(${symptom.colorVar})` }} aria-hidden />
                  <span className="truncate">{t.recorded_as}</span>
                  {hint && <span className="text-muted-foreground">· {hint}</span>}
                </li>
              );
            })}
            </ul>
            <button
              type="button"
              aria-expanded={open}
              onClick={() => setOpen((o) => !o)}
              className="inline-flex h-5 items-center gap-0.5 rounded-md px-1 text-xs font-medium text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
            >
              <ChevronDown className={cn("size-3.5 transition-transform motion-reduce:transition-none", open && "rotate-180")} aria-hidden />
              {open ? "Hide sources" : `Sources · ${edgeIds.length} link${edgeIds.length === 1 ? "" : "s"}`}
            </button>
          </div>
          {absent.length > 0 && (
            <p className="mt-1 text-xs text-muted-foreground" data-testid="symptom-match-absent">
              Recorded, but you said no: <span className="text-foreground">{absent.join(", ")}</span>
            </p>
          )}
          {open && <Sources ids={edgeIds} />}
        </div>
      </div>
    </li>
  );
}

/**
 * Dr. Wu's symptom-overlap ranking (`reply.symptom_match`, built by the server from
 * match_phenotypes): conditions in the atlas whose recorded symptoms overlap the user's, best
 * first, each with its overlap count and shared symptoms, every one backed by a cited
 * has_phenotype link. An overlap count only: no score, percentage or probability, never a
 * diagnosis.
 */
export function SymptomMatchCard({
  match,
  isOnMap,
  onSelect,
}: {
  match: SymptomMatch;
  /** The Atlas tree's answer to "is this drawn on the map?"; defaults to the server's `on_map`. */
  isOnMap?: (id: string) => boolean;
  /** On the Atlas page: select a condition on the map instead of linking to the Atlas. */
  onSelect?: (id: string) => void;
}) {
  const titleId = useId();
  if (match.items.length === 0) return null;
  return (
    <article className="rounded-xl border bg-card p-3" aria-labelledby={titleId} data-testid="card-symptom_match">
      <h3 id={titleId} className="flex items-center gap-2 text-sm font-medium">
        <ListOrdered className="size-4 text-primary" aria-hidden />
        Conditions with these symptoms
      </h3>
      <p className="mt-0.5 text-xs text-muted-foreground" data-testid="symptom-match-note">
        {SYMPTOM_MATCH_NOTE}
      </p>
      <ol className="mt-2.5 space-y-2">
        {match.items.map((item, i) => (
          <Row key={item.id} item={item} rank={i + 1} onMap={isOnMap ? isOnMap(item.id) : item.on_map} onSelect={onSelect} />
        ))}
      </ol>
    </article>
  );
}
