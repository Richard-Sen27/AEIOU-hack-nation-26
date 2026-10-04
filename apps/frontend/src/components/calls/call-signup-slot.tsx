"use client";

import { ArrowUpRight, Check, UserPlus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Busy, useConnectFlow } from "@/components/messages/connect-flow";
import { useSession } from "@/components/providers/session-provider";
import { Button, buttonVariants } from "@/components/ui/button";
import { getSignupOptions } from "@/lib/api";
import { cn } from "@/lib/utils";

import type { Call } from "./call-meta";
import { SignupDialog } from "./signup-dialog";
import { signupErrorText, SIGNUPS_HREF, type SignupOptions } from "./signup-meta";

/** What to say instead of the button, per reason (the backend's label wins). */
function blockedText(o: SignupOptions): string | null {
  const a = o.availability;
  if (a.label) return a.label;
  switch (a.blocked_by) {
    case "already_signed_up":
      return "You signed up.";
    case "declined":
      return "The study team declined your sign-up.";
    default:
      return null;
  }
}

/**
 * The place on a call's page where taking part starts: the sign-up action
 * where the backend offers it (`availability.can_sign_up`), otherwise the
 * backend's label (for adults, already signed up, …), and the study's own
 * link. Nothing for doctors and researchers. The connect consent and the age
 * group are asked just in time when the user starts.
 */
export function CallSignupSlot({ call }: { call: Call }) {
  const { user } = useSession();
  const expert = user?.role === "doctor" || user?.role === "researcher";
  const patient = user?.role === "patient";
  const flow = useConnectFlow();
  const [options, setOptions] = useState<SignupOptions | null>(null);
  const [open, setOpen] = useState<SignupOptions | null>(null);
  const [busy, setBusy] = useState(false);

  const fetchOptions = useCallback(async () => {
    const { data } = await getSignupOptions({ path: { call_id: call.id }, meta: { quiet: true }, cache: "no-store" });
    if (data) setOptions(data);
    return data ?? null;
  }, [call.id]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch, state set after await
    if (patient) void fetchOptions();
  }, [patient, fetchOptions]);

  // Consent (of the current text) and age group, then fresh options.
  const prepare = useCallback(
    async (force: boolean) => {
      const s = await flow.ensure(force, { current: true });
      if (!s) return null;
      return fetchOptions();
    },
    [flow, fetchOptions],
  );

  async function start() {
    setBusy(true);
    const next = await prepare(false);
    setBusy(false);
    if (!next) return;
    if (!next.availability.can_sign_up) {
      toast(blockedText(next) ?? signupErrorText(null));
      return;
    }
    setOpen(next);
  }

  if (expert) return null;
  const avail = options?.availability;
  const blocked = options && !avail?.can_sign_up ? blockedText(options) : null;
  const forAdults = avail?.blocked_by === "for_adults";
  const signedUp = avail?.blocked_by === "already_signed_up";
  if (!avail?.can_sign_up && !blocked && !call.adults_only && !call.external_url) return null;
  return (
    <section aria-label="Take part" className="flex flex-wrap items-center gap-3 border-t pt-5" data-testid="call-signup-slot">
      {avail?.can_sign_up && (
        <Button onClick={() => void start()} disabled={busy} data-testid="signup-start">
          {busy ? <Busy on /> : <UserPlus data-icon="inline-start" aria-hidden />}
          Sign up
        </Button>
      )}
      {blocked && (
        <p className="flex items-center gap-1.5 text-sm text-muted-foreground" data-testid="signup-blocked" data-reason={avail?.blocked_by ?? undefined}>
          {signedUp && <Check className="size-4 text-primary" aria-hidden />}
          {blocked}
          {(signedUp || avail?.blocked_by === "declined") && (
            <Link href={SIGNUPS_HREF} className="font-medium text-foreground underline underline-offset-2" data-testid="signup-mine-link">
              My sign-ups
            </Link>
          )}
        </p>
      )}
      {call.adults_only && !forAdults && (
        <p className="text-sm text-muted-foreground" data-testid="call-adults-only">
          For adults (18 or older).
        </p>
      )}
      {call.external_url && (
        <a
          href={call.external_url}
          target="_blank"
          rel="noopener noreferrer"
          referrerPolicy="no-referrer"
          className={cn(buttonVariants({ variant: "outline" }))}
          data-testid="call-external-link"
        >
          The study team&apos;s page <ArrowUpRight data-icon="inline-end" aria-hidden />
          <span className="sr-only">(opens in a new tab)</span>
        </a>
      )}
      {flow.dialog}
      {open && (
        <SignupDialog
          options={open}
          verification={call.publisher?.verification}
          onClose={() => setOpen(null)}
          onSent={() => void fetchOptions()}
          renew={() => prepare(true)}
        />
      )}
    </section>
  );
}
