import { Flag, Hourglass } from "lucide-react";

import type { EdgeStatus } from "@/lib/graph/types";
import { cn } from "@/lib/utils";

const COPY: Record<Exclude<EdgeStatus, "active">, { label: string; description: string }> = {
  pending_review: {
    label: "Pending review",
    description: "Not yet checked by a person. Not used as support for any action.",
  },
  under_review: {
    label: "Under review",
    description: "Someone flagged this link. It is being re-checked and not used as support.",
  },
};

/** Visible flag for non-active edges and claims. Renders nothing for `active`. */
export function StatusFlag({
  status,
  className,
  withDescription = false,
}: {
  status: EdgeStatus;
  className?: string;
  withDescription?: boolean;
}) {
  if (status === "active") return null;
  const copy = COPY[status];
  const Icon = status === "under_review" ? Flag : Hourglass;
  return (
    <span
      role="status"
      className={cn(
        "inline-flex items-start gap-1.5 rounded-md border border-status-flag/60 bg-status-flag/10 px-2 py-0.5 text-[11px] font-medium text-foreground",
        className,
      )}
      data-testid="status-flag"
      data-status={status}
    >
      <Icon className="mt-[1px] size-3 shrink-0 text-status-flag" aria-hidden />
      <span>
        {copy.label}
        {withDescription && <span className="block font-normal text-muted-foreground">{copy.description}</span>}
      </span>
    </span>
  );
}
