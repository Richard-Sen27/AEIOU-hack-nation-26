"use client";

import { Loader2, MessageSquare, Undo2 } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { SessionLoading, SignInPrompt } from "@/components/account/sign-in-prompt";
import { useSession } from "@/components/providers/session-provider";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { listMySignups, withdrawSignup } from "@/lib/api";
import { announce } from "@/lib/a11y";
import { cn } from "@/lib/utils";

import { callHref, formatDate } from "./call-meta";
import { sharedLabels, SIGNUP_STATUS_LABEL, signupErrorText, threadHref, type MySignup } from "./signup-meta";

export function SharedChips({ labels, className }: { labels: string[]; className?: string }) {
  if (!labels.length) return null;
  return (
    <ul className={cn("flex flex-wrap gap-1.5", className)} aria-label="Shared" data-testid="signup-shared">
      {labels.map((l) => (
        <li key={l} className="rounded-full border bg-background px-2 py-0.5 text-xs">
          {l}
        </li>
      ))}
    </ul>
  );
}

function SignupItem({ s, onWithdrawn }: { s: MySignup; onWithdrawn: (id: string) => void }) {
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const canWithdraw = s.status === "active" || s.status === "call_closed";
  const deleteOn = formatDate(s.delete_after);
  const labels = sharedLabels(s.shared);

  async function withdraw() {
    setBusy(true);
    const { error } = await withdrawSignup({ path: { signup_id: s.id }, meta: { quiet: true } });
    setBusy(false);
    setConfirm(false);
    if (error !== undefined) {
      toast(signupErrorText(error));
      return;
    }
    onWithdrawn(s.id);
    toast("Sign-up withdrawn");
    announce("Sign-up withdrawn.");
  }

  return (
    <li className="space-y-2 rounded-xl border bg-card px-4 py-3" data-testid="my-signup" data-status={s.status}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span
          className={cn(
            "inline-flex h-5 items-center rounded-full px-2 text-[11px] font-medium whitespace-nowrap",
            s.status === "active" ? "bg-primary/15 text-foreground" : "bg-muted text-muted-foreground",
          )}
          data-testid="my-signup-status"
        >
          {SIGNUP_STATUS_LABEL[s.status]}
        </span>
        <span className="text-xs text-muted-foreground">{formatDate(s.created_at)}</span>
      </div>
      {s.call_id && s.call_open ? (
        <Link href={callHref(s.call_id)} className="block text-[15px] font-medium text-pretty hover:underline">
          {s.call_title}
        </Link>
      ) : (
        <p className="text-[15px] font-medium text-pretty">{s.call_title}</p>
      )}
      <p className="text-xs text-muted-foreground">
        To {s.recipient} · as “{s.display_name}”
      </p>
      <SharedChips labels={labels} />
      {s.note && <p className="text-sm whitespace-pre-line text-muted-foreground line-clamp-3">{s.note}</p>}
      {deleteOn && (
        <p className="text-xs text-muted-foreground" data-testid="my-signup-delete-after">
          Deleted on {deleteOn}
        </p>
      )}
      {(s.thread_id || canWithdraw) && (
        <div className="flex flex-wrap items-center gap-2 pt-1">
          {s.thread_id && (
            <Link href={threadHref(s.thread_id)} className={buttonVariants({ variant: "outline", size: "sm" })} data-testid="my-signup-thread">
              <MessageSquare data-icon="inline-start" aria-hidden /> Conversation
            </Link>
          )}
          <span className="flex-1" />
          {canWithdraw && (
            <Button variant="ghost" size="sm" onClick={() => setConfirm(true)} disabled={busy} data-testid="my-signup-withdraw">
              <Undo2 data-icon="inline-start" aria-hidden /> Withdraw
            </Button>
          )}
        </div>
      )}
      <AlertDialog open={confirm} onOpenChange={(o) => !busy && !o && setConfirm(false)}>
        <AlertDialogContent className="sm:max-w-md" data-testid="my-signup-confirm">
          <AlertDialogHeader>
            <AlertDialogTitle>Withdraw this sign-up?</AlertDialogTitle>
            <AlertDialogDescription>
              What you shared is deleted from Amber now. It cannot undo what the team already noted.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Keep it</AlertDialogCancel>
            <Button variant="destructive" onClick={() => void withdraw()} disabled={busy} data-testid="my-signup-confirm-action">
              {busy && <Loader2 className="animate-spin" aria-hidden />}
              Withdraw
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </li>
  );
}

type Load = { kind: "loading" } | { kind: "ready"; items: MySignup[] } | { kind: "error"; message: string };

/**
 * The patient's own sign-ups: status, what was shared, when it is deleted,
 * withdraw with one confirmation, the conversation. Used on `/calls/signups`
 * and in the profile (`variant="profile"`: no sign-in prompt of its own).
 */
export function MySignups({ variant = "page" }: { variant?: "page" | "profile" }) {
  const { user, status } = useSession();
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const userId = user?.id ?? null;

  const fetchList = useCallback(async () => {
    const { data, error } = await listMySignups({ meta: { quiet: true }, cache: "no-store" });
    if (data) setLoad({ kind: "ready", items: data.items });
    else setLoad({ kind: "error", message: signupErrorText(error) });
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch, state set after await
    if (userId) void fetchList();
  }, [userId, fetchList]);

  if (status === "loading") return variant === "page" ? <SessionLoading /> : null;
  if (!user) {
    return variant === "page" ? (
      <SignInPrompt title="Sign in to see your sign-ups" description="Studies, surveys and trials you signed up to. Private to you." returnTo="/calls/signups" />
    ) : null;
  }
  if (load.kind === "loading") {
    return (
      <div className="space-y-3" aria-busy="true" aria-label="Loading your sign-ups">
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }
  if (load.kind === "error") {
    return (
      <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground" role="status" data-testid="my-signups-error">
        {load.message}
        <Button variant="outline" size="sm" onClick={() => void fetchList()}>
          Try again
        </Button>
      </div>
    );
  }
  if (load.items.length === 0) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="my-signups-empty">
        No sign-ups yet.{" "}
        <Link href="/calls" className="font-medium text-foreground underline underline-offset-2">
          See open calls
        </Link>
      </p>
    );
  }
  return (
    <ul className="space-y-3" data-testid="my-signups">
      {load.items.map((s) => (
        <SignupItem key={s.id} s={s} onWithdrawn={() => void fetchList()} />
      ))}
    </ul>
  );
}
