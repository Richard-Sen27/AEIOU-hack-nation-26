"use client";

import { Ban, Eye, Loader2, PenLine, Plus, Send, Trash2, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { routeGlobalError } from "@/components/account/api-errors";
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
import { closeCall, deleteCall, listMyCalls, submitCall, type Schemas } from "@/lib/api";
import { announce } from "@/lib/a11y";
import type { ApiError } from "@/lib/api/errors";

import { callErrorText, callHref, fieldLabel, formatDate, reviewRequired, type OwnCall } from "./call-meta";
import { DemoMark, KindBadge, StatusBadge } from "./call-parts";
import { invalidatePublishedCalls } from "./use-published-calls";

type Load = { kind: "loading" } | { kind: "ready"; data: Schemas.OwnCallList } | { kind: "error"; error: ApiError | null };

const OPEN = new Set(["draft", "pending_review", "published"]);

/** One line in the publisher's list: one line per state, never an essay. */
function statusLine(c: OwnCall): string | null {
  if (c.status === "pending_review") return `Sent ${formatDate(c.submitted_at)}. Waiting for review by the Amber team.`;
  if (c.status === "published") return c.expired ? "Past its closing date, no longer listed." : `Listed since ${formatDate(c.published_at)}.`;
  if (c.status === "closed") return `Closed ${formatDate(c.closed_at)}.`;
  if (c.status === "withdrawn") return `Withdrawn ${formatDate(c.closed_at)}.`;
  if (c.status === "draft") return `Saved ${formatDate(c.updated_at)}. Not sent yet.`;
  return null;
}

export function NotPublisherNote() {
  return (
    <p className="text-sm text-muted-foreground" data-testid="calls-not-publisher">
      Publishing calls is for verified doctors and researchers.{" "}
      <Link href="/calls" className="font-medium text-foreground underline underline-offset-2">
        See open calls
      </Link>
    </p>
  );
}

/** Why a doctor or researcher cannot publish yet, and where to change it. */
export function CannotPublishNote() {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-dashed px-4 py-3 text-sm sm:flex-row sm:items-center" data-testid="calls-cannot-publish">
      <p className="text-muted-foreground">To publish, get verified and switch on your public card.</p>
      <Link href="/profile#your-work" className="font-medium underline underline-offset-2 sm:ml-auto" data-testid="card-settings-link">
        Card settings
      </Link>
    </div>
  );
}

