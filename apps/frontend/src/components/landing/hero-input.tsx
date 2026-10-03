"use client";

import { ArrowUp, Bot, FileUp, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useId, useImperativeHandle, useRef, useState } from "react";
import { toast } from "sonner";

import { needsOnboarding } from "@/components/account/onboarding";
import { ACCEPT } from "@/components/documents/errors";
import { useGate } from "@/components/providers/gate-provider";
import { useSession } from "@/components/providers/session-provider";
import { useSearch } from "@/components/search/search-provider";
import { Spinner } from "@/components/ui/spinner";
import { announce } from "@/lib/a11y";
import type { SearchHit } from "@/lib/api/types";
import { setPendingChatMessage, setPendingUploads } from "@/lib/handoff";
import { isEntityQuery, searchEntities } from "@/lib/search";
import { cn } from "@/lib/utils";

export const HERO_PROMPT =
  "Tell us about the diagnosis, a gene, or the symptoms, in your own words. Or drop a report here.";

/** Same list as the documents page, so every drop zone accepts what the API accepts. */
export const UPLOAD_ACCEPT = ACCEPT;

const EXAMPLES = ["STXBP1", "Dravet syndrome", "Infantile spasms"];

const GUEST_REASON =
  "Dr. Wu answers questions in your own words. What you typed has not been sent or saved anywhere, so after signing in you will need to type it again.";

export type HeroInputHandle = { focus: () => void; fill: (text: string) => void };

/** Pick the hit that matches what was typed, else the best-ranked one. */
function bestHit(hits: SearchHit[], q: string): SearchHit | undefined {
  const t = q.trim().toLowerCase();
  return (
    hits.find((h) => h.label.toLowerCase() === t || h.matched_synonym?.toLowerCase() === t) ?? hits[0]
  );
}

/**
 * The landing input (system spec, "Chat-based input"). Names search the atlas
 * and open the node; sentences go to Dr. Wu (signed in) or offer sign-in
 * (guests, nothing is sent). Dropped files go through the health-data consent gate
 * to the documents flow. Typed text never enters a URL or browser storage.
 */
