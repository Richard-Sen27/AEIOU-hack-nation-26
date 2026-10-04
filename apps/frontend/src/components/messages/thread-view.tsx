"use client";

import { ArrowLeft, Ban, EyeOff, Flag, MoreHorizontal, Send, Trash2, UserRound } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { announce } from "@/lib/a11y";
import { ApiError } from "@/lib/api/errors";
import {
  acceptThread,
  blockThreadParticipant,
  declineThread,
  deleteMessage,
  getThread,
  hideThread,
  sendMessage,
  unwrap,
  type Schemas,
} from "@/lib/api";
import { cn } from "@/lib/utils";

import { Busy, guardianText, messagingErrorText } from "./connect-flow";
import { closedNote, counterpartName, ExpertBanner, formatWhen, MAX_BODY, PatientBanner, statusLabel } from "./labels";
import { useMessages } from "./messages-shell";
import { ReportDialog } from "./report-dialog";

const THREAD_POLL_MS = 15_000;

type Detail = Schemas.ThreadDetail;
type Confirm = { kind: "block" } | { kind: "delete"; messageId: string } | null;

/** One conversation: messages, the composer or the request buttons, and the actions. */
export function ThreadView({ id }: { id: string }) {
  const router = useRouter();
  const { reload, flow } = useMessages();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [missing, setMissing] = useState(false);
  const [confirm, setConfirm] = useState<Confirm>(null);
  const [report, setReport] = useState<{ messageId?: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const sending = useRef(false);

  const fetchThread = useCallback(async () => {
    const { data, error } = await getThread({ path: { thread_id: id }, meta: { quiet: true }, cache: "no-store" });
    if (data) {
      setDetail(data);
      setMissing(false);
    } else if (error instanceof ApiError && error.code === "not_found") setMissing(true);
    return data;
  }, [id]);

  // Opening marks it read: refresh the list and the header once loaded.
  useEffect(() => {
    let alive = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch, state set after await
    void fetchThread().then((d) => alive && d && void reload());
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible" && !sending.current) void fetchThread();
    }, THREAD_POLL_MS);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [fetchThread, reload]);

  const count = detail?.messages.length ?? 0;
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [count]);

  if (missing) {
    return (
      <div className="flex flex-1 flex-col items-start gap-3 py-6 text-sm text-muted-foreground">
        <BackLink />
        <p>This conversation is no longer here.</p>
      </div>
    );
  }
  if (!detail) {
    return (
      <div className="flex-1 space-y-3 py-6" aria-busy="true" aria-label="Loading">
        <Skeleton className="h-8 w-1/3" />
        <Skeleton className="h-20 w-2/3" />
      </div>
    );
  }

  const t = detail.thread;
  const name = counterpartName(t);
  const iAmPatient = t.counterpart.is_professional;
  const label = statusLabel(t);
  const note = closedNote(t);

  async function act(key: string, fn: () => Promise<void>) {
    setBusy(key);
    try {
      await fn();
    } catch (e) {
      toast(messagingErrorText(e, key === "accept" || key === "decline" ? "respond" : "other"));
    } finally {
      setBusy(null);
    }
  }

  const respond = (accept: boolean) =>
    act(accept ? "accept" : "decline", async () => {
      if (!(await flow.ensure())) return;
      const call = accept ? acceptThread : declineThread;
      setDetail(await unwrap(call({ path: { thread_id: id }, meta: { quiet: true } })));
      // No toast: the composer (or the "declined" line) says it, and a toast would cover Send.
      announce(accept ? "Accepted. You can reply now." : "Declined.");
      await reload();
    });

  const hide = () =>
    act("hide", async () => {
      await unwrap(hideThread({ path: { thread_id: id }, meta: { quiet: true } }));
      toast("Hidden until a new message arrives.");
      await reload();
      router.push("/messages");
    });

  const block = () =>
    act("block", async () => {
      await unwrap(blockThreadParticipant({ path: { thread_id: id }, meta: { quiet: true } }));
      toast(`${name} is blocked.`);
      await Promise.all([fetchThread(), reload()]);
    });

  const remove = (messageId: string) =>
    act("delete", async () => {
      await unwrap(deleteMessage({ path: { thread_id: id, message_id: messageId }, meta: { quiet: true } }));
      setDetail((d) => (d ? { ...d, messages: d.messages.filter((m) => m.id !== messageId) } : d));
      toast("Message deleted.");
    });

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="thread-view" data-status={t.status}>
      <div className="flex items-center gap-2 pt-4 pb-3">
        <BackLink className="lg:hidden" />
        <div className="min-w-0 flex-1">
          <h2 className={cn("truncate text-lg font-semibold tracking-tight", t.counterpart.deleted && "text-muted-foreground italic")} data-testid="thread-name">
            {name}
          </h2>
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            {t.counterpart.is_professional ? "Doctor or researcher" : "Patient or family"}
            {t.counterpart.card_id && !t.counterpart.deleted && (
              <Link href={`/people/${t.counterpart.card_id}`} className="inline-flex items-center gap-1 font-medium text-foreground underline-offset-4 hover:underline">
                <UserRound className="size-3" aria-hidden /> Card
              </Link>
            )}
          </p>
        </div>
        {label && (
          <Badge variant={t.status === "requested" ? "secondary" : "outline"} data-testid="thread-badge">
            {label}
          </Badge>
        )}
        <DropdownMenu>
          <DropdownMenuTrigger render={<Button variant="ghost" size="icon" aria-label="Conversation actions" data-testid="thread-actions" />}>
            <MoreHorizontal aria-hidden />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-44">
            <DropdownMenuItem onClick={() => void hide()}>
              <EyeOff aria-hidden /> Hide
            </DropdownMenuItem>
            {!t.blocked_by_me && !t.counterpart.deleted && (
              <DropdownMenuItem onClick={() => setConfirm({ kind: "block" })}>
                <Ban aria-hidden /> Block
              </DropdownMenuItem>
            )}
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => setReport({})}>
              <Flag aria-hidden /> Report
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {iAmPatient ? <PatientBanner /> : <ExpertBanner />}

      <div ref={logRef} className="-mx-1 min-h-0 flex-1 overflow-y-auto px-1 py-4" data-testid="message-log">
        {detail.messages.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">No messages.</p>
        ) : (
          <ol className="space-y-3" aria-label="Messages">
            {detail.messages.map((m) => (
              <li key={m.id} className={cn("group flex items-end gap-1.5", m.mine ? "flex-row-reverse" : "flex-row")} data-testid="message">
                <div
                  className={cn(
                    "max-w-[85%] rounded-2xl px-3.5 py-2 sm:max-w-[70%]",
                    m.mine ? "rounded-br-md bg-secondary text-secondary-foreground" : "rounded-bl-md bg-muted text-foreground",
                  )}
                >
                  <p className="text-[15px] leading-relaxed break-words whitespace-pre-wrap" dir="auto" data-testid="message-body">
                    <span className="sr-only">{m.mine ? "You: " : `${name}: `}</span>
                    {m.body ?? <span className="text-muted-foreground italic">This message can&apos;t be shown.</span>}
                  </p>
                  <p className={cn("mt-0.5 text-[11px] tabular", m.mine ? "text-right text-secondary-foreground/75" : "text-muted-foreground")}>{formatWhen(m.created_at)}</p>
                </div>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  className="text-muted-foreground opacity-0 group-hover:opacity-100 focus-visible:opacity-100 [@media(hover:none)]:opacity-100"
                  aria-label={m.mine ? "Delete message" : "Report message"}
                  onClick={() => (m.mine ? setConfirm({ kind: "delete", messageId: m.id }) : setReport({ messageId: m.id }))}
                  data-testid={m.mine ? "message-delete" : "message-report"}
                >
                  {m.mine ? <Trash2 aria-hidden /> : <Flag aria-hidden />}
                </Button>
              </li>
            ))}
          </ol>
        )}
      </div>

      <div className="border-t pt-3 pb-4">
        {t.can_respond ? (
          <div className="flex flex-wrap items-center gap-2" data-testid="respond">
            <span className="mr-auto text-sm text-muted-foreground">Accept to reply.</span>
            <Button variant="outline" onClick={() => void respond(false)} disabled={busy !== null} data-testid="decline">
              <Busy on={busy === "decline"} /> Decline
            </Button>
            <Button onClick={() => void respond(true)} disabled={busy !== null} data-testid="accept">
              <Busy on={busy === "accept"} /> Accept
            </Button>
          </div>
        ) : t.can_send ? (
          <Composer
            thread={t}
            name={name}
            onSending={(on) => (sending.current = on)}
            onSent={async () => {
              await fetchThread();
            }}
          />
        ) : (
          note && (
            <p className="text-sm text-muted-foreground" data-testid="thread-note">
              {note}
              {t.status === "blocked" && t.blocked_by_me && (
                <>
                  {" "}
                  <Link href="/profile#settings" className="font-medium text-foreground underline underline-offset-2">
                    Unblock in your profile
                  </Link>
                </>
              )}
            </p>
          )
        )}
      </div>

      <AlertDialog open={confirm !== null} onOpenChange={(o) => !o && setConfirm(null)}>
        <AlertDialogContent data-testid="confirm-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle>{confirm?.kind === "block" ? `Block ${name}?` : "Delete this message?"}</AlertDialogTitle>
            <AlertDialogDescription>
              {confirm?.kind === "block" ? "Neither of you can write until you unblock." : "It is removed for both of you."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              data-testid="confirm-action"
              onClick={() => {
                const c = confirm;
                setConfirm(null);
                if (c?.kind === "block") void block();
                else if (c?.kind === "delete") void remove(c.messageId);
              }}
            >
              {confirm?.kind === "block" ? "Block" : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {report && <ReportDialog threadId={id} messageId={report.messageId} onClose={() => setReport(null)} />}
    </div>
  );
}

