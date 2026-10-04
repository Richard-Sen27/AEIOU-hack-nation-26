"use client";

import { MessageSquare } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import { toast } from "sonner";

import { VerificationLabel } from "@/components/people/verification-label";
import { useSession } from "@/components/providers/session-provider";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api/errors";
import { openThread, unwrap, type Schemas } from "@/lib/api";
import { trackEvent } from "@/lib/analytics";

import { Busy, guardianText, messagingErrorText, useConnectFlow, type ConnectStatus } from "./connect-flow";
import { MAX_BODY, MAX_NAME, PatientBanner } from "./labels";

type Recipient = { card_id: string; name: string; accepts_patient_messages: boolean; verification?: Schemas.CardVerification };

/** Whether this viewer may write to this card: only patients, only cards that accept messages. */
export function canMessageCard(role: string | null | undefined, card: { accepts_patient_messages: boolean }) {
  return role === "patient" && card.accepts_patient_messages;
}

/**
 * "Message" on an expert's public card: the connect consent and age group just
 * in time, then the request dialog. Renders nothing for anyone who cannot use it.
 */
export function MessageCardAction({ card, className }: { card: Recipient; className?: string }) {
  const { user } = useSession();
  const flow = useConnectFlow();
  const [open, setOpen] = useState<ConnectStatus | null>(null);
  const [busy, setBusy] = useState(false);
  if (!canMessageCard(user?.role, card)) return null;

  async function start() {
    setBusy(true);
    const s = await flow.ensure();
    setBusy(false);
    if (s) setOpen(s);
  }

  return (
    <>
      <Button onClick={() => void start()} disabled={busy} className={className} data-testid="message-card">
        {busy ? <Busy on /> : <MessageSquare aria-hidden />}
        Message
      </Button>
      {flow.dialog}
      {open && (
        <MessageRequestDialog
          card={card}
          status={open}
          onClose={() => setOpen(null)}
          reconfirm={async () => {
            const s = await flow.ensure(true);
            if (s) setOpen(s);
            return s;
          }}
        />
      )}
    </>
  );
}

function MessageRequestDialog({
  card,
  status,
  onClose,
  reconfirm,
}: {
  card: Recipient;
  status: ConnectStatus;
  onClose: () => void;
  reconfirm: () => Promise<ConnectStatus | null>;
}) {
  const ids = useId();
  const router = useRouter();
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [guardian, setGuardian] = useState(false);
  const [needGuardian, setNeedGuardian] = useState(status.age_group === "16_17");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exists, setExists] = useState(false);

  const ready = name.trim().length > 0 && body.trim().length > 0 && body.length <= MAX_BODY && (!needGuardian || guardian) && !busy;

  async function send() {
    if (!ready) return;
    setBusy(true);
    setError(null);
    setExists(false);
    try {
      const detail = await unwrap(
        openThread({
          body: { card_id: card.card_id, display_name: name.trim(), body, guardian_agreed: needGuardian && guardian },
          meta: { quiet: true },
        }),
      );
      toast("Request sent.");
      trackEvent("message_sent", { kind: "request" });
      onClose();
      router.push(`/messages/${detail.thread.id}`);
    } catch (e) {
      const code = e instanceof ApiError ? e.code : "";
      if (code === "consent_required" || code === "age_group_required") {
        setBusy(false);
        const s = await reconfirm();
        if (s) setNeedGuardian(s.age_group === "16_17");
        setError(s ? "Confirmed. Send again." : messagingErrorText(e, "open"));
        return;
      }
      if (code === "guardian_agreement_required") setNeedGuardian(true);
      if (code === "conflict") setExists(true);
      setError(messagingErrorText(e, "open"));
      setBusy(false);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && !busy && onClose()}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg" data-testid="message-request-dialog">
        <DialogHeader>
          <DialogTitle>Message {card.name}</DialogTitle>
          <DialogDescription>A request. They accept or decline it.</DialogDescription>
          {card.verification?.simulated && <VerificationLabel verification={card.verification} />}
        </DialogHeader>
        <PatientBanner />
        <div className="space-y-3">
          <div className="space-y-1.5">
            <label htmlFor={`${ids}-name`} className="text-sm font-medium">
              Your name for them
            </label>
            <Input
              id={`${ids}-name`}
              value={name}
              maxLength={MAX_NAME}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Maria, or Leo's mum"
              autoComplete="off"
              data-testid="request-name"
            />
            <p className="text-xs text-muted-foreground">Only this name and your message are shown.</p>
          </div>
          <div className="space-y-1.5">
            <label htmlFor={`${ids}-body`} className="text-sm font-medium">
              Message
            </label>
            <Textarea
              id={`${ids}-body`}
              value={body}
              maxLength={MAX_BODY}
              onChange={(e) => setBody(e.target.value)}
              className="max-h-[40vh] min-h-28"
              autoComplete="off"
              data-testid="request-body"
            />
            <p className="text-right font-mono text-xs text-muted-foreground tabular">
              {body.length}/{MAX_BODY.toLocaleString("en")}
            </p>
          </div>
          {needGuardian && (
            <label htmlFor={`${ids}-guardian`} className="flex items-start gap-2.5 rounded-lg border bg-muted/50 p-3 text-sm">
              <Checkbox
                id={`${ids}-guardian`}
                checked={guardian}
                onCheckedChange={(v) => setGuardian(v === true)}
                className="mt-0.5"
                data-testid="guardian-checkbox"
              />
              <span>{guardianText(status, card.name)}</span>
            </label>
          )}
        </div>
        {error && (
          <p role="alert" className="text-sm text-destructive" data-testid="request-error">
            {error}{" "}
            {exists && (
              <Link href="/messages" className="font-medium underline underline-offset-2" onClick={onClose}>
                Open Messages
              </Link>
            )}
          </p>
        )}
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void send()} disabled={!ready} data-testid="request-send">
            <Busy on={busy} />
            Send request
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
