import { TriangleAlert } from "lucide-react";

import { cn } from "@/lib/utils";

/** Exact wording from the spec; do not paraphrase. */
export const VUS_SENTENCE =
  "This result is uncertain. Discuss it with a genetic counselor before acting on it.";

/** Shown wherever a variant of uncertain significance (VUS) appears. */
export function VusNotice({ className, compact = false }: { className?: string; compact?: boolean }) {
  return (
    <div
      role="note"
      data-testid="vus-notice"
      className={cn(
        "flex items-start gap-2 rounded-md border border-status-flag/60 bg-status-flag/10 text-foreground",
        compact ? "px-2 py-1 text-xs" : "px-3 py-2 text-sm",
        className,
      )}
    >
      <TriangleAlert className={cn("shrink-0 text-status-flag", compact ? "mt-[1px] size-3.5" : "mt-0.5 size-4")} aria-hidden />
      <p>
        <span className="font-semibold">Variant of uncertain significance. </span>
        {VUS_SENTENCE}
      </p>
    </div>
  );
}
