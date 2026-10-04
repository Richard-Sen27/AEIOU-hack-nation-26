import { BadgeCheck, FlaskConical } from "lucide-react";

import type { Schemas } from "@/lib/api";
import { cn } from "@/lib/utils";

type Verification = Pick<Schemas.CardVerification, "method" | "label" | "simulated">;

/** Short words for a chip; the card itself always shows the backend's label. */
export function shortVerification(v: Verification): string {
  if (v.simulated) return "Demo, verification simulated";
  return v.method === "orcid" ? "ORCID iD confirmed" : "Checked by the Amber team";
}

/**
 * What was checked, worded by the backend. A simulated (local demo) verification
 * is drawn in the warning colour so it can never pass for a real one.
 */
export function VerificationLabel({
  verification,
  short = false,
  className,
}: {
  verification: Verification;
  /** Chip wording instead of the full label (the full label stays in the tooltip). */
  short?: boolean;
  className?: string;
}) {
  const Icon = verification.simulated ? FlaskConical : BadgeCheck;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-xs font-medium",
        verification.simulated ? "text-status-flag" : "text-foreground/80",
        className,
      )}
      title={short ? verification.label : undefined}
      data-testid="verification-label"
      data-simulated={verification.simulated || undefined}
    >
      <Icon className={cn("size-3.5 shrink-0", !verification.simulated && "text-confidence-high")} aria-hidden />
      {short ? shortVerification(verification) : verification.label}
    </span>
  );
}
