"use client";

import { useId, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { reportThread, unwrap, type Schemas } from "@/lib/api";

import { Busy, messagingErrorText } from "./connect-flow";
import { useMessages } from "./messages-shell";

type Reason = Schemas.ReportReason;

const REASONS: Array<[Reason, string]> = [
  ["harassment", "Harassment"],
  ["spam", "Spam"],
  ["medical_advice", "Medical advice or prescribing"],
  ["impersonation", "Pretends to be someone else"],
  ["other", "Something else"],
];

const FALLBACK_AUTHORIZATION = "I ask the Amber team to read this conversation to review my report. Every access is logged.";

/** Report a conversation or one message; the authorization box is required (the backend's text). */
export function ReportDialog({ threadId, messageId, onClose }: { threadId: string; messageId?: string; onClose: () => void }) {
  const ids = useId();
  const { flow } = useMessages();
  const [reason, setReason] = useState<Reason | null>(null);
  const [authorized, setAuthorized] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ready = reason !== null && authorized && !busy;

  async function send() {
    if (!ready || !reason) return;
    setBusy(true);
    setError(null);
    try {
      await unwrap(
        reportThread({
          path: { thread_id: threadId },
          body: { reason, message_id: messageId ?? null, authorize_review: true },
          meta: { quiet: true },
        }),
      );
      toast("Report sent. Thank you.");
      onClose();
    } catch (e) {
      setError(messagingErrorText(e));
      setBusy(false);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && !busy && onClose()}>
      <DialogContent className="sm:max-w-md" data-testid="report-dialog">
        <DialogHeader>
          <DialogTitle>{messageId ? "Report message" : "Report conversation"}</DialogTitle>
          <DialogDescription className="sr-only">Choose a reason and confirm.</DialogDescription>
        </DialogHeader>
        <RadioGroup value={reason} onValueChange={(v) => setReason(v as Reason)} className="gap-1.5" aria-label="Reason">
          {REASONS.map(([value, label]) => (
            <label key={value} className="flex items-center gap-2.5 py-1 text-sm">
              <RadioGroupItem value={value} aria-label={label} />
              {label}
            </label>
          ))}
        </RadioGroup>
        <label htmlFor={`${ids}-auth`} className="flex items-start gap-2.5 rounded-lg border bg-muted/50 p-3 text-sm">
          <Checkbox
            id={`${ids}-auth`}
            checked={authorized}
            onCheckedChange={(v) => setAuthorized(v === true)}
            className="mt-0.5"
            data-testid="report-authorize"
          />
          <span>{flow.status?.report_authorization_text ?? FALLBACK_AUTHORIZATION}</span>
        </label>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void send()} disabled={!ready} data-testid="report-send">
            <Busy on={busy} /> Send report
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
