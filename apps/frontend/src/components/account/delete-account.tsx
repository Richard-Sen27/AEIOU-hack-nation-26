"use client";

import { Loader2, Trash2 } from "lucide-react";
import { useState } from "react";

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
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/errors";
import { deleteMe, unwrap } from "@/lib/api";

export const DELETED_ON_ACCOUNT_DELETION = [
  "Your account, settings and ChatGPT connection",
  "Your profile: diagnoses, genes, variants, symptoms",
  "Your chats with Dr. Wu",
  "Your documents and their findings",
  "Your consents and their history",
  "Your contributions, removed from the shared atlas",
  "Your flags on links",
];

/** `DELETE /me` behind one confirmation, then sign out. */
export function DeleteAccountButton({ variant = "default" }: { variant?: "default" | "compact" }) {
  const { signOut } = useSession();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await unwrap(deleteMe({ meta: { quiet: true } }));
      await signOut();
    } catch (e) {
      const code = e instanceof ApiError ? e.code : "";
      setError(
        code === "rate_limited"
          ? "Too many attempts in the last hour. Nothing was deleted; please try again later."
          : code === "not_implemented"
          ? "Account deletion is not available yet. Please write to the privacy contact on the privacy page."
          : code === "network_error"
            ? "Amber's server is not reachable. Nothing was deleted; please try again."
            : "Your account could not be deleted. Nothing was deleted; please try again.",
      );
      setBusy(false);
    }
  }

  return (
    <>
      <Button
        variant="destructive"
        size={variant === "compact" ? "default" : "lg"}
        onClick={() => setOpen(true)}
        data-testid="delete-account"
      >
        <Trash2 aria-hidden /> Delete my account
      </Button>
      <AlertDialog open={open} onOpenChange={(o) => !busy && setOpen(o)}>
        <AlertDialogContent className="sm:max-w-md" data-testid="delete-account-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle>Delete your account?</AlertDialogTitle>
            <AlertDialogDescription render={<div />} className="space-y-2 text-left text-sm">
              <p>This permanently deletes:</p>
              <ul className="list-disc space-y-0.5 pl-4">
                {DELETED_ON_ACCOUNT_DELETION.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
              <p>It cannot be undone. Backups are cleared within the backup cycle. You will be signed out.</p>
            </AlertDialogDescription>
          </AlertDialogHeader>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Keep my account</AlertDialogCancel>
            <Button variant="destructive" onClick={() => void remove()} disabled={busy}>
              {busy && <Loader2 className="animate-spin" aria-hidden />}
              Delete everything
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
