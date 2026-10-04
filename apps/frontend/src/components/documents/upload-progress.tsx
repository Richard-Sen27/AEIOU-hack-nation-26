"use client";

import { ArrowRight, Check, CircleAlert, Loader2, X } from "lucide-react";
import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import { Button } from "@/components/ui/button";
import { LimitContact } from "@/components/ui/limit-notice";
import { cn } from "@/lib/utils";

import type { UploadItem } from "./use-uploads";

/** The real job stages, in order (GET /jobs/{id} → JobStage). */
export const STAGES = [
  { id: "uploading", label: "Uploading", hint: "Sending the file securely" },
  { id: "extracting_text", label: "Reading text", hint: "Text extraction on our server" },
  { id: "redacting", label: "Removing personal details", hint: "Names, birth dates, addresses, patient IDs" },
  { id: "classifying", label: "Recognising the document type", hint: "Genetic report, letter, paper or registry" },
  { id: "extracting_findings", label: "Finding results", hint: "Diagnoses, genes, variants, symptoms" },
] as const;

function stageIndex(stage: UploadItem["stage"]): number {
  if (stage === "uploading") return 0;
  if (stage === "queued") return 1;
  if (stage === "done") return STAGES.length;
  return STAGES.findIndex((s) => s.id === stage);
}

function formatSize(bytes: number) {
  return bytes > 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export function UploadProgress({ item, onDismiss }: { item: UploadItem; onDismiss: () => void }) {
  const current = stageIndex(item.stage);
  const failed = item.status === "failed";
  const done = item.status === "done";

  return (
    <li
      className={cn("space-y-4 rounded-xl border bg-card p-4 sm:p-5", failed && "border-destructive/50")}
      data-testid="upload-item"
      data-status={item.status}
      aria-busy={!done && !failed}
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium" title={item.name}>
            {item.name}
          </p>
          <p className="text-xs text-muted-foreground">
            {formatSize(item.size)}
            {done && " · original file deleted"}
          </p>
        </div>
        {(done || failed) && (
          <Button variant="ghost" size="icon-sm" onClick={onDismiss} aria-label="Dismiss">
            <X aria-hidden />
          </Button>
        )}
      </div>

      {!failed && (
        <>
          <div
            role="progressbar"
            aria-label="Reading the document"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(item.percent)}
            className="h-1.5 overflow-hidden rounded-full bg-muted"
          >
            <div className="h-full rounded-full bg-primary transition-[width] duration-500" style={{ width: `${item.percent}%` }} />
          </div>
          <ol className="grid gap-2 sm:grid-cols-5" aria-label="Steps">
            {STAGES.map((s, i) => {
              const state = i < current ? "done" : i === current ? "active" : "todo";
              return (
                <li key={s.id} className="flex items-start gap-2 text-xs sm:flex-col sm:gap-1.5" data-state={state} data-stage={s.id}>
                  <span
                    className={cn(
                      "flex size-5 shrink-0 items-center justify-center rounded-full border",
                      state === "done" && "border-secondary bg-secondary text-secondary-foreground",
                      state === "active" && "border-primary text-primary",
                      state === "todo" && "text-muted-foreground",
                    )}
                    aria-hidden
                  >
                    {state === "done" ? <Check className="size-3" /> : state === "active" ? <Loader2 className="size-3 animate-spin" /> : null}
                  </span>
                  <span>
                    <span className={cn("block font-medium", state === "todo" && "text-muted-foreground")}>
                      {s.label}
                      <span className="sr-only">{state === "done" ? " (done)" : state === "active" ? " (in progress)" : ""}</span>
                    </span>
                    <span className="block text-muted-foreground">{s.hint}</span>
                  </span>
                </li>
              );
            })}
          </ol>
        </>
      )}

      {failed && item.error && (
        <p role="alert" className="flex items-start gap-2 text-sm text-destructive" data-testid="upload-error" data-code={item.error.code}>
          <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>
            {item.error.message}
            <LimitContact info={item.error.limit} />
          </span>
        </p>
      )}

      {done && item.documentId && (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
          <p className="text-sm">
            {item.findingCount
              ? `${item.findingCount} ${item.findingCount === 1 ? "finding" : "findings"} to review. Nothing is used until you confirm it.`
              : "No findings were extracted from this document."}
          </p>
          <Link href={`/documents/${item.documentId}`} className={cn(buttonVariants({ size: "lg" }), "px-4")}>
            Review findings <ArrowRight data-icon="inline-end" aria-hidden />
          </Link>
        </div>
      )}
    </li>
  );
}