function OwnCallItem({
  call,
  review,
  onChange,
  onRemove,
}: {
  call: OwnCall;
  review: boolean;
  onChange: (c: OwnCall) => void;
  onRemove: (id: string) => void;
}) {
  const [busy, setBusy] = useState<"submit" | "close" | "delete" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<"close" | "delete" | null>(null);
  const line = statusLine(call);
  const canSubmit = call.status === "draft" || call.status === "rejected";
  const canClose = OPEN.has(call.status) || call.status === "rejected";

  async function run(action: "submit" | "close" | "delete") {
    setBusy(action);
    setError(null);
    const path = { call_id: call.id };
    const { data, error } =
      action === "submit"
        ? await submitCall({ path, meta: { quiet: true } })
        : action === "close"
          ? await closeCall({ path, meta: { quiet: true } })
          : await deleteCall({ path, meta: { quiet: true } });
    setBusy(null);
    setConfirm(null);
    if (error !== undefined) {
      const err = routeGlobalError(error);
      setError(callErrorText(err));
      announce("That did not work.", "assertive");
      return;
    }
    invalidatePublishedCalls();
    if (action === "delete") {
      onRemove(call.id);
      toast("Call deleted");
      announce("Call deleted.");
      return;
    }
    const next = data as OwnCall;
    onChange(next);
    const msg =
      action === "submit"
        ? next.status === "published"
          ? "Published"
          : "Sent for review"
        : call.status === "published"
          ? "Call closed"
          : "Call withdrawn";
    toast(msg);
    announce(`${msg}.`);
  }

  return (
    <li className="space-y-2.5 rounded-xl border bg-card px-4 py-3.5" data-testid="own-call" data-status={call.status}>
      <div className="flex flex-wrap items-center gap-1.5">
        <KindBadge kind={call.kind} />
        <StatusBadge status={call.status} expired={call.expired} />
        {call.demo && <DemoMark />}
      </div>
      <p className="text-[15px] font-medium text-pretty">{call.title}</p>
      {line && <p className="text-xs text-muted-foreground">{line}</p>}
      {call.review_note && (
        <p className="rounded-md bg-muted px-3 py-2 text-sm" data-testid="own-call-review-note">
          <span className="font-medium">Note from the Amber team: </span>
          {call.review_note}
        </p>
      )}
      {call.wording_issues.length > 0 && call.editable && (
        <p className="flex items-start gap-1.5 text-sm" data-testid="own-call-wording">
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-status-flag" aria-hidden />
          <span>
            Rephrase before sending:{" "}
            {call.wording_issues.map((w, i) => (
              <span key={`${w.field}-${w.term}`}>
                {i > 0 && ", "}
                {fieldLabel(w.field)} (&ldquo;{w.term}&rdquo;)
              </span>
            ))}
          </span>
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive" data-testid="own-call-error">
          {error}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2 pt-1">
        {call.editable && (
          <Link href={`/calls/mine/${encodeURIComponent(call.id)}`} className={buttonVariants({ variant: "outline", size: "sm" })} data-testid="own-call-edit">
            <PenLine data-icon="inline-start" aria-hidden /> Edit
          </Link>
        )}
        {call.status === "published" && !call.expired && (
          <Link href={callHref(call.id)} className={buttonVariants({ variant: "outline", size: "sm" })} data-testid="own-call-view">
            <Eye data-icon="inline-start" aria-hidden /> View
          </Link>
        )}
        {canSubmit && (
          <Button size="sm" onClick={() => void run("submit")} disabled={busy !== null} data-testid="own-call-submit">
            {busy === "submit" ? <Loader2 className="animate-spin" data-icon="inline-start" aria-hidden /> : <Send data-icon="inline-start" aria-hidden />}
            {review ? "Submit for review" : "Publish"}
          </Button>
        )}
        <span className="flex-1" />
        {canClose && (
          <Button variant="ghost" size="sm" onClick={() => setConfirm("close")} disabled={busy !== null} data-testid="own-call-close">
            <Ban data-icon="inline-start" aria-hidden /> {call.status === "published" ? "Close" : "Withdraw"}
          </Button>
        )}
        <Button variant="ghost" size="sm" onClick={() => setConfirm("delete")} disabled={busy !== null} data-testid="own-call-delete">
          <Trash2 data-icon="inline-start" aria-hidden /> Delete
        </Button>
      </div>
      {canSubmit && review && <p className="text-xs text-muted-foreground">The Amber team reviews it before it is listed.</p>}

      <AlertDialog open={confirm !== null} onOpenChange={(o) => !busy && !o && setConfirm(null)}>
        <AlertDialogContent className="sm:max-w-md" data-testid="own-call-confirm">
          <AlertDialogHeader>
            <AlertDialogTitle>
              {confirm === "delete" ? "Delete this call?" : call.status === "published" ? "Close this call?" : "Withdraw this call?"}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {confirm === "delete"
                ? "It is removed from Amber with its review history. This cannot be undone."
                : call.status === "published"
                  ? "It is no longer listed. A closed call cannot be opened again."
                  : "It will not be reviewed or listed."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy !== null}>Keep it</AlertDialogCancel>
            <Button variant="destructive" onClick={() => confirm && void run(confirm)} disabled={busy !== null} data-testid="own-call-confirm-action">
              {busy && <Loader2 className="animate-spin" aria-hidden />}
              {confirm === "delete" ? "Delete" : call.status === "published" ? "Close" : "Withdraw"}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </li>
  );
}

/** `/calls/mine`: the doctor's or researcher's own calls in every status. */
export function MyCalls() {
  const { user, status } = useSession();
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const professional = user?.role === "doctor" || user?.role === "researcher";

  const fetchList = useCallback(async () => {
    const { data, error } = await listMyCalls({ meta: { quiet: true }, cache: "no-store" });
    if (data) setLoad({ kind: "ready", data });
    else setLoad({ kind: "error", error: routeGlobalError(error) });
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch, state set after await
    if (professional) void fetchList();
  }, [professional, fetchList]);

  if (status === "loading") return <SessionLoading />;
  if (!user) {
    return <SignInPrompt title="Sign in to see your calls" description="Doctors and researchers publish surveys, studies and trials here." returnTo="/calls/mine" />;
  }
  if (!professional) return <NotPublisherNote />;
  if (load.kind === "loading") {
    return (
      <div className="space-y-3" aria-busy="true" aria-label="Loading your calls">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-28 w-full" />
      </div>
    );
  }
  if (load.kind === "error") {
    return (
      <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground" role="status" data-testid="my-calls-error">
        {callErrorText(load.error)}
        <Button variant="outline" size="sm" onClick={() => void fetchList()}>
          Try again
        </Button>
      </div>
    );
  }

  const { items, can_publish, open_limit } = load.data;
  const openCount = items.filter((c) => OPEN.has(c.status)).length;
  const atLimit = openCount >= (open_limit ?? 10);
  const replace = (c: OwnCall) => setLoad({ kind: "ready", data: { ...load.data, items: items.map((x) => (x.id === c.id ? c : x)) } });
  const remove = (id: string) => setLoad({ kind: "ready", data: { ...load.data, items: items.filter((x) => x.id !== id) } });

  return (
    <div className="space-y-4" data-testid="my-calls">
      {!can_publish && <CannotPublishNote />}
      {can_publish && (
        <div className="flex flex-wrap items-center gap-3">
          {atLimit ? (
            <p className="text-sm text-muted-foreground" data-testid="calls-at-limit">
              {open_limit} open calls at most. Close one to write another.
            </p>
          ) : (
            <Link href="/calls/mine/new" className={buttonVariants()} data-testid="new-call">
              <Plus data-icon="inline-start" aria-hidden /> New call
            </Link>
          )}
        </div>
      )}
      {items.length > 0 ? (
        <ul className="space-y-3" data-testid="own-calls">
          {items.map((c) => (
            <OwnCallItem key={c.id} call={c} review={reviewRequired(load.data)} onChange={replace} onRemove={remove} />
          ))}
        </ul>
      ) : (
        can_publish && <p className="text-sm text-muted-foreground" data-testid="own-calls-empty">No calls yet.</p>
      )}
    </div>
  );
}
