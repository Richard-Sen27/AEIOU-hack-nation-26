"use client";

import { useEffect, useState } from "react";

import { PRIVACY_EMAIL } from "@/lib/api/config";
import { isDaily, limitMessage, remaining, type LimitInfo } from "@/lib/api/limits";
import { cn } from "@/lib/utils";

/**
 * The limit message (lib/api/limits), re-rendered every second while a short
 * wait counts down, so "Try again in 40 seconds" stays true.
 */
export function useLimitMessage(info: LimitInfo | undefined, subject: string): string {
  const [now, setNow] = useState(() => Date.now());
  const counting = !!info && !isDaily(info) && info.reason !== "busy" && (remaining(info, now) ?? 0) > 0;
  useEffect(() => {
    if (!counting) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [counting]);
  return limitMessage(info, subject, now);
}

/** The limit message as text, counting down. */
export function LimitText({ info, subject }: { info: LimitInfo | undefined; subject: string }) {
  return <>{useLimitMessage(info, subject)}</>;
}

/**
 * "Need more? Write to <address>." under a daily limit, when the operator set
 * NEXT_PUBLIC_PRIVACY_EMAIL (Amber's only public contact); otherwise nothing.
 */
export function LimitContact({ info, className }: { info: LimitInfo | undefined; className?: string }) {
  if (!PRIVACY_EMAIL || !isDaily(info)) return null;
  return (
    <span className={cn("block text-xs text-muted-foreground", className)} data-testid="limit-contact">
      Need more? Write to{" "}
      <a href={`mailto:${PRIVACY_EMAIL}`} className="break-all font-medium text-foreground underline underline-offset-2">
        {PRIVACY_EMAIL}
      </a>
      .
    </span>
  );
}
