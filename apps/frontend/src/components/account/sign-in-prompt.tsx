"use client";

import { LockKeyhole } from "lucide-react";

import { SignInButtons } from "@/components/gates/sign-in-buttons";
import { useSession } from "@/components/providers/session-provider";
import { Skeleton } from "@/components/ui/skeleton";

/** Shown instead of a signed-in-only page for guests (never breaks, never redirects). */
export function SignInPrompt({
  title,
  description,
  returnTo,
}: {
  title: string;
  description: string;
  returnTo?: string;
}) {
  const { status } = useSession();
  return (
    <section
      data-testid="sign-in-prompt"
      className="bg-atlas-grid flex flex-col items-start gap-4 rounded-xl border bg-card/60 p-6 sm:p-8"
    >
      <span className="flex size-10 items-center justify-center rounded-lg bg-accent text-accent-foreground">
        <LockKeyhole className="size-5" aria-hidden />
      </span>
      <div className="max-w-xl space-y-1.5">
        <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
        <p className="text-sm leading-relaxed text-muted-foreground">{description}</p>
      </div>
      {status === "offline" ? (
        <p className="text-sm text-muted-foreground">
          Amber&apos;s server can&apos;t be reached, so sign-in is unavailable for now.
        </p>
      ) : (
        <SignInButtons returnTo={returnTo} />
      )}
      <p className="text-xs text-muted-foreground">Accounts are for people aged 16 or older.</p>
    </section>
  );
}

/** Placeholder while `/auth/session` loads. */
export function SessionLoading() {
  return (
    <div className="space-y-3" aria-busy="true" aria-label="Loading">
      <Skeleton className="h-8 w-1/3" />
      <Skeleton className="h-32 w-full" />
    </div>
  );
}
