import { Database, Lightbulb, MessageCircleHeart, UserPen } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ORIGIN_META } from "@/lib/graph/meta";
import type { Origin } from "@/lib/graph/types";
import { cn } from "@/lib/utils";

const ICON = {
  observed: Database,
  inferred: Lightbulb,
  patient_reported: MessageCircleHeart,
  user_contributed: UserPen,
} as const;

/**
 * observed → "Data" (solid border) · inferred → "Hypothesis" (dashed) ·
 * patient_reported / user_contributed → own labels (dotted). The border style
 * matches the line style used in every graph view.
 */
export function OriginBadge({ origin, className }: { origin: Origin; className?: string }) {
  const meta = ORIGIN_META[origin] ?? ORIGIN_META.observed;
  const Icon = ICON[origin] ?? Database;
  return (
    <Tooltip>
      <TooltipTrigger
        render={<span />}
        className={cn(
          "inline-flex h-5 cursor-default items-center gap-1 rounded-full border-[1.5px] px-2 text-[11px] font-medium whitespace-nowrap",
          meta.line === "solid" && "border-solid border-foreground/50 text-foreground",
          meta.line === "dashed" && "border-dashed border-foreground/50 text-foreground",
          meta.line === "dotted" && "border-dotted border-status-flag text-foreground",
          className,
        )}
        data-testid="origin-badge"
        data-origin={origin}
      >
        <Icon className="size-3" aria-hidden />
        {meta.label.plain}
      </TooltipTrigger>
      <TooltipContent>{meta.description}</TooltipContent>
    </Tooltip>
  );
}
