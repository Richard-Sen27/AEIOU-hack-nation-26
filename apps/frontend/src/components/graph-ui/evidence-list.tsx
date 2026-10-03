import { ArrowUpRight, CircleCheck, CircleSlash } from "lucide-react";

import type { Evidence, EvidenceTier } from "@/lib/graph/types";
import { cn } from "@/lib/utils";

export const TIER_SHORT: Record<EvidenceTier, string> = {
  curated_db: "Curated DB",
  peer_reviewed: "Peer-reviewed",
  review: "Review",
  preprint: "Preprint",
  llm_inferred: "AI-extracted",
  patient_reported: "Patient-reported",
};

function formatDate(iso?: string | null) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en", { year: "numeric", month: "short", day: "numeric" });
}

function EvidenceItem({ e }: { e: Evidence }) {
  const contra = e.polarity === "contradicts";
  const Icon = contra ? CircleSlash : CircleCheck;
  const label = e.source_id ? `${e.source_type} ${e.source_id}` : e.source_type;
  return (
    <li
      className={cn(
        "relative rounded-md border bg-card px-3 py-2.5 text-sm",
        contra && "border-confidence-low/50 bg-confidence-low/5",
      )}
      data-polarity={e.polarity}
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <Icon
          className={cn("size-3.5 shrink-0", contra ? "text-confidence-low" : "text-confidence-high")}
          aria-hidden
        />
        <span className="sr-only">{contra ? "Contradicts:" : "Supports:"}</span>
        {e.url ? (
          <a
            href={e.url}
            target="_blank"
            rel="noopener noreferrer"
            referrerPolicy="no-referrer"
            className="inline-flex items-center gap-0.5 font-mono text-xs font-medium underline-offset-2 hover:underline"
          >
            {label}
            <ArrowUpRight className="size-3" aria-hidden />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        ) : (
          <span className="font-mono text-xs font-medium">{label}</span>
        )}
        <span className="rounded border px-1.5 py-px text-[10.5px] text-muted-foreground">{TIER_SHORT[e.tier] ?? e.tier}</span>
        {e.retrieved_at && (
          <span className="ml-auto text-[11px] text-muted-foreground">
            Retrieved <time dateTime={e.retrieved_at}>{formatDate(e.retrieved_at)}</time>
          </span>
        )}
      </div>
      {e.quote && (
        <blockquote className="mt-1.5 border-l-2 border-border pl-2.5 text-[13px] leading-relaxed text-muted-foreground">
          “{e.quote}”
        </blockquote>
      )}
    </li>
  );
}

/**
 * Sources for one edge or claim: source link, tier, quote, retrieved date.
 * Contradicting evidence is rendered directly next to the supporting
 * evidence it contradicts (side by side on wide screens), never hidden.
 */
export function EvidenceList({
  evidence,
  className,
  emptyText = "No sources listed for this link.",
}: {
  evidence: Evidence[];
  className?: string;
  emptyText?: string;
}) {
  const supporting = evidence.filter((e) => e.polarity !== "contradicts");
  const contradicting = evidence.filter((e) => e.polarity === "contradicts");
  if (evidence.length === 0) {
    return <p className={cn("text-sm text-muted-foreground", className)}>{emptyText}</p>;
  }
  return (
    <div
      className={cn("grid gap-3", contradicting.length > 0 && "md:grid-cols-2", className)}
      data-testid="evidence-list"
    >
      <section aria-label={`${supporting.length} supporting sources`}>
        <h4 className="mb-1.5 text-xs font-medium text-muted-foreground">
          Supporting · {supporting.length}
        </h4>
        <ul className="space-y-2">
          {supporting.map((e, i) => (
            <EvidenceItem key={e.id ?? `s${i}`} e={e} />
          ))}
        </ul>
      </section>
      {contradicting.length > 0 && (
        <section aria-label={`${contradicting.length} contradicting sources`}>
          <h4 className="mb-1.5 text-xs font-medium text-confidence-low">
            Contradicting · {contradicting.length}
          </h4>
          <ul className="space-y-2">
            {contradicting.map((e, i) => (
              <EvidenceItem key={e.id ?? `c${i}`} e={e} />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
