"use client";

import { Check } from "lucide-react";

import { useLens } from "@/components/providers/lens-provider";
import { EDGE_FAMILY_META } from "@/lib/graph/meta";
import type { EdgeFamily } from "@/lib/graph/types";
import { cn } from "@/lib/utils";

/**
 * Toggle chips for the four connection families, each with its count.
 * Colour is paired with a line sample, a name and a check mark.
 */
export function FamilyChips({
  families,
  counts,
  active,
  onToggle,
  highlighted,
  className,
}: {
  families: EdgeFamily[];
  counts: Partial<Record<EdgeFamily, number>>;
  active: Set<EdgeFamily>;
  onToggle: (f: EdgeFamily) => void;
  /** Families the lens highlights first (shown with a ring). */
  highlighted?: EdgeFamily[];
  className?: string;
}) {
  const { labelStyle } = useLens();
  return (
    <div role="group" aria-label="Show connections by kind" className={cn("flex flex-wrap gap-1.5", className)}>
      {families.map((f) => {
        const meta = EDGE_FAMILY_META[f];
        const on = active.has(f);
        const n = counts[f] ?? 0;
        return (
          <button
            key={f}
            type="button"
            aria-pressed={on}
            onClick={() => onToggle(f)}
            title={meta.description[labelStyle]}
            data-testid={`family-chip-${f}`}
            className={cn(
              "inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring",
              on ? "bg-card text-foreground" : "bg-transparent text-muted-foreground line-through decoration-muted-foreground/50",
              on && highlighted?.includes(f) && "border-foreground/40 ring-1 ring-primary/40",
            )}
          >
            <span
              className={cn("flex size-3.5 items-center justify-center rounded-[4px] border", on ? "border-transparent" : "border-muted-foreground/50")}
              style={on ? { background: `var(${meta.colorVar})` } : undefined}
              aria-hidden
            >
              {on && <Check className="size-2.5 text-background" strokeWidth={3} />}
            </span>
            {meta.label[labelStyle]}
            <span className="font-mono text-[10.5px] tabular text-muted-foreground">{n}</span>
          </button>
        );
      })}
    </div>
  );
}
