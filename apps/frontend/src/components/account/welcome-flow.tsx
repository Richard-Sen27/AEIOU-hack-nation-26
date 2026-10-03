"use client";

import { ArrowRight, Check, Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import { toast } from "sonner";

import { useLens } from "@/components/providers/lens-provider";
import { safeReturnTo, useSession } from "@/components/providers/session-provider";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { announce } from "@/lib/a11y";
import { ApiError } from "@/lib/api/errors";
import { apiFetch } from "@/lib/api/fetch";
import type { SessionUser, SettingsUpdate } from "@/lib/api/generated/types.gen";
import { cn } from "@/lib/utils";

import { DeleteAccountButton } from "./delete-account";
import { LANGUAGES, ROLE_COPY, SELECTABLE_ROLES, type SelectableRole } from "./labels";
import { NativeSelect } from "./native-select";
import { SessionLoading, SignInPrompt } from "./sign-in-prompt";

function browserLanguage(): string {
  if (typeof navigator === "undefined") return "en";
  const code = navigator.language?.slice(0, 2).toLowerCase();
  return LANGUAGES.some((l) => l.code === code) ? code : "en";
}

/** OpenAI's Sign in with ChatGPT guidelines: one-time notice after first sign-in. */
function ChatGptPlanNotice({ open, onDone }: { open: boolean; onDone: () => void }) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onDone()}>
      <DialogContent className="sm:max-w-md" showCloseButton={false} data-testid="chatgpt-plan-notice">
        <DialogHeader className="gap-3">
          {/* eslint-disable-next-line @next/next/no-img-element -- official SVG asset, unmodified */}
          <img src="/brand/chatgpt-logo-black.svg" alt="" width={28} height={28} className="dark:hidden" />
          {/* eslint-disable-next-line @next/next/no-img-element -- official SVG asset, unmodified */}
          <img src="/brand/chatgpt-logo-white.svg" alt="" width={28} height={28} className="hidden dark:block" />
          <DialogTitle className="text-lg font-semibold tracking-tight">You&apos;re using your ChatGPT plan</DialogTitle>
          <DialogDescription className="text-sm leading-relaxed">
            Eligible usage in this app uses your ChatGPT plan. Manage usage in your ChatGPT settings.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button size="lg" onClick={onDone} autoFocus>
            Got it
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function StepHeading({ n, title, done }: { n: number; title: string; done?: boolean }) {
  return (
    <legend className="float-left mb-3 flex w-full items-center gap-2.5 text-base font-semibold tracking-tight">
      <span
        aria-hidden
        className={cn(
          "flex size-6 items-center justify-center rounded-full border font-mono text-[11px]",
          done ? "border-secondary bg-secondary text-secondary-foreground" : "bg-card text-muted-foreground",
        )}
      >
        {done ? <Check className="size-3.5" /> : n}
      </span>
      {title}
    </legend>
  );
}

export function WelcomeFlow({ next }: { next?: string }) {
  const { user, status } = useSession();
  if (status === "loading") return <SessionLoading />;
  if (!user) {
    return (
      <SignInPrompt
        title="Sign in to set up your account"
        description="Choosing how Amber explains things, and confirming your age, happens right after you sign in with ChatGPT."
        returnTo="/welcome"
      />
    );
  }
  // Re-mount when the user changes so the defaults below come from the session.
  return <WelcomeForm key={user.id} user={user} next={next} />;
}