function BackLink({ className }: { className?: string }) {
  return (
    <Button variant="ghost" size="icon" className={className} aria-label="All conversations" nativeButton={false} render={<Link href="/messages" />}>
      <ArrowLeft aria-hidden />
    </Button>
  );
}

function Composer({
  thread,
  name,
  onSending,
  onSent,
}: {
  thread: Schemas.ThreadSummary;
  name: string;
  onSending: (on: boolean) => void;
  onSent: () => Promise<void>;
}) {
  const ids = useId();
  const { flow } = useMessages();
  const [body, setBody] = useState("");
  const [guardian, setGuardian] = useState(false);
  const [needGuardian, setNeedGuardian] = useState(thread.guardian_agreement_needed);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The server knows best: once the first message carried the agreement, it is no longer asked.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- follow the thread state
    setNeedGuardian(thread.guardian_agreement_needed);
  }, [thread.guardian_agreement_needed]);

  const ready = body.trim().length > 0 && body.length <= MAX_BODY && (!needGuardian || guardian) && !busy;

  async function send() {
    if (!ready) return;
    setBusy(true);
    onSending(true);
    setError(null);
    try {
      const status = await flow.ensure();
      if (!status) return;
      await unwrap(
        sendMessage({
          path: { thread_id: thread.id },
          body: { body, guardian_agreed: needGuardian && guardian },
          meta: { quiet: true },
        }),
      );
      setBody("");
      setGuardian(false);
      await onSent();
    } catch (e) {
      const code = e instanceof ApiError ? e.code : "";
      if (code === "guardian_agreement_required") setNeedGuardian(true);
      if (code === "consent_required" || code === "age_group_required") void flow.ensure(true);
      setError(messagingErrorText(e, "send"));
      if (code === "conflict") await onSent();
    } finally {
      setBusy(false);
      onSending(false);
    }
  }

  return (
    <div className="space-y-2" data-testid="composer">
      {needGuardian && (
        <label htmlFor={`${ids}-guardian`} className="flex items-start gap-2.5 rounded-lg border bg-muted/50 p-2.5 text-sm">
          <Checkbox
            id={`${ids}-guardian`}
            checked={guardian}
            onCheckedChange={(v) => setGuardian(v === true)}
            className="mt-0.5"
            data-testid="guardian-checkbox"
          />
          <span>{guardianText(flow.status, name)}</span>
        </label>
      )}
      <div className="flex items-end gap-2">
        <label htmlFor={`${ids}-body`} className="sr-only">
          Message to {name}
        </label>
        <Textarea
          id={`${ids}-body`}
          value={body}
          maxLength={MAX_BODY}
          onChange={(e) => setBody(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              void send();
            }
          }}
          placeholder="Write a message"
          className="max-h-40 min-h-10 resize-none"
          autoComplete="off"
          data-testid="composer-input"
        />
        <Button size="icon-lg" onClick={() => void send()} disabled={!ready} aria-label="Send" data-testid="composer-send">
          {busy ? <Busy on /> : <Send aria-hidden />}
        </Button>
      </div>
      {body.length > MAX_BODY - 200 && (
        <p className="text-right font-mono text-xs text-muted-foreground tabular">
          {body.length}/{MAX_BODY.toLocaleString("en")}
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive" data-testid="composer-error">
          {error}
        </p>
      )}
    </div>
  );
}
