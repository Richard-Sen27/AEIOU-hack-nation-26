"use client";

import { CircleHelp, CircleSlash, Lightbulb } from "lucide-react";
import { useMemo } from "react";

import { riseClass, riseStyle } from "@/components/ui/smooth-reveal";
import { CONFIDENCE_LABEL, ORIGIN_META } from "@/lib/graph/meta";
import { cn } from "@/lib/utils";

import { useEdges } from "./graph-data";
import { SourcesToggle } from "./sources";
import type { Claim, PartialReply } from "./types";

const LEVEL_CLASS = {
  high: "text-confidence-high border-confidence-high/40 bg-confidence-high/10",
  medium: "text-foreground border-confidence-medium/50 bg-confidence-medium/15",
  low: "text-confidence-low border-confidence-low/40 bg-confidence-low/10",
} as const;

/** The claim-level confidence (the contract gives a level, not a score). */
export function LevelBadge({ level }: { level: Claim["confidence"] }) {
  const filled = level === "high" ? 3 : level === "medium" ? 2 : 1;
  return (
    <span
      className={cn("inline-flex h-5 items-center gap-1.5 rounded-full border px-2 text-[11px] font-medium whitespace-nowrap", LEVEL_CLASS[level])}
      data-testid="claim-confidence"
    >
      <span className="flex items-end gap-[2px]" aria-hidden>
        {[0, 1, 2].map((i) => (
          <span key={i} className={cn("w-[3px] rounded-[1px]", i < filled ? "bg-current" : "bg-current/25")} style={{ height: 5 + i * 2.5 }} />
        ))}
      </span>
      <span>
        <span className="sr-only">Confidence </span>
        {CONFIDENCE_LABEL[level]}
      </span>
    </span>
  );
}

const HYPOTHESIS_FALLBACK = "Worked out from the data, not confirmed by a study.";

/**
 * A computed hypothesis stays visibly marked, with its one-line reason (the cited link's
 * explanation); patient-reported and user-added statements say so in plain words.
 */
function OriginNote({ claim }: { claim: Claim }) {
  const edges = useEdges(claim.origin === "inferred" ? claim.edge_ids : []);
  if (claim.origin === "observed") return null;
  if (claim.origin !== "inferred") {
    return (
      <p className="mt-1 text-xs text-muted-foreground" data-testid="claim-origin">
        <span className="font-medium text-status-flag">{ORIGIN_META[claim.origin]?.label.plain}</span> ·{" "}
        {ORIGIN_META[claim.origin]?.description}
      </p>
    );
  }
  const reason = claim.edge_ids.map((id) => edges[id]?.edge.explanation).find(Boolean);
  return (
    <p className="mt-1 flex items-start gap-1.5 text-xs text-muted-foreground" data-testid="claim-hypothesis">
      <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-dashed border-foreground/40 px-1.5 leading-4 font-medium text-foreground">
        <Lightbulb className="size-3" aria-hidden /> Hypothesis
      </span>
      <span dir="auto">{reason ?? HYPOTHESIS_FALLBACK}</span>
    </p>
  );
}

function ClaimItem({
  claim,
  index,
  contradictions,
  compact,
  rise,
}: {
  claim: Claim;
  index: number;
  contradictions: PartialReply["contradictions"];
  compact?: boolean;
  rise?: number;
}) {
  const weak = claim.confidence === "low";
  const animate = rise !== undefined;
  return (
    <li className={cn("flex items-start gap-2", riseClass(animate))} style={riseStyle(animate, rise ?? 0)} data-testid="claim" data-origin={claim.origin}>
      <span className="mt-[3px] w-4 shrink-0 text-right font-mono text-[11px] text-muted-foreground tabular-nums" aria-hidden>
        {index + 1}
      </span>
      <div className="min-w-0 flex-1">
        <p dir="auto" className={cn("leading-relaxed", compact ? "text-[13px]" : "text-[15px]")}>
          {claim.text}
          {weak && (
            <span className="ml-1.5 inline-flex rounded-full border border-confidence-low/40 px-1.5 align-[1px] text-[11px] leading-4 text-confidence-low" data-testid="claim-confidence">
              Weak evidence
            </span>
          )}
        </p>
        <OriginNote claim={claim} />
        {contradictions.map((c, ci) => (
          <p key={ci} className="mt-1 flex items-start gap-1.5 text-xs" data-testid="contradiction">
            <CircleSlash className="mt-px size-3.5 shrink-0 text-confidence-low" aria-hidden />
            <span dir="auto">
              <span className="font-medium text-confidence-low">Some sources disagree: </span>
              {c.note}
            </span>
          </p>
        ))}
      </div>
    </li>
  );
}

/** How many entrance steps `Claims` takes for this reply (its heading, each statement, the sources line, the gaps). */
export function claimSteps(reply: PartialReply, compact = false): number {
  const claims = reply.claims.length ? reply.claims.length + 2 : 0;
  return claims + (reply.missing_evidence.length && !compact ? 1 : 0);
}

/**
 * The cited statements in plain words, numbered: hypotheses marked with their reason,
 * contradictions right under their statement. Their sources sit behind one short
 * "Sources · N" line, collapsed by default; every statement keeps its sources there.
 * Missing evidence is listed as what is not known.
 */
export function Claims({ reply, compact = false, rise }: { reply: PartialReply; compact?: boolean; rise?: number }) {
  const groups = useMemo(
    () =>
      reply.claims.map((c, i) => ({
        ref: i + 1,
        edgeIds: [...new Set([...c.edge_ids, ...reply.contradictions.filter((x) => x.claim_index === i).flatMap((x) => x.edge_ids)])],
      })),
    [reply.claims, reply.contradictions],
  );
  if (reply.claims.length === 0 && reply.missing_evidence.length === 0) return null;
  // In a live reply each part comes in one step after the other, from step `rise` on.
  const animate = rise !== undefined;
  const at = (i: number) => riseStyle(animate, (rise ?? 0) + i);
  const n = reply.claims.length;
  return (
    <section aria-label="What the sources say" className={compact ? "space-y-2" : "space-y-3"} data-testid="claims">
      {reply.claims.length > 0 && (
        <div>
          <h3 className={cn("mb-1.5 text-xs font-medium text-muted-foreground", riseClass(animate))} style={at(0)}>
            What the sources say
          </h3>
          <ol className="space-y-1.5">
            {reply.claims.map((claim, i) => (
              <ClaimItem
                key={i}
                claim={claim}
                index={i}
                compact={compact}
                rise={animate ? (rise ?? 0) + 1 + i : undefined}
                contradictions={reply.contradictions.filter((c) => c.claim_index === i)}
              />
            ))}
          </ol>
          <div className={cn("mt-1 -ml-1.5", riseClass(animate))} style={at(n + 1)}>
            <SourcesToggle groups={groups} />
          </div>
        </div>
      )}
      {reply.missing_evidence.length > 0 && !compact && (
        <div className={cn("rounded-lg border border-dashed px-3.5 py-3", riseClass(animate))} style={at(n ? n + 2 : 0)} data-testid="missing-evidence">
          <h3 className="text-sm font-medium">What is not known yet</h3>
          <ul className="mt-1.5 space-y-1">
            {reply.missing_evidence.map((m, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-muted-foreground">
                <CircleHelp className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                <span dir="auto">{m}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
