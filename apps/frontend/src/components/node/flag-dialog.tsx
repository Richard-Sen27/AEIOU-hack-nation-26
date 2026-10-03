"use client";

import { Flag } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { flagEdge, reportApiError, type ApiError, type Schemas } from "@/lib/api";

export const FLAG_REASON_MAX = 280;

/**
 * "Flag this connection": short reason, POST /edges/{id}/flag. The reason is
 * sent in the request body only (never a URL) and never logged here.
 */
export function FlagDialog({
  edgeId,
  open,
  onOpenChange,
  onFlagged,
  onAlreadyFlagged,
}: {
  edgeId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onFlagged: (result: Schemas.FlagResult) => void;
  onAlreadyFlagged: () => void;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = reason.trim();
    if (text.length < 3) {
      setError("Please say briefly what looks wrong.");
      return;
    }
    setBusy(true);
    setError(null);
    const { data, error: err } = await flagEdge({
      path: { edge_id: edgeId },
      body: { reason: text },
      meta: { quiet: true },
    });
    setBusy(false);
    if (data) {
      setReason("");
      onFlagged(data);
      onOpenChange(false);
      return;
    }
    const apiError = err as unknown as ApiError | undefined;
    switch (apiError?.code) {
      case "conflict":
        setReason("");
        onAlreadyFlagged();
        onOpenChange(false);
        return;
      case "validation_error":
        setError(
          "This reason looks like it may contain personal details. Describe only what is wrong with the connection, without names, dates or health information.",
        );
        return;
      case "rate_limited":
        setError("You have flagged many connections in a short time. Please try again later.");
        return;
      case "not_found":
        setError("This connection no longer exists in the atlas.");
        return;
      default:
        // Sign-in, age confirmation, outages: the global handlers know what to do.
        if (apiError) reportApiError(apiError);
        if (apiError?.status === 401 || apiError?.status === 403) onOpenChange(false);
        else setError("The flag could not be sent. Please try again.");
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" data-testid="flag-dialog">
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Flag className="size-4 text-status-flag" aria-hidden /> Flag this connection
            </DialogTitle>
            <DialogDescription>
              Tell us what looks wrong, for example a source that does not say this. The connection is
              marked as under review until someone checks it.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-1.5">
            <label htmlFor="flag-reason" className="text-sm font-medium">
              What looks wrong?
            </label>
            <Textarea
              id="flag-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value.slice(0, FLAG_REASON_MAX))}
              maxLength={FLAG_REASON_MAX}
              rows={4}
              required
              aria-invalid={!!error}
              aria-describedby="flag-reason-help flag-reason-error"
              placeholder="The cited paper studies a different gene."
            />
            <div id="flag-reason-help" className="flex justify-between gap-3 text-xs text-muted-foreground">
              <span>Please do not include names, dates or health details.</span>
              <span className="font-mono tabular">
                {reason.length}/{FLAG_REASON_MAX}
              </span>
            </div>
            {error && (
              <p id="flag-reason-error" role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy} data-testid="flag-submit">
              {busy ? "Sending…" : "Send flag"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
