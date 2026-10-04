"use client";

import { BadgeCheck, FlaskConical } from "lucide-react";
import Link from "next/link";

import { cn } from "@/lib/utils";

import { cardHref } from "./public-card";
import { usePersonCard } from "./use-people";
import { shortVerification } from "./verification-label";

/**
 * "In Amber" on a researcher or doctor who has a visible, verified card. The
 * summary carries only the card id; the verification words come from the card
 * itself, so a simulated (demo) verification is marked here too.
 */
export function InAmberChip({ cardId, name, className }: { cardId: string; name: string; className?: string }) {
  const card = usePersonCard(cardId);
  const v = card.kind === "ready" ? card.data.verification : null;
  // A card that is gone (switched off since the summary was built) gets no chip.
  if (card.kind === "error") return null;
  const Icon = v?.simulated ? FlaskConical : BadgeCheck;
  return (
    <Link
      href={cardHref(cardId)}
      className={cn(
        "inline-flex h-5 max-w-full items-center gap-1 rounded-full border px-1.5 text-[11px] font-medium outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring",
        v?.simulated ? "border-status-flag/50 text-status-flag" : "border-primary/40 text-foreground",
        className,
      )}
      title={v?.label}
      data-testid="in-amber-chip"
      data-simulated={v?.simulated || undefined}
    >
      <Icon className={cn("size-3 shrink-0", !v?.simulated && "text-confidence-high")} aria-hidden />
      <span className="truncate">
        In Amber{v && <> · {shortVerification(v)}</>}
      </span>
      <span className="sr-only">: open the card of {name}</span>
    </Link>
  );
}
