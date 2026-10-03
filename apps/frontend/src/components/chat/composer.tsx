"use client";

import { ArrowUp, FileUp, Square } from "lucide-react";
import { useId, useImperativeHandle, useRef, useState } from "react";

import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { UPLOAD_ACCEPT } from "@/components/landing/hero-input";
import { cn } from "@/lib/utils";

export type ComposerHandle = { fill: (text: string) => void; focus: () => void };

/** Message box with send / stop, report upload and the expert-mode switch. */
export function Composer({
  ref,
  streaming,
  expertMode,
  onExpertMode,
  onSend,
  onStop,
  onFiles,
}: {
  ref?: React.Ref<ComposerHandle>;
  streaming: boolean;
  expertMode: boolean;
  onExpertMode: (on: boolean) => void;
  onSend: (text: string) => void;
  onStop: () => void;
  onFiles: (files: FileList | null) => void;
}) {
  const [value, setValue] = useState("");
  const textRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const id = useId();

  useImperativeHandle(ref, () => ({
    fill: (t) => {
      setValue(t);
      textRef.current?.focus();
    },
    focus: () => textRef.current?.focus(),
  }));

  const submit = () => {
    const t = value.trim();
    if (!t || streaming) return;
    onSend(t);
    setValue("");
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="rounded-2xl border bg-card shadow-sm focus-within:border-ring/60 focus-within:ring-3 focus-within:ring-ring/20"
      data-testid="composer"
    >
      <label htmlFor={`${id}-msg`} className="sr-only">
        Message Dr. Wu
      </label>
      <textarea
        id={`${id}-msg`}
        ref={textRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
        rows={1}
        maxLength={4000}
        placeholder={expertMode ? "Ask about a mechanism, e.g. AAV gene replacement for loss of function" : "Ask Dr. Wu in your own words"}
        className="field-sizing-content block max-h-48 min-h-12 w-full resize-none bg-transparent px-4 pt-3 pb-1 text-base leading-relaxed outline-none placeholder:text-muted-foreground sm:text-[15px]"
      />
      <div className="flex items-center gap-1 px-2 pb-2">
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2 text-[13px] text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
        >
          <FileUp className="size-4" aria-hidden />
          <span className="hidden sm:inline">Add a report</span>
          <span className="sr-only sm:hidden">Add a report</span>
        </button>
        <input
          ref={fileRef}
          type="file"
          multiple
          accept={UPLOAD_ACCEPT}
          className="sr-only"
          tabIndex={-1}
          aria-hidden
          data-testid="chat-file-input"
          onChange={(e) => {
            onFiles(e.target.files);
            e.target.value = "";
          }}
        />
        <Tooltip>
          <TooltipTrigger
            render={<label htmlFor={`${id}-expert`} />}
            className="ml-1 inline-flex h-8 cursor-pointer items-center gap-2 rounded-lg px-2 text-[13px] text-muted-foreground hover:text-foreground"
          >
            Expert mode
          </TooltipTrigger>
          <TooltipContent className="max-w-64">
            Accepts mechanism questions and answers with ranked disease clusters and IDs. Open to everyone.
          </TooltipContent>
        </Tooltip>
        <Switch id={`${id}-expert`} checked={expertMode} onCheckedChange={(v) => onExpertMode(!!v)} data-testid="expert-mode" />
        {streaming ? (
          <button
            type="button"
            onClick={onStop}
            aria-label="Stop the answer"
            className="ml-auto flex size-9 items-center justify-center rounded-full bg-foreground text-background outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <Square className="size-3.5 fill-current" aria-hidden />
          </button>
        ) : (
          <button
            type="submit"
            disabled={!value.trim()}
            aria-label="Send"
            className={cn(
              "ml-auto flex size-9 items-center justify-center rounded-full bg-primary text-primary-foreground outline-none transition-colors hover:bg-primary/85 focus-visible:ring-3 focus-visible:ring-ring/50 disabled:bg-muted disabled:text-muted-foreground",
            )}
          >
            <ArrowUp className="size-4" aria-hidden />
          </button>
        )}
      </div>
    </form>
  );
}
