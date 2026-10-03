"use client";

import { Popover, PopoverContent, PopoverDescription, PopoverHeader, PopoverTitle, PopoverTrigger } from "@/components/ui/popover";
import { CONFIDENCE_LABEL, confidenceLevel, type ConfidenceLevel } from "@/lib/graph/meta";
import { TIER_WEIGHTS, type Evidence, type EvidenceTier } from "@/lib/graph/types";
import { cn } from "@/lib/utils";

const TIER_LABEL: Record<EvidenceTier, string> = {
  curated_db: "Curated database",
  peer_reviewed: "Peer-reviewed study",
  review: "Review article",
  preprint: "Preprint",
  llm_inferred: "AI-extracted (unverified)",
  patient_reported: "Patient-reported",
};

const LEVEL_CLASS: Record<ConfidenceLevel, string> = {
  high: "text-confidence-high border-confidence-high/40 bg-confidence-high/10",
  medium: "text-foreground border-confidence-medium/50 bg-confidence-medium/15",
  low: "text-confidence-low border-confidence-low/40 bg-confidence-low/10",
};

/** Three-step meter: filled bars encode the level, so colour is not the only signal. */
function Meter({ level }: { level: ConfidenceLevel }) {
  const filled = level === "high" ? 3 : level === "medium" ? 2 : 1;
  return (
    <span className="flex items-end gap-[2px]" aria-hidden>
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className={cn("w-[3px] rounded-[1px]", i < filled ? "bg-current" : "bg-current/25")}
          style={{ height: 5 + i * 2.5 }}
        />
      ))}
    </span>
  );
}

/**
 * High (≥ 0.8) · Medium (≥ 0.5) · Low. Click for the breakdown: score,
 * supporting evidence by tier and weight, contradicting evidence.
 * Pass `evidence` to show the per-tier breakdown.
 */
export function ConfidenceBadge({
  confidence,
  evidence,
  className,
  showScore = false,
}: {
  confidence: number;
  evidence?: Evidence[];
  className?: string;
  /** Show the numeric score next to the label (technical lens). */
  showScore?: boolean;
}) {
  const level = confidenceLevel(confidence);
  const supporting = evidence?.filter((e) => e.polarity === "supports") ?? [];
  const contradicting = evidence?.filter((e) => e.polarity === "contradicts") ?? [];
  const byTier = new Map<EvidenceTier, number>();
  supporting.forEach((e) => byTier.set(e.tier, (byTier.get(e.tier) ?? 0) + 1));

  return (
    <Popover>
      <PopoverTrigger
        className={cn(
          "inline-flex h-5 items-center gap-1.5 rounded-full border px-2 text-[11px] font-medium whitespace-nowrap outline-none transition-colors hover:brightness-95 focus-visible:ring-2 focus-visible:ring-ring",
          LEVEL_CLASS[level],
          className,
        )}
        aria-label={`Confidence ${CONFIDENCE_LABEL[level]} (${confidence.toFixed(2)}). Show breakdown`}
        data-testid="confidence-badge"
      >
        <Meter level={level} />
        <span>{CONFIDENCE_LABEL[level]}</span>
        {showScore && <span className="font-mono tabular opacity-70">{confidence.toFixed(2)}</span>}
      </PopoverTrigger>
      <PopoverContent className="w-80" align="start">
        <PopoverHeader>
          <PopoverTitle className="flex items-center justify-between text-sm">
            <span>Confidence: {CONFIDENCE_LABEL[level]}</span>
            <span className="font-mono text-xs tabular text-muted-foreground">{confidence.toFixed(2)} / 1</span>
          </PopoverTitle>
          <PopoverDescription className="text-xs">
            Combined from every supporting source, weighted by how strong that kind of source is,
            minus a penalty for each contradicting one. High ≥ 0.8, Medium ≥ 0.5, otherwise Low.
          </PopoverDescription>
        </PopoverHeader>
        <div className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
          <div
            className={cn(
              "h-full rounded-full",
              level === "high" ? "bg-confidence-high" : level === "medium" ? "bg-confidence-medium" : "bg-confidence-low",
            )}
            style={{ width: `${Math.round(Math.max(0, Math.min(1, confidence)) * 100)}%` }}
          />
        </div>
        {evidence && (
          <dl className="space-y-1 text-xs">
            {[...byTier.entries()]
              .sort(([a], [b]) => TIER_WEIGHTS[b] - TIER_WEIGHTS[a])
              .map(([tier, n]) => (
                <div key={tier} className="flex items-center justify-between gap-3">
                  <dt className="text-muted-foreground">{TIER_LABEL[tier]}</dt>
                  <dd className="font-mono tabular">
                    {n} × {TIER_WEIGHTS[tier].toFixed(1)}
                  </dd>
                </div>
              ))}
            {supporting.length === 0 && <p className="text-muted-foreground">No supporting sources listed.</p>}
            <div className="flex items-center justify-between gap-3 border-t pt-1">
              <dt className={cn(contradicting.length ? "text-confidence-low" : "text-muted-foreground")}>
                Contradicting sources
              </dt>
              <dd className="font-mono tabular">{contradicting.length}</dd>
            </div>
          </dl>
        )}
      </PopoverContent>
    </Popover>
  );
}
