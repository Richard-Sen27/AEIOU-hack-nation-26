import { ExternalLink, MessageSquare } from "lucide-react";
import Link from "next/link";

import type { Schemas } from "@/lib/api";
import { nodeTypeMeta } from "@/lib/graph/meta";
import { cn } from "@/lib/utils";

import { VerificationLabel } from "./verification-label";

export type PublicCard = Schemas.PublicCard;

const ROLE_LABEL: Record<string, string> = { doctor: "Doctor", researcher: "Researcher" };
const INSTITUTION = nodeTypeMeta("institution");

export const cardHref = (cardId: string) => `/people/${encodeURIComponent(cardId)}`;

/**
 * A doctor's or researcher's public card, exactly as other signed-in users see
 * it: only what the person switched on, verification worded by the backend.
 * The same component renders the owner's preview, so the two cannot drift.
 *
 * Later stages plug in without changing this file's layout: `actions` (the
 * "Message" button, only when `accepts_patient_messages`) and `children` (the
 * expert's published calls).
 */
export function PublicCardView({
  card,
  heading: Heading = "h2",
  actions,
  children,
  className,
}: {
  card: PublicCard;
  heading?: "h1" | "h2" | "h3" | "h4";
  /** Slot for actions such as "Message" (stage 5). */
  actions?: React.ReactNode;
  /** Slot below the card body, e.g. the expert's published calls (stage 3). */
  children?: React.ReactNode;
  className?: string;
}) {
  const meta = nodeTypeMeta(card.role);
  const Icon = meta.icon;
  return (
    <article
      className={cn("space-y-4 rounded-xl border bg-card p-4 sm:p-5", className)}
      data-testid="public-card"
      data-card-id={card.card_id}
    >
      <header className="flex items-start gap-3">
        <span
          className="flex size-10 shrink-0 items-center justify-center rounded-lg border bg-background"
          style={{ color: `var(${meta.colorVar})` }}
        >
          <Icon className="size-5" aria-hidden />
        </span>
        <div className="min-w-0 flex-1 space-y-0.5">
          <Heading className="text-lg leading-tight font-semibold tracking-tight text-balance" data-testid="card-name">
            {card.name}
          </Heading>
          <p className="text-sm text-muted-foreground" data-testid="card-role">
            {ROLE_LABEL[card.role] ?? card.role} <span className="text-xs">(self-declared)</span>
            {card.name_source === "self_declared" && <span className="text-xs"> · name self-declared</span>}
          </p>
          <VerificationLabel verification={card.verification} className="pt-1" />
        </div>
        {actions && (
          <div className="flex shrink-0 items-center gap-2" data-slot="card-actions">
            {actions}
          </div>
        )}
      </header>

      {card.headline && (
        <p className="text-[15px] leading-relaxed text-pretty" data-testid="card-headline">
          {card.headline}
        </p>
      )}

      {(card.institutions?.length ?? 0) > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="Institutions (self-declared)" data-testid="card-institutions">
          {card.institutions!.map((inst) => {
            const body = (
              <>
                <INSTITUTION.icon className="size-3.5 shrink-0" style={{ color: `var(${INSTITUTION.colorVar})` }} aria-hidden />
                <span className="truncate">{inst.label}</span>
              </>
            );
            const chip = "flex max-w-full items-center gap-1.5 rounded-lg border bg-background px-2 py-1 text-sm";
            return (
              <li key={`${inst.node_id ?? "text"}-${inst.label}`} className="max-w-full">
                {inst.node_id ? (
                  <Link href={`/node/${encodeURIComponent(inst.node_id)}`} className={cn(chip, "hover:bg-muted")}>
                    {body}
                  </Link>
                ) : (
                  <span className={chip}>{body}</span>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {(card.atlas_node_id || card.orcid_url || card.accepts_patient_messages) && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm">
          {card.atlas_node_id && (
            <Link
              href={`/node/${encodeURIComponent(card.atlas_node_id)}`}
              className="font-medium underline underline-offset-2"
              data-testid="card-atlas-link"
            >
              {card.atlas_node_label ? `${card.atlas_node_label} in the atlas` : "Entry in the atlas"}
            </Link>
          )}
          {card.orcid_url && card.orcid_id && (
            <a
              href={card.orcid_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 underline underline-offset-2"
              data-testid="card-orcid-link"
            >
              ORCID <span className="font-mono text-xs">{card.orcid_id}</span>
              <ExternalLink className="size-3" aria-hidden />
              <span className="sr-only">(opens in a new tab)</span>
            </a>
          )}
          {card.accepts_patient_messages && (
            <span className="inline-flex items-center gap-1 text-muted-foreground" data-testid="card-accepts-messages">
              <MessageSquare className="size-3.5" aria-hidden />
              Accepts messages from patients
            </span>
          )}
        </div>
      )}

      {children && <div data-slot="card-calls">{children}</div>}
    </article>
  );
}
