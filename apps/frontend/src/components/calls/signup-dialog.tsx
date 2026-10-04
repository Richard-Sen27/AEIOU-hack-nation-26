"use client";

import { CheckCircle2, MessageSquare } from "lucide-react";
import Link from "next/link";
import { useId, useState } from "react";

import { Busy } from "@/components/messages/connect-flow";
import { Button, buttonVariants } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { trackEvent } from "@/lib/analytics";
import { signUpToCall, unwrap } from "@/lib/api";
import { ApiError } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

import {
  authorizationText,
  MAX_NAME,
  sharedLabels,
  signupErrorText,
  SIGNUPS_HREF,
  threadHref,
  type MySignup,
  type SignupOptions,
} from "./signup-meta";

function Tick({ id, checked, onChange, children, testId }: { id: string; checked: boolean; onChange: (v: boolean) => void; children: React.ReactNode; testId?: string }) {
  return (
    <label htmlFor={id} className="flex items-start gap-2.5 text-sm">
      <Checkbox id={id} checked={checked} onCheckedChange={(v) => onChange(v === true)} className="mt-0.5" data-testid={testId} />
      <span className="min-w-0">{children}</span>
    </label>
  );
}

/**
 * The sign-up screen, which is the authorization: who receives it, the items
 * to tick (only what the backend pre-ticks starts ticked), a name, an optional
 * note, the authorization text with the ticked items, the optional
 * conversation, and for a 16-17 user the required guardian box. `renew` runs
 * the connect steps again (consent, age group) and returns fresh options.
 */
