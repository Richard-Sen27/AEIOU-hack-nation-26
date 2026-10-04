import { BadgeCheck, ChevronRight } from "lucide-react";
import Link from "next/link";

import type { Schemas } from "@/lib/api";
import { cn } from "@/lib/utils";

import { personHref } from "./call-meta";

const ROLE = { doctor: "Doctor", researcher: "Researcher" } as Record<string, string>;

/** The publisher's public card in one block, linking to their card page. */
export function PublisherLine({ card, className }: { card: Schemas.PublicCard; className?: string }) {
  const institutions = (card.institutions ?? []).map((i) => i.label).join(" · ");
  return (
    <Link
      href={personHref(card.card_id)}
      className={cn("group flex items-center gap-3 rounded-lg border bg-background/60 px-3 py-2.5 transition-colors hover:bg-muted", className)}
      data-testid="call-publisher"
    >
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{card.name}</span>
        <span className="block truncate text-xs text-muted-foreground">
          {ROLE[card.role] ?? card.role} (self-declared)
          {institutions && ` · ${institutions}`}
        </span>
        <span className="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground">
          <BadgeCheck className="size-3.5 shrink-0 text-primary" aria-hidden />
          <span className="truncate">{card.verification.label}</span>
        </span>
      </span>
      <ChevronRight className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" aria-hidden />
    </Link>
  );
}
