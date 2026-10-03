"use client";

import { ChevronDown, CircleHelp, CircleSlash } from "lucide-react";
import { useState } from "react";

import { OriginBadge } from "@/components/graph-ui";
import { CONFIDENCE_LABEL, ORIGIN_META } from "@/lib/graph/meta";
import { cn } from "@/lib/utils";

import { EdgeItem } from "./edge-item";
import { useEdges } from "./graph-data";
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

function EdgeList({ ids, tone }: { ids: string[]; tone?: "contradiction" }) {
  const edges = useEdges(ids);
  return (
    <div className="space-y-2">
      {ids.map((id) => (
        <EdgeItem key={id} id={id} data={edges[id]} tone={tone} defaultOpen={tone === "contradiction"} />
      ))}
    </div>
  );
}

function ClaimItem({
  claim,
  index,
  contradictions,
}: {
  claim: Claim;
  index: number;
  contradictions: PartialReply["contradictions"];
}) {
  const [open, setOpen] = useState(false);
  const [contraOpen, setContraOpen] = useState(false);
  const line = ORIGIN_META[claim.origin]?.line ?? "solid";
  return (
    <li
      className={cn(
        "rounded-lg border-l-[3px] bg-card/60 py-2.5 pr-3 pl-3.5",
        line === "solid" && "border-solid border-l-foreground/40",
        line === "dashed" && "border-dashed border-l-foreground/40",
        line === "dotted" && "border-dotted border-l-status-flag",
      )}
      data-testid="claim"
      data-origin={claim.origin}
    >
      <p dir="auto" className="text-[15px] leading-relaxed">
        {claim.text}
      </p>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        <OriginBadge origin={claim.origin} />
        <LevelBadge level={claim.confidence} />
        {claim.edge_ids.length > 0 && (
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
            className="inline-flex h-6 items-center gap-1 rounded-md px-1.5 text-xs font-medium text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ChevronDown className={cn("size-3.5 transition-transform motion-reduce:transition-none", open && "rotate-180")} aria-hidden />
            {open ? "Hide evidence" : `Evidence · ${claim.edge_ids.length} link${claim.edge_ids.length === 1 ? "" : "s"}`}
          </button>
        )}
      </div>

      {contradictions.map((c, ci) => (
        <div
          key={ci}
          className="mt-2.5 rounded-md border border-confidence-low/50 bg-confidence-low/5 px-3 py-2"
          data-testid="contradiction"
        >
          <p className="flex items-start gap-2 text-sm">
            <CircleSlash className="mt-0.5 size-4 shrink-0 text-confidence-low" aria-hidden />
            <span dir="auto">
              <span className="font-medium">Contradicting evidence: </span>
              {c.note}
            </span>
          </p>
          {c.edge_ids.length > 0 && (
            <>
              <button
                type="button"
                aria-expanded={contraOpen}
                onClick={() => setContraOpen((o) => !o)}
                className="mt-1 ml-6 inline-flex items-center gap-1 rounded text-xs font-medium text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
              >
                <ChevronDown className={cn("size-3.5 transition-transform motion-reduce:transition-none", contraOpen && "rotate-180")} aria-hidden />
                {contraOpen ? "Hide contradicting sources" : "Show contradicting sources"}
              </button>
              {contraOpen && (
                <div className="mt-2">
                  <EdgeList ids={c.edge_ids} tone="contradiction" />
                </div>
              )}
            </>
          )}
        </div>
      ))}

      {open && (
        <div className="mt-2.5" data-testid={`claim-${index}-evidence`}>
          <EdgeList ids={claim.edge_ids} />
        </div>
      )}
    </li>
  );
}

/**
 * Claims with origin (data vs hypothesis), confidence and cited edges.
 * Contradictions sit directly under the claim they contradict; missing
 * evidence is listed as what is not known.
 */
export function Claims({ reply }: { reply: PartialReply }) {
  if (reply.claims.length === 0 && reply.missing_evidence.length === 0) return null;
  return (
    <section aria-label="What the evidence says" className="space-y-3">
      {reply.claims.length > 0 && (
        <>
          <h3 className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-muted-foreground">What the evidence says</h3>
          <ol className="space-y-2">
            {reply.claims.map((claim, i) => (
              <ClaimItem
                key={i}
                claim={claim}
                index={i}
                contradictions={reply.contradictions.filter((c) => c.claim_index === i)}
              />
            ))}
          </ol>
        </>
      )}
      {reply.missing_evidence.length > 0 && (
        <div className="rounded-lg border border-dashed px-3.5 py-3" data-testid="missing-evidence">
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