export function SignupDialog({
  options: initial,
  onClose,
  onSent,
  renew,
}: {
  options: SignupOptions;
  onClose: () => void;
  onSent: (signup: MySignup) => void;
  renew: () => Promise<SignupOptions | null>;
}) {
  const ids = useId();
  const [options, setOptions] = useState(initial);
  const [ticked, setTicked] = useState<string[]>(() => initial.options.filter((o) => o.preselected).map((o) => o.key));
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [authorized, setAuthorized] = useState(false);
  const [guardian, setGuardian] = useState(false);
  const [needGuardian, setNeedGuardian] = useState(initial.guardian_required);
  const [conversation, setConversation] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<MySignup | null>(null);

  const maxNote = options.max_note ?? 1000;
  const noteTooLong = note.length > maxNote;
  const ready = name.trim().length > 0 && authorized && (!needGuardian || guardian) && !noteTooLong && !busy;

  async function send() {
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      const signup = await unwrap(
        signUpToCall({
          path: { call_id: options.call_id },
          body: {
            display_name: name.trim(),
            items: ticked,
            note: note.trim() || null,
            authorized: true,
            // Always sent by the backend; a missing one is refused (422) and named.
            authorization_version: options.authorization_version ?? "",
            guardian_agreed: needGuardian && guardian,
            open_conversation: conversation,
          },
          meta: { quiet: true },
        }),
      );
      setSent(signup);
      trackEvent("signup_submitted");
      onSent(signup);
    } catch (e) {
      const code = e instanceof ApiError ? e.code : "";
      if (code === "consent_required" || code === "age_group_required") {
        setBusy(false);
        const next = await renew();
        if (next) {
          setOptions(next);
          setNeedGuardian(next.guardian_required);
          setTicked((t) => t.filter((k) => next.options.some((o) => o.key === k)));
        }
        setError(next ? "Confirmed. Check and send again." : signupErrorText(e));
        return;
      }
      if (code === "guardian_agreement_required") setNeedGuardian(true);
      setError(signupErrorText(e, { conversation }));
      setBusy(false);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && !busy && onClose()}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg" data-testid="signup-dialog">
        {sent ? (
          <div className="space-y-4" data-testid="signup-sent">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <CheckCircle2 className="size-5 text-primary" aria-hidden /> Sent
              </DialogTitle>
              <DialogDescription>To {options.recipient}. Only the study team decides who takes part.</DialogDescription>
            </DialogHeader>
            {sharedLabels(sent.shared).length > 0 && (
              <ul className="flex flex-wrap gap-1.5" aria-label="Shared">
                {sharedLabels(sent.shared).map((l) => (
                  <li key={l} className="rounded-full border px-2 py-0.5 text-xs">
                    {l}
                  </li>
                ))}
              </ul>
            )}
            <p className="text-sm text-muted-foreground">You can withdraw it any time in My sign-ups.</p>
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              {sent.thread_id && (
                <Link href={threadHref(sent.thread_id)} className={buttonVariants({ variant: "outline" })} data-testid="signup-sent-thread">
                  <MessageSquare data-icon="inline-start" aria-hidden /> Conversation
                </Link>
              )}
              <Link href={SIGNUPS_HREF} className={buttonVariants({ variant: "outline" })} data-testid="signup-sent-mine">
                My sign-ups
              </Link>
              <Button onClick={onClose} data-testid="signup-done">
                Done
              </Button>
            </div>
          </div>
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>Sign up</DialogTitle>
              <DialogDescription data-testid="signup-recipient">
                To {options.recipient}, who runs this call.
              </DialogDescription>
            </DialogHeader>

            <fieldset className="space-y-2" data-testid="signup-items">
              <legend className="mb-2 text-sm font-medium">
                What to share {options.about_child && <span className="font-normal text-muted-foreground">· about your child</span>}
              </legend>
              {options.options.length === 0 ? (
                <p className="text-sm text-muted-foreground" data-testid="signup-no-items">
                  Nothing in your profile matches what this call asks for.
                </p>
              ) : (
                options.options.map((o) => (
                  <Tick
                    key={o.key}
                    id={`${ids}-${o.key}`}
                    checked={ticked.includes(o.key)}
                    onChange={(v) => setTicked((t) => (v ? [...t, o.key] : t.filter((k) => k !== o.key)))}
                    testId={`signup-item-${o.kind}`}
                  >
                    {o.label}
                    {o.detail && <span className="text-muted-foreground"> · {o.detail}</span>}
                  </Tick>
                ))
              )}
            </fieldset>

            <div className="space-y-1.5">
              <label htmlFor={`${ids}-name`} className="text-sm font-medium">
                Your name for the study team
              </label>
              <Input
                id={`${ids}-name`}
                value={name}
                maxLength={MAX_NAME}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Maria, or Leo's mum"
                autoComplete="off"
                data-testid="signup-name"
              />
            </div>

            <div className="space-y-1.5">
              <label htmlFor={`${ids}-note`} className="text-sm font-medium">
                Note <span className="font-normal text-muted-foreground">(optional)</span>
              </label>
              <Textarea
                id={`${ids}-note`}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                className="min-h-20"
                autoComplete="off"
                aria-invalid={noteTooLong || undefined}
                data-testid="signup-note"
              />
              <p className={cn("text-right font-mono text-xs tabular", noteTooLong ? "text-destructive" : "text-muted-foreground")}>
                {note.length}/{maxNote.toLocaleString("en")}
              </p>
            </div>

            <Tick id={`${ids}-conv`} checked={conversation} onChange={setConversation} testId="signup-conversation">
              Also open a conversation with the team
            </Tick>

            <div className="space-y-3 rounded-lg border bg-muted/50 p-3">
              <Tick id={`${ids}-auth`} checked={authorized} onChange={setAuthorized} testId="signup-authorize">
                <span data-testid="signup-authorization">{authorizationText(options, ticked, note.trim().length > 0)}</span>
              </Tick>
              {needGuardian && (
                <Tick id={`${ids}-guardian`} checked={guardian} onChange={setGuardian} testId="signup-guardian">
                  <span data-testid="signup-guardian-text">{options.guardian_text}</span>
                </Tick>
              )}
            </div>

            {error && (
              <p role="alert" className="text-sm text-destructive" data-testid="signup-error">
                {error}
              </p>
            )}

            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button variant="outline" onClick={onClose} disabled={busy}>
                Cancel
              </Button>
              <Button onClick={() => void send()} disabled={!ready} data-testid="signup-send">
                <Busy on={busy} />
                Send
              </Button>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
