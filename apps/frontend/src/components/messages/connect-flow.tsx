"use client";

import { Loader2 } from "lucide-react";
import { useCallback, useId, useState } from "react";
import { toast } from "sonner";

import { useGate } from "@/components/providers/gate-provider";
import { useSession } from "@/components/providers/session-provider";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { ApiError } from "@/lib/api/errors";
import { getConnectStatus, hasConsent, setConnectAgeGroup, unwrap, type Schemas } from "@/lib/api";

export type ConnectStatus = Schemas.ConnectStatus;
export type AgeGroup = Schemas.AgeGroup;

export const AGE_GROUP_LABEL: Record<AgeGroup, string> = {
  "18_plus": "18 or older",
  "16_17": "16 or 17",
};

/** The guardian checkbox text with the recipient's name filled in. */
export function guardianText(status: ConnectStatus | null, recipient: string | null | undefined) {
  const text = status?.guardian_text ?? "A parent or guardian knows about this and agrees that I share it with {recipient}.";
  return text.replace("{recipient}", recipient || "this person");
}

/**
 * Short, clear text for a messaging error. Never echoes what the user typed.
 * `kind` picks the wording for 404/409/429, which mean different things per route.
 */
export function messagingErrorText(e: unknown, kind: "open" | "send" | "respond" | "other" = "other"): string {
  const err = e instanceof ApiError ? e : null;
  switch (err?.code) {
    case "consent_required":
      return "Messages need your consent first.";
    case "age_group_required":
      return "Tell us your age group first.";
    case "guardian_agreement_required":
      return "Tick the parent or guardian box to send.";
    case "forbidden":
      return "Only patients and caregivers can start a conversation.";
    case "not_found":
      return kind === "open" ? "This person does not accept messages." : "This conversation is no longer here.";
    case "conflict":
      return kind === "open"
        ? "You already have a conversation with this person."
        : kind === "respond"
          ? "There is no request waiting here."
          : "This conversation is not open for messages.";
    case "rate_limited":
      return kind === "open" ? "You can start 5 new conversations a day. Try again tomorrow." : "Too many messages. Try again later.";
    case "not_implemented":
      return "Messaging is not available on this server yet.";
    case "validation_error":
      return "Check the name and message (up to 2,000 characters).";
    case "network_error":
      return "Amber's server is not reachable. Please try again.";
    default:
      return "Something went wrong. Please try again.";
  }
}

/** Asks for the age group once, at the first connect action. */
function AgeGroupDialog({ open, onDone }: { open: boolean; onDone: (group: AgeGroup | null) => void }) {
  const id = useId();
  const [group, setGroup] = useState<AgeGroup | null>(null);
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onDone(null)}>
      <DialogContent className="sm:max-w-sm" data-testid="age-group-dialog">
        <DialogHeader>
          <DialogTitle>Your age group</DialogTitle>
          <DialogDescription>Self-declared. You can change it in your profile.</DialogDescription>
        </DialogHeader>
        <RadioGroup value={group} onValueChange={(v) => setGroup(v as AgeGroup)} className="gap-2" aria-labelledby={`${id}-l`}>
          <span id={`${id}-l`} className="sr-only">
            Age group
          </span>
          {(Object.keys(AGE_GROUP_LABEL) as AgeGroup[]).map((g) => (
            <label key={g} className="flex items-center gap-2.5 rounded-lg border px-3 py-2.5 text-sm has-[[data-checked]]:border-primary">
              <RadioGroupItem value={g} aria-label={AGE_GROUP_LABEL[g]} />
              {AGE_GROUP_LABEL[g]}
            </label>
          ))}
        </RadioGroup>
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="outline" onClick={() => onDone(null)}>
            Not now
          </Button>
          <Button disabled={!group} onClick={() => group && onDone(group)} data-testid="age-group-continue">
            Continue
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/**
 * The connect steps every messaging action needs, just in time: the `connect`
 * consent (the app's consent dialog), then the age group. `ensure()` resolves
 * the current status, or null if the user stopped. Render `dialog` once.
 */
export function useConnectFlow() {
  const { requireConsent } = useGate();
  const { user } = useSession();
  const [status, setStatus] = useState<ConnectStatus | null>(null);
  const [asking, setAsking] = useState<((g: AgeGroup | null) => void) | null>(null);

  const load = useCallback(async () => {
    try {
      const s = await unwrap(getConnectStatus({ meta: { quiet: true }, cache: "no-store" }));
      setStatus(s);
      return s;
    } catch {
      return null;
    }
  }, []);

  const ensure = useCallback(async (force = false): Promise<ConnectStatus | null> => {
    // Already settled in this session: no extra request per message.
    if (!force && hasConsent(user, "connect") && status?.consent_active && status.age_group) return status;
    if (!(await requireConsent("connect", "Messages need an account."))) return null;
    let s = await load();
    if (!s) {
      toast("Amber's server is not reachable. Please try again.");
      return null;
    }
    if (!s.age_group) {
      const group = await new Promise<AgeGroup | null>((resolve) => setAsking(() => resolve));
      setAsking(null);
      if (!group) return null;
      try {
        s = await unwrap(setConnectAgeGroup({ body: { age_group: group }, meta: { quiet: true } }));
        setStatus(s);
      } catch (e) {
        toast(messagingErrorText(e));
        return null;
      }
    }
    return s;
  }, [requireConsent, load, user, status]);

  const dialog = <AgeGroupDialog key={asking ? "open" : "closed"} open={asking !== null} onDone={(g) => asking?.(g)} />;

  return { status, load, ensure, dialog };
}

export function Busy({ on }: { on: boolean }) {
  return on ? <Loader2 className="animate-spin" aria-hidden /> : null;
}
