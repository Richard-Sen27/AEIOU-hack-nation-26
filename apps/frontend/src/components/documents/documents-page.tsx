"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { routeGlobalError } from "@/components/account/api-errors";
import { SessionLoading, SignInPrompt } from "@/components/account/sign-in-prompt";
import { useGate } from "@/components/providers/gate-provider";
import { needsOnboarding } from "@/components/account/onboarding";
import { useSession } from "@/components/providers/session-provider";
import { listDocuments, unwrap } from "@/lib/api";
import type { Document } from "@/lib/api/generated/types.gen";
import { takePendingUploads } from "@/lib/handoff";

import { DocumentList } from "./document-list";
import { DropZone } from "./drop-zone";
import { UPLOADS_PER_HOUR } from "./errors";
import { UploadProgress } from "./upload-progress";
import { useUploads } from "./use-uploads";

const STEPS = [
  ["Upload", "To Amber's own server only."],
  ["Personal details removed", "Names, birth dates, addresses and IDs, before any AI sees the text."],
  ["Original deleted", "Right after the text is read."],
  ["You review", "Only what you confirm goes into your profile."],
] as const;

export function DocumentsPage() {
  const { user, status } = useSession();
  const { requireConsent } = useGate();
  const [documents, setDocuments] = useState<Document[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const uploadsRef = useRef<HTMLElement>(null);

  const loadDocuments = useCallback(async () => {
    try {
      setDocuments(await unwrap(listDocuments({ meta: { quiet: true }, cache: "no-store" })));
      setListError(null);
    } catch (e) {
      const err = routeGlobalError(e);
      setListError(
        err?.code === "not_implemented"
          ? "Your documents list is not available yet."
          : err?.code === "network_error"
            ? "Amber's server is not reachable, so your documents cannot be listed right now."
            : "Your documents could not be loaded.",
      );
    }
  }, []);

  const { items, add, dismiss } = useUploads({ onDone: () => void loadDocuments() });

  const handleFiles = useCallback(
    async (files: File[]) => {
      if (await requireConsent("health_data", "Uploading a report needs an account.")) add(files);
    },
    [add, requireConsent],
  );

  // Bring a new upload's progress into view.
  const count = items.length;
  useEffect(() => {
    if (count > 0) uploadsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [count]);

  // Files handed over from the landing page or chat (in memory only). Taken
  // only once the account may upload: a first sign-in passes the welcome step
  // first, and the files must survive that detour.
  useEffect(() => {
    if (status === "loading" || !user || needsOnboarding(user)) return;
    const files = takePendingUploads();
    if (files.length) void handleFiles(files);
  }, [status, user, handleFiles]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on sign-in, state set after await
    if (user) void loadDocuments();
  }, [user, loadDocuments]);

  if (status === "loading") return <SessionLoading />;
  if (!user) {
    return (
      <SignInPrompt
        title="Sign in to upload a report"
        description="Reading reports uses AI. The atlas stays open to everyone."
        returnTo="/documents"
      />
    );
  }

  return (
    <div className="space-y-10">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <DropZone onFiles={(f) => void handleFiles(f)} />
        <aside aria-labelledby="how-h" className="rounded-xl border bg-card p-5">
          <h2 id="how-h" className="text-sm font-semibold">
            What happens to your file
          </h2>
          <ol className="mt-3 space-y-3">
            {STEPS.map(([title, body], i) => (
              <li key={title} className="flex gap-3 text-sm">
                <span className="flex size-5 shrink-0 items-center justify-center rounded-full border font-mono text-[10.5px] text-muted-foreground">
                  {i + 1}
                </span>
                <span>
                  <span className="block font-medium">{title}</span>
                  <span className="block text-muted-foreground">{body}</span>
                </span>
              </li>
            ))}
          </ol>
          <p className="mt-4 border-t pt-3 text-xs text-muted-foreground">
            Up to {UPLOADS_PER_HOUR} uploads per hour.{" "}
            <Link href="/privacy#health-data" className="underline underline-offset-2 hover:text-foreground">
              How we handle health data
            </Link>
          </p>
        </aside>
      </div>

      {items.length > 0 && (
        <section ref={uploadsRef} aria-labelledby="uploads-h" className="scroll-mt-20 space-y-3">
          <h2 id="uploads-h" className="text-lg font-semibold tracking-tight">
            Reading your {items.length === 1 ? "document" : "documents"}
          </h2>
          <ul className="space-y-3" aria-live="polite">
            {items.map((it) => (
              <UploadProgress key={it.key} item={it} onDismiss={() => dismiss(it.key)} />
            ))}
          </ul>
        </section>
      )}

      <section aria-labelledby="docs-h" className="space-y-3">
        <div>
          <h2 id="docs-h" className="text-lg font-semibold tracking-tight">
            Your documents
          </h2>
          <p className="text-sm text-muted-foreground">
            Findings only, never the file. Deleting a document deletes its findings.
          </p>
        </div>
        <DocumentList documents={documents} error={listError} onChanged={() => void loadDocuments()} />
      </section>
    </div>
  );
}
