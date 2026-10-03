"use client";

import { ShieldCheck } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { ConsentType } from "@/lib/api/types";

import { CONSENT_TITLES, ConsentContent } from "./consent-content";

/** Dialog shell; the body lives in ./consent-content.tsx (feature slot). */
export function ConsentDialog({
  type,
  onGranted,
  onCancel,
}: {
  type: ConsentType | null;
  onGranted: () => void;
  onCancel: () => void;
}) {
  return (
    <Dialog open={type !== null} onOpenChange={(open) => !open && onCancel()}>
      <DialogContent
        className="sm:max-w-lg"
        data-testid="consent-dialog"
        // Start at the top of the notice, not at its first link further down.
        initialFocus={() => document.querySelector<HTMLElement>("[data-consent-notice]")}
      >
        {type && (
          <>
            <DialogHeader className="gap-3">
              <span className="flex size-10 items-center justify-center rounded-lg bg-accent text-accent-foreground">
                <ShieldCheck className="size-5" aria-hidden />
              </span>
              <DialogTitle className="text-lg font-semibold tracking-tight">
                {CONSENT_TITLES[type]}
              </DialogTitle>
            </DialogHeader>
            <ConsentContent type={type} onGranted={onGranted} onCancel={onCancel} />
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
