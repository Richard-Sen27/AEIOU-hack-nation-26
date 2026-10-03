"use client";

import { Download, Loader2, LogOut, Radio } from "lucide-react";
import Link from "next/link";
import { useState, useSyncExternalStore } from "react";
import { toast } from "sonner";

import { useSession } from "@/components/providers/session-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/errors";
import { apiFetch } from "@/lib/api/fetch";
import type { DataExport } from "@/lib/api/generated/types.gen";

import { DeleteAccountButton } from "./delete-account";

const noop = () => () => {};
const readBrowserGpc = () =>
  (navigator as Navigator & { globalPrivacyControl?: boolean }).globalPrivacyControl === true;

/** Global Privacy Control: show that the signal was received and honoured. */
export function GpcStatus() {
  const { gpc, user } = useSession();
  const browser = useSyncExternalStore(noop, readBrowserGpc, () => false);
  const recorded = !!user?.gpc_opt_out;
  const on = gpc || browser || recorded;
  return (
    <div className="flex items-start gap-3 rounded-lg border bg-background p-4" data-testid="gpc-status" data-gpc={on ? "on" : "off"}>
      <Radio className={on ? "mt-0.5 size-5 shrink-0 text-secondary" : "mt-0.5 size-5 shrink-0 text-muted-foreground"} aria-hidden />
      <div className="space-y-1 text-sm">
        <p className="flex flex-wrap items-center gap-2 font-medium">
          Global Privacy Control
          <Badge variant={on ? "secondary" : "outline"}>{on ? "Signal received and honoured" : "No signal from your browser"}</Badge>
        </p>
        <p className="text-muted-foreground">
          {on
            ? `Your browser asks sites not to sell or share your personal information. We honour it${recorded ? " and have recorded it on your account as your opt-out" : ""}. Amber never sells or shares personal information anyway.`
            : "Your browser is not sending a Global Privacy Control signal. It makes no difference here: Amber never sells or shares your personal information."}
        </p>
      </div>
    </div>
  );
}

function download(data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `amber-my-data-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function DataRights() {
  const { signOut } = useSession();
  const [busy, setBusy] = useState(false);

  async function exportData() {
    setBusy(true);
    try {
      download(await apiFetch<DataExport>("/me/export", { quiet: true, cache: "no-store" }));
      toast("Your data is downloading", { description: "A JSON file with everything Amber stores about you." });
    } catch (e) {
      const code = e instanceof ApiError ? e.code : "";
      toast("Your data could not be exported", {
        description:
          code === "rate_limited"
            ? "You can export up to 10 times an hour. Please try again later."
            : code === "not_implemented"
              ? "Export is not available yet."
              : "Please try again in a moment.",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <div className="flex flex-col gap-3 rounded-lg border bg-background p-4">
        <div className="space-y-1 text-sm">
          <p className="font-medium">Download my data</p>
          <p className="text-muted-foreground">
            Everything Amber stores about you as one machine-readable JSON file: account, settings, consents, profile,
            chats, documents, findings, contributions and flags. Your ChatGPT tokens are never included.
          </p>
        </div>
        <Button variant="outline" size="lg" onClick={() => void exportData()} disabled={busy} className="mt-auto self-start" data-testid="export-data">
          {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Download aria-hidden />}
          Download my data
        </Button>
      </div>
      <div className="flex flex-col gap-3 rounded-lg border bg-background p-4">
        <div className="space-y-1 text-sm">
          <p className="font-medium">Delete my account</p>
          <p className="text-muted-foreground">
            Deletes your account and everything in it, and removes your contributions from the shared atlas. One
            confirmation, then you are signed out.
          </p>
        </div>
        <div className="mt-auto">
          <DeleteAccountButton />
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3 rounded-lg border bg-background p-4 text-sm lg:col-span-2">
        <p className="flex-1 text-muted-foreground">
          Other requests (for example through an authorised agent)? See{" "}
          <Link href="/privacy#rights" className="font-medium text-foreground underline underline-offset-2">
            your rights
          </Link>
          .
        </p>
        <Button variant="ghost" onClick={() => void signOut()}>
          <LogOut aria-hidden /> Sign out
        </Button>
      </div>
    </div>
  );
}
