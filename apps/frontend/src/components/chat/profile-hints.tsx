"use client";

import { Baby, Check, CircleCheck, X } from "lucide-react";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

import type { HintDecision, HintKey, Schemas } from "./types";

const iconBtn =
  "flex size-6 items-center justify-center rounded-full outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50";

function hintItems(h: Schemas.ProfileHints): { key: HintKey; label: string }[] {
  const items: { key: HintKey; label: string }[] = [];
  if (h.age_years != null) items.push({ key: "age", label: `Age ${h.age_years}` });
  else if (h.age_range) items.push({ key: "age", label: `Age ${h.age_range}` });
  if (h.onset) items.push({ key: "onset", label: `Onset: ${h.onset}` });
  if (h.country) items.push({ key: "country", label: `Country: ${h.country}` });
  return items;
}

/**
 * Age, onset and country Dr. Wu picked up from the message, shown like chips:
 * nothing counts until the user confirms it into the profile (system spec,
 * chat orchestrator: "age, onset and country", confirmed by the user).
 */
export function ProfileHints({
  hints,
  state,
  onConfirm,
  onDismiss,
}: {
  hints: Schemas.ProfileHints | null | undefined;
  state?: Partial<Record<HintKey, HintDecision>>;
  onConfirm: (key: HintKey) => void;
  onDismiss: (key: HintKey) => void;
}) {
  const items = hints ? hintItems(hints).filter((i) => state?.[i.key] !== "dismissed") : [];
  if (!items.length) return null;
  return (
    <ul className="flex flex-wrap gap-1.5" aria-label="Details for your profile" data-testid="profile-hints">
      {items.map(({ key, label }) => {
        const decision = state?.[key];
        const confirmed = decision === "confirmed";
        return (
          <li
            key={key}
            className={cn(
              "inline-flex h-8 max-w-full items-center gap-1.5 rounded-full border bg-card pr-1 pl-3 text-[13px]",
              confirmed && "border-confidence-high/50 bg-confidence-high/10",
            )}
            data-testid="profile-hint"
            data-key={key}
            data-state={confirmed ? "confirmed" : "pending"}
          >
            <span className="truncate font-medium" dir="auto">
              {label}
            </span>
            {confirmed ? (
              <span className="inline-flex items-center gap-0.5 pr-2 text-[11px] font-medium text-confidence-high">
                <CircleCheck className="size-3.5" aria-hidden /> In profile
              </span>
            ) : decision === "saving" ? (
              <Spinner className="mx-1 size-3.5" />
            ) : (
              <span className="flex items-center">
                <button type="button" onClick={() => onConfirm(key)} aria-label={`Confirm ${label}`} title="Confirm" className={cn(iconBtn, "text-confidence-high hover:bg-confidence-high/15")}>
                  <Check className="size-3.5" aria-hidden />
                </button>
                <button type="button" onClick={() => onDismiss(key)} aria-label={`Dismiss ${label}`} title="Dismiss" className={cn(iconBtn, "text-muted-foreground hover:bg-destructive/10 hover:text-destructive")}>
                  <X className="size-3.5" aria-hidden />
                </button>
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * The reply suggests the conversation is about a child while the stored
 * answer says "own data": offer, once, to change it. A child's profile needs
 * the parental-responsibility confirmation (compliance.md, Children).
 */
export function ChildOffer({ onConfirm, onDismiss }: { onConfirm: () => Promise<void>; onDismiss: () => void }) {
  const id = useId();
  const [parental, setParental] = useState(false);
  const [busy, setBusy] = useState(false);
  return (
    <div className="space-y-2.5 rounded-lg border bg-muted/40 p-3 text-sm" role="group" aria-labelledby={`${id}-q`} data-testid="child-offer">
      <p id={`${id}-q`} className="flex items-start gap-2">
        <Baby className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
        <span>
          This sounds like it is about a child you care for, but your profile is set to your own information. Is it
          about a child?
        </span>
      </p>
      <label htmlFor={`${id}-parental`} className="flex items-start gap-2.5">
        <Checkbox id={`${id}-parental`} checked={parental} onCheckedChange={(v) => setParental(v === true)} className="mt-0.5" />
        <span>I confirm that I hold parental responsibility (I am the parent or legal guardian) for this child.</span>
      </label>
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          disabled={!parental || busy}
          onClick={async () => {
            setBusy(true);
            await onConfirm();
            setBusy(false);
          }}
        >
          {busy && <Spinner className="size-3.5" />} Yes, it is about a child
        </Button>
        <Button size="sm" variant="ghost" onClick={onDismiss} disabled={busy}>
          No, it is about me
        </Button>
      </div>
    </div>
  );
}
