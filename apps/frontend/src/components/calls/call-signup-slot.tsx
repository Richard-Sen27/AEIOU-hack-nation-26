"use client";

import { ArrowUpRight } from "lucide-react";

import { useSession } from "@/components/providers/session-provider";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { Call } from "./call-meta";

/**
 * The place on a call's page where taking part starts. Connect stage 4 adds
 * the sign-up action here (and only here). It is never offered on calls for
 * adults (`adults_only`) or to doctors and researchers. Until then the slot
 * shows the study's own link, if it has one.
 */
export function CallSignupSlot({ call }: { call: Call }) {
  const { user } = useSession();
  const expert = user?.role === "doctor" || user?.role === "researcher";
  if (expert) return null;
  if (!call.adults_only && !call.external_url) return null;
  return (
    <section aria-label="Take part" className="flex flex-wrap items-center gap-3 border-t pt-5" data-testid="call-signup-slot">
      {call.adults_only && (
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
    </section>
  );
}
