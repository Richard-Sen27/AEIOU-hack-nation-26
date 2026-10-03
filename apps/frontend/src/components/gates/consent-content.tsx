"use client";

/**
 * SLOT for the account/compliance feature: the body of the consent dialog,
 * per consent type. Replace `ConsentContent` with the real just-in-time
 * notice and grant flow (GDPR Art. 9 explicit consent, notice at collection,
 * parental-responsibility confirmation, version + timestamp via
 * `POST /consents`). Call `onGranted()` after the API confirms; the gate then
 * refreshes the session and resolves `requireConsent()` with `true`.
 * `onCancel()` resolves it with `false`. Declining must take no more steps
 * than granting.
 */
import { Button } from "@/components/ui/button";
import type { ConsentType } from "@/lib/api/types";

export type ConsentContentProps = {
  type: ConsentType;
  onGranted: () => void;
  onCancel: () => void;
};

export const CONSENT_TITLES: Record<ConsentType, string> = {
  upload: "Before you upload a document",
  contribute: "Before you contribute to the shared atlas",
};

export function ConsentContent({ type, onCancel }: ConsentContentProps) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        {type === "upload"
          ? "Uploading needs your explicit consent to process health information. This consent step is not available yet."
          : "Contributing needs your explicit consent to share information with the atlas. This consent step is not available yet."}
      </p>
      <div className="flex justify-end">
        <Button variant="outline" onClick={onCancel}>
          Close
        </Button>
      </div>
    </div>
  );
}