function WelcomeForm({ user, next }: { user: SessionUser; next?: string }) {
  const { refresh } = useSession();
  const { resetRole } = useLens();
  const router = useRouter();
  const ids = useId();
  const firstSignIn = !user.role || user.role === "guest";
  const [planNoticeOpen, setPlanNoticeOpen] = useState(firstSignIn);
  const [role, setRole] = useState<SelectableRole | null>(
    user.role && user.role !== "guest" ? user.role : null,
  );
  const [adult, setAdult] = useState(!!user.age_confirmed);
  const [language, setLanguage] = useState(user.language || browserLanguage());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [triedSubmit, setTriedSubmit] = useState(false);
  const target = safeReturnTo(next);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setTriedSubmit(true);
    if (!role || !adult) {
      announce(!role ? "Please choose how you will use Amber." : "Please confirm that you are 16 or older.", "assertive");
      return;
    }
    setBusy(true);
    setError(null);
    const body: SettingsUpdate = { role, language, age_confirmed_16: true };
    try {
      await apiFetch<SessionUser>("/me/settings", { method: "PATCH", json: body, quiet: true });
      resetRole();
      await refresh();
      toast("You're all set", { description: `${ROLE_COPY[role].label} view. Change it any time in your profile.` });
      router.replace(target);
    } catch (err) {
      const code = err instanceof ApiError ? err.code : "";
      setError(
        code === "network_error"
          ? "Amber's server is not reachable. Please try again in a moment."
          : code === "not_implemented"
            ? "Saving settings is not available yet."
            : "Your settings could not be saved. Please try again.",
      );
      setBusy(false);
    }
  }

  return (
    <>
      <ChatGptPlanNotice open={planNoticeOpen} onDone={() => setPlanNoticeOpen(false)} />
      <form onSubmit={submit} className="space-y-6" noValidate aria-label="Set up your account">
        <fieldset className="rounded-xl border bg-card p-5 sm:p-6 [&>*:not(legend)]:clear-both">
          <StepHeading n={1} title="How will you use Amber?" done={!!role} />
          <p className="-mt-1 mb-4 text-sm text-muted-foreground">
            This decides where you start and how things are explained, never what you can see. You can
            change it at any time.
          </p>
          <RadioGroup
            value={role}
            onValueChange={(v) => setRole(v as SelectableRole)}
            className="grid gap-2.5 sm:grid-cols-3"
            aria-label="Role"
            aria-invalid={triedSubmit && !role}
          >
            {SELECTABLE_ROLES.map((r) => (
              <label
                key={r}
                className={cn(
                  "flex cursor-pointer flex-col gap-2 rounded-lg border bg-background p-3.5 transition-colors hover:bg-muted/60",
                  "has-data-checked:border-primary has-data-checked:bg-primary/10 has-focus-visible:ring-3 has-focus-visible:ring-ring/50",
                )}
              >
                <span className="flex items-center gap-2 text-sm font-medium">
                  <RadioGroupItem value={r} aria-label={ROLE_COPY[r].label} />
                  {ROLE_COPY[r].label}
                </span>
                <span className="text-xs leading-relaxed text-muted-foreground">{ROLE_COPY[r].start}</span>
              </label>
            ))}
          </RadioGroup>
          {triedSubmit && !role && (
            <p className="mt-2 text-sm text-destructive">Please choose one.</p>
          )}
        </fieldset>

        <fieldset className="rounded-xl border bg-card p-5 sm:p-6 [&>*:not(legend)]:clear-both">
          <StepHeading n={2} title="Confirm your age" done={adult} />
          <label htmlFor={`${ids}-adult`} className="flex items-start gap-2.5 text-sm">
            <Checkbox
              id={`${ids}-adult`}
              checked={adult}
              onCheckedChange={(v) => setAdult(v === true)}
              aria-invalid={triedSubmit && !adult}
              className="mt-0.5"
            />
            <span>
              I am <strong className="font-semibold">16 or older</strong>.
              <span className="mt-1 block text-muted-foreground">
                Amber accounts, uploads and Dr. Wu are for people aged 16 and over. Parents and guardians
                can use Amber on behalf of a child.
              </span>
            </span>
          </label>
          {triedSubmit && !adult && (
            <p className="mt-2 text-sm text-destructive">Please confirm that you are 16 or older to continue.</p>
          )}
          <details className="mt-4 text-sm text-muted-foreground">
            <summary className="cursor-pointer font-medium text-foreground">I am under 16</summary>
            <div className="mt-2 space-y-3">
              <p>
                You can keep exploring the atlas without an account. Please ask a parent or guardian if you
                want to use Dr. Wu or upload documents. You can delete this account now; nothing else has
                been stored about you.
              </p>
              <DeleteAccountButton variant="compact" />
            </div>
          </details>
        </fieldset>

        <fieldset className="rounded-xl border bg-card p-5 sm:p-6 [&>*:not(legend)]:clear-both">
          <StepHeading n={3} title="Language (optional)" />
          <label htmlFor={`${ids}-lang`} className="mb-2 block text-sm text-muted-foreground">
            Dr. Wu answers and explanations will use this language.
          </label>
          <NativeSelect
            id={`${ids}-lang`}
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            className="sm:max-w-xs"
          >
            {LANGUAGES.map((l) => (
              <option key={l.code} value={l.code}>
                {l.label}
              </option>
            ))}
          </NativeSelect>
        </fieldset>

        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}

        <div className="flex flex-col-reverse items-stretch gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-muted-foreground">
            How we handle your data:{" "}
            <Link href="/privacy" className="font-medium text-foreground underline underline-offset-2">
              privacy notice
            </Link>
          </p>
          <Button type="submit" size="lg" disabled={busy} className="px-4">
            {busy ? <Loader2 className="animate-spin" aria-hidden /> : null}
            Continue
            {!busy && <ArrowRight data-icon="inline-end" aria-hidden />}
          </Button>
        </div>
      </form>
    </>
  );
}
