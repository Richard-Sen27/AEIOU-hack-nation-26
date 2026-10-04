"use client";

import { ChevronDown, Loader2, MessageSquare, UserX } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

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
import { declineCallSignup, listCallSignups, type Schemas } from "@/lib/api";
import { announce } from "@/lib/a11y";
import { ApiError } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

import { formatDate } from "./call-meta";
import { SharedChips } from "./my-signups";
import { RECEIVED_STATUS_LABEL, sharedLabels, threadHref, type ReceivedSignup } from "./signup-meta";

function declineErrorText(e: unknown): string {
  const code = e instanceof ApiError ? e.code : "";
  if (code === "conflict") return "Only active sign-ups can be declined.";
  if (code === "not_found") return "This sign-up is no longer here.";
  if (code === "network_error") return "Amber's server is not reachable. Please try again.";
  return "That did not work. Try again in a moment.";
}

function Received({ s, onChange, callId }: { s: ReceivedSignup; callId: string; onChange: (s: ReceivedSignup) => void }) {
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const active = s.status === "active";

  async function decline() {
    setBusy(true);
    const { data, error } = await declineCallSignup({ path: { call_id: callId, signup_id: s.id }, meta: { quiet: true } });
    setBusy(false);
    setConfirm(false);
    if (!data) {
      toast(declineErrorText(error));
      return;
    }
    onChange(data);
    toast("Sign-up declined");
    announce("Sign-up declined.");
  }

  return (
    <li className="space-y-1.5 py-3" data-testid="received-signup" data-status={s.status}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className={cn("text-sm font-medium", !active && "text-muted-foreground")}>{s.display_name}</span>
        {!active && (
          <span className="inline-flex h-5 items-center rounded-full bg-muted px-2 text-[11px] font-medium text-muted-foreground" data-testid="received-status">
            {RECEIVED_STATUS_LABEL[s.status]}
          </span>
        )}
        {s.about_child && (
          <span className="inline-flex h-5 items-center rounded-full border px-2 text-[11px]" data-testid="received-child">
            About a child
          </span>
        )}
        <span className="text-xs text-muted-foreground">{formatDate(s.created_at)}</span>
      </div>
      {s.minor && s.minor_label && (
        <p className="text-xs font-medium text-foreground" data-testid="received-minor">
          {s.minor_label}
        </p>
      )}
      <SharedChips labels={sharedLabels(s.shared)} />
      {s.note && <p className="text-sm whitespace-pre-line text-muted-foreground" data-testid="received-note">{s.note}</p>}
      {(s.thread_id || active) && (
        <div className="flex flex-wrap items-center gap-2">
          {s.thread_id && (
            <Link href={threadHref(s.thread_id)} className={buttonVariants({ variant: "outline", size: "xs" })} data-testid="received-thread">
              <MessageSquare data-icon="inline-start" aria-hidden /> Conversation
            </Link>
          )}
          {active && (
            <Button variant="ghost" size="xs" onClick={() => setConfirm(true)} disabled={busy} data-testid="received-decline">
              <UserX data-icon="inline-start" aria-hidden /> Decline
            </Button>
          )}
        </div>
      )}
      <AlertDialog open={confirm} onOpenChange={(o) => !busy && !o && setConfirm(false)}>
        <AlertDialogContent className="sm:max-w-md" data-testid="received-confirm">
          <AlertDialogHeader>
            <AlertDialogTitle>Decline {s.display_name}?</AlertDialogTitle>
            <AlertDialogDescription>What they shared and their note are deleted. They see that you declined.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Keep</AlertDialogCancel>
            <Button variant="destructive" onClick={() => void decline()} disabled={busy} data-testid="received-confirm-action">
              {busy && <Loader2 className="animate-spin" aria-hidden />}
              Decline
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </li>
  );
}

/**
 * The sign-ups one of my calls received: the count against `max_signups`,
 * and per sign-up only what the participant chose to send (display name,
 * ticked items, note), the 16-17 label and whether it is about a child.
 * Never anything that identifies an account.
 */
export function CallSignups({ callId }: { callId: string }) {
  const [list, setList] = useState<Schemas.ReceivedSignupList | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);

  const fetchList = useCallback(async () => {
    const { data } = await listCallSignups({ path: { call_id: callId }, meta: { quiet: true }, cache: "no-store" });
    if (data) setList(data);
    setFailed(!data);
  }, [callId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch, state set after await
    void fetchList();
  }, [fetchList]);

  if (failed) {
    return (
      <p className="flex items-center gap-2 text-xs text-muted-foreground" data-testid="call-signups-error">
        Sign-ups could not be loaded.
        <Button variant="ghost" size="xs" onClick={() => void fetchList()}>
          Try again
        </Button>
      </p>
    );
  }
  if (!list) return null;
  const count = list.max_signups ? `${list.active_count} of ${list.max_signups}` : String(list.active_count);
  if (list.items.length === 0) {
    return (
      <p className="text-xs text-muted-foreground" data-testid="call-signups-count">
        No sign-ups yet.
      </p>
    );
  }
  const replace = (s: ReceivedSignup) =>
    setList((l) => {
      if (!l) return l;
      const items = l.items.map((x) => (x.id === s.id ? s : x));
      return { ...l, items, active_count: items.filter((x) => x.status === "active").length };
    });

  return (
    <div className="border-t pt-2" data-testid="call-signups">
      <Button
        variant="ghost"
        size="sm"
        className="-ml-2"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        data-testid="call-signups-toggle"
      >
        Sign-ups <span className="font-mono tabular" data-testid="call-signups-count">{count}</span>
        <ChevronDown className={cn("transition-transform", open && "rotate-180")} data-icon="inline-end" aria-hidden />
      </Button>
      {open && (
        <ul className="divide-y" data-testid="call-signups-list">
          {list.items.map((s) => (
            <Received key={s.id} s={s} callId={callId} onChange={replace} />
          ))}
        </ul>
      )}
    </div>
  );
}