export function HeroInput({ ref }: { ref?: React.Ref<HeroInputHandle> }) {
  const router = useRouter();
  const { openSearch } = useSearch();
  const { user } = useSession();
  const { requireSignIn, requireConsent } = useGate();
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);
  const hintId = useId();

  useImperativeHandle(ref, () => ({
    focus: () => textareaRef.current?.focus(),
    fill: (text: string) => {
      setValue(text);
      textareaRef.current?.focus();
    },
  }));

  // A search in flight is abandoned if the user leaves.
  const ctrlRef = useRef<AbortController | null>(null);
  useEffect(() => () => ctrlRef.current?.abort(), []);

  const trimmed = value.trim();
  const mode: "empty" | "search" | "assistant" = !trimmed ? "empty" : isEntityQuery(trimmed) ? "search" : "assistant";

  async function submit() {
    if (!trimmed || busy) return;
    if (mode === "search") {
      ctrlRef.current?.abort();
      const ctrl = new AbortController();
      ctrlRef.current = ctrl;
      setBusy(true);
      try {
        const hits = await searchEntities(trimmed, ctrl.signal);
        const hit = bestHit(hits, trimmed);
        if (hit) {
          announce(`Opening ${hit.label}`);
          router.push(`/node/${encodeURIComponent(hit.id)}`);
        } else {
          openSearch(trimmed);
        }
      } catch (e) {
        if ((e as { code?: string }).code !== "aborted") openSearch(trimmed);
      } finally {
        setBusy(false);
      }
      return;
    }
    if (!user) {
      await requireSignIn(GUEST_REASON, "/chat");
      return;
    }
    setPendingChatMessage(trimmed);
    setValue("");
    router.push("/chat");
  }

  async function handleFiles(list: FileList | null) {
    const files = list ? Array.from(list) : [];
    if (files.length === 0) return;
    if (needsOnboarding(user)) {
      // A first sign-in passes the welcome step before anything else; the
      // documents page asks for consent once it is back (files kept in memory).
      setPendingUploads(files);
      router.push("/documents");
      return;
    }
    const ok = await requireConsent(
      "health_data",
      user
        ? "Reading a report needs your consent."
        : "Reading a report needs an account and your consent. The report has not been uploaded or kept, so after signing in please add it again.",
    );
    if (!ok) {
      if (user) toast("Nothing was uploaded", { description: "You can add a report any time from Documents." });
      return;
    }
    setPendingUploads(files);
    router.push("/documents");
  }

  const hint =
    mode === "empty" ? (
      <>Type a name to search the atlas, or a few sentences for Dr. Wu, our AI assistant.</>
    ) : mode === "search" ? (
      <>
        <Search className="size-3.5 shrink-0 text-primary" aria-hidden />
        <span>
          Searches the atlas for <span className="font-medium text-foreground">this name</span>.
        </span>
      </>
    ) : user ? (
      <>
        <Bot className="size-3.5 shrink-0 text-primary" aria-hidden />
        <span>Goes to Dr. Wu, an AI assistant, running on your ChatGPT plan.</span>
      </>
    ) : (
      <>
        <Bot className="size-3.5 shrink-0 text-primary" aria-hidden />
        <span>
          Sentences are answered by Dr. Wu, an AI assistant that needs sign-in. Nothing is sent
          until you do.
        </span>
      </>
    );

  return (
    <div className="mx-auto w-full max-w-2xl text-left">
      <form
        data-testid="hero-input"
        data-dragging={dragging || undefined}
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
        onDragEnter={(e) => {
          if (!e.dataTransfer.types.includes("Files")) return;
          dragDepth.current += 1;
          setDragging(true);
        }}
        onDragOver={(e) => {
          if (e.dataTransfer.types.includes("Files")) e.preventDefault();
        }}
        onDragLeave={() => {
          dragDepth.current = Math.max(0, dragDepth.current - 1);
          if (dragDepth.current === 0) setDragging(false);
        }}
        onDrop={(e) => {
          if (!e.dataTransfer.files.length) return;
          e.preventDefault();
          dragDepth.current = 0;
          setDragging(false);
          void handleFiles(e.dataTransfer.files);
        }}
        className={cn(
          "relative rounded-2xl border bg-card shadow-lg shadow-primary/5 transition-[box-shadow,border-color] focus-within:border-ring/60 focus-within:ring-3 focus-within:ring-ring/25",
          dragging && "border-primary border-dashed ring-3 ring-primary/30",
        )}
      >
        <label htmlFor={`${hintId}-input`} className="sr-only">
          Describe the diagnosis, a gene or the symptoms in your own words, or search the atlas by name
        </label>
        <textarea
          id={`${hintId}-input`}
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              void submit();
            }
          }}
          rows={2}
          maxLength={4000}
          placeholder={HERO_PROMPT}
          aria-describedby={`${hintId}-hint`}
          autoComplete="off"
          spellCheck
          // Browser extensions (writing and autofill helpers) inject a caret-color
          // style into text fields before hydration; that is not our markup.
          suppressHydrationWarning
          className="field-sizing-content block max-h-64 min-h-[5.5rem] w-full resize-none rounded-2xl bg-transparent px-5 pt-4 pb-2 text-base leading-relaxed text-foreground outline-none placeholder:text-muted-foreground sm:text-[17px]"
        />
        <div className="flex items-center gap-2 px-3 pb-3">
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2 text-[13px] text-muted-foreground outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          >
            <FileUp className="size-4" aria-hidden />
            <span>Add a report</span>
          </button>
          <input
            ref={fileRef}
            type="file"
            multiple
            accept={UPLOAD_ACCEPT}
            className="sr-only"
            tabIndex={-1}
            aria-hidden
            data-testid="hero-file-input"
            onChange={(e) => {
              void handleFiles(e.target.files);
              e.target.value = "";
            }}
          />
          <button
            type="submit"
            disabled={!trimmed || busy}
            aria-label={mode === "search" ? "Search the atlas" : "Send to Dr. Wu"}
            className="ml-auto flex size-9 items-center justify-center rounded-full bg-primary text-primary-foreground outline-none transition-colors hover:bg-primary/85 focus-visible:ring-3 focus-visible:ring-ring/50 disabled:bg-muted disabled:text-muted-foreground"
          >
            {busy ? <Spinner className="size-4" /> : mode === "search" ? <Search className="size-4" aria-hidden /> : <ArrowUp className="size-4" aria-hidden />}
          </button>
        </div>
        {dragging && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center rounded-2xl bg-card/90 text-sm font-medium" aria-hidden>
            <FileUp className="mr-2 size-4 text-primary" /> Drop the report to read it
          </div>
        )}
      </form>
      <p
        id={`${hintId}-hint`}
        aria-live="polite"
        className="mt-2.5 flex min-h-5 items-start gap-1.5 px-1 text-[13px] leading-snug text-muted-foreground"
        data-testid="hero-hint"
        data-mode={mode}
      >
        {hint}
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-1.5 px-1 text-[13px] text-muted-foreground">
        <span>Try</span>
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            type="button"
            onClick={() => {
              setValue(ex);
              textareaRef.current?.focus();
            }}
            className="rounded-full border bg-card/70 px-2.5 py-0.5 text-foreground outline-none transition-colors hover:border-primary/50 hover:bg-card focus-visible:ring-2 focus-visible:ring-ring"
          >
            {ex}
          </button>
        ))}
      </div>
    </div>
  );
}
