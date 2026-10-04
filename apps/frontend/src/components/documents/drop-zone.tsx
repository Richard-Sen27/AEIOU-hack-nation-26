"use client";

import { FileUp, ShieldCheck } from "lucide-react";
import { useId, useRef, useState } from "react";

import { cn } from "@/lib/utils";

import { ACCEPT } from "./errors";

/**
 * Drop zone for PDF, image, DOCX or text. `onFiles` runs the consent gate
 * before anything is read or sent.
 */
export function DropZone({ onFiles, disabled }: { onFiles: (files: File[]) => void; disabled?: boolean }) {
  const inputId = useId();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  return (
    <div
      data-testid="drop-zone"
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        if (disabled) return;
        const files = Array.from(e.dataTransfer.files ?? []);
        if (files.length) onFiles(files);
      }}
      className={cn(
        "bg-atlas-grid relative flex flex-col items-center gap-4 rounded-xl border-2 border-dashed bg-card/60 px-5 py-10 text-center transition-colors sm:py-12",
        over ? "border-primary bg-primary/10" : "border-border",
        disabled && "opacity-60",
      )}
    >
      <span className="flex size-12 items-center justify-center rounded-xl bg-primary/15 text-primary">
        <FileUp className="size-6" aria-hidden />
      </span>
      <div className="space-y-1">
        <p className="text-base font-semibold tracking-tight">Drop a report here</p>
        <p className="text-sm text-muted-foreground">
          PDF, photo (PNG, JPEG, HEIC), Word (DOCX) or text · up to 20 MB and 30 pages
        </p>
      </div>
      <label
        htmlFor={inputId}
        className={cn(
          "inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/80",
          "has-focus-visible:ring-3 has-focus-visible:ring-ring/50",
          disabled && "pointer-events-none",
        )}
      >
        Choose a file
        <input
          ref={input}
          id={inputId}
          type="file"
          accept={ACCEPT}
          multiple
          disabled={disabled}
          className="sr-only"
          data-testid="file-input"
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            e.target.value = "";
            if (files.length) onFiles(files);
          }}
        />
      </label>
      <p className="flex max-w-md items-start gap-1.5 text-xs leading-relaxed text-muted-foreground">
        <ShieldCheck className="mt-px size-3.5 shrink-0 text-secondary" aria-hidden />
        Personal details removed before any AI sees it. File deleted after reading.
      </p>
    </div>
  );
}
