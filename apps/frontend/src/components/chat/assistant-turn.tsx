"use client";

import {
  Bot,
  Check,
  ChevronDown,
  CircleAlert,
  Clock,
  KeyRound,
  Map as MapIcon,
  Phone,
  RotateCcw,
  Route,
  TriangleAlert,
  WifiOff,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { useGate } from "@/components/providers/gate-provider";
import { AiDisclosure } from "@/components/shell/ai-disclosure";
import { Button, buttonVariants } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import type { SearchHit } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { Actions } from "./actions";
import { Cards } from "./cards";
import { Chips } from "./chips";
import { Claims } from "./claims";
import { FollowUpQuestion } from "./follow-up";
import { isEmergencyReply, type AssistantTurn as Turn, type TurnError } from "./types";

function StatusLines({ turn }: { turn: Turn }) {
  const [open, setOpen] = useState(false);
  const { statuses } = turn;
  const working = turn.phase === "streaming";
  if (statuses.length === 0) {
    return working && !turn.reply.summary ? (
      <p className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="status-line">
        <Spinner className="size-3.5" /> Reading your message…
      </p>
    ) : null;
  }
  if (working) {
    return (
      <ol className="space-y-1" aria-label="What Dr. Wu is doing" data-testid="status-lines">
        {statuses.map((s, i) => {
          const last = i === statuses.length - 1;
          return (
            <li key={i} className={cn("flex items-center gap-2 text-sm", last ? "text-foreground" : "text-muted-foreground")} data-testid="status-line">
              {last ? <Spinner className="size-3.5" /> : <Check className="size-3.5 text-confidence-high" aria-hidden />}
              <span>{s.message}</span>
              {s.tool && <span className="font-mono text-[10.5px] text-muted-foreground">{s.tool}</span>}
            </li>
          );
        })}
      </ol>
    );
  }
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1 rounded text-xs text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ChevronDown className={cn("size-3.5 transition-transform motion-reduce:transition-none", open && "rotate-180")} aria-hidden />
        Checked the atlas in {statuses.length} step{statuses.length === 1 ? "" : "s"}
      </button>
      {open && (
        <ol className="mt-1 space-y-0.5 pl-5 text-xs text-muted-foreground">
          {statuses.map((s, i) => (
            <li key={i}>
              {s.message}
              {s.tool && <span className="ml-1.5 font-mono">{s.tool}</span>}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

const ERROR_COPY: Record<string, { icon: typeof CircleAlert; title: string; hint: string; retry: boolean }> = {
  rate_limited: {
    icon: Clock,
    title: "Your ChatGPT plan's usage limit is reached",
    hint: "Dr. Wu runs on your own ChatGPT plan. Try again when your plan allows more requests.",
    retry: true,
  },
  reauth_required: {
    icon: KeyRound,
    title: "Please sign in again",
    hint: "Your ChatGPT sign-in has expired.",
    retry: false,
  },
  sign_in_required: { icon: KeyRound, title: "Please sign in again", hint: "Your session has ended.", retry: false },
  timeout: {
    icon: Clock,
    title: "Dr. Wu took too long to answer",
    hint: "What arrived so far is kept. You can try again.",
    retry: true,
  },
  network_error: {
    icon: WifiOff,
    title: "The connection dropped",
    hint: "What arrived before the drop is kept. You can try again.",
    retry: true,
  },
  not_implemented: {
    icon: CircleAlert,
    title: "Dr. Wu is not available yet",
    hint: "This part of Amber is still being built. You can keep exploring the atlas.",
    retry: true,
  },
};

function errorCopy(err: TurnError) {
  if (err.code === "upstream_error" && /usage|quota|limit/i.test(err.message)) return ERROR_COPY.rate_limited;
  if (err.code === "upstream_error" && /time/i.test(err.message)) return ERROR_COPY.timeout;
  return (
    ERROR_COPY[err.code] ?? {
      icon: CircleAlert,
      title: "Dr. Wu could not finish this answer",
      hint: "You can try again.",
      retry: true,
    }
  );
}

function TurnErrorNotice({ error, onRetry }: { error: TurnError; onRetry: () => void }) {
  const { openSignIn } = useGate();
  const copy = errorCopy(error);
  const Icon = copy.icon;
  const signIn = error.code === "reauth_required" || error.code === "sign_in_required";
  return (
    <div role="alert" className="flex flex-col gap-2 rounded-lg border border-destructive/40 bg-destructive/5 px-3.5 py-3 sm:flex-row sm:items-center" data-testid="turn-error" data-code={error.code}>
      <Icon className="size-4 shrink-0 text-destructive" aria-hidden />
      <div className="flex-1 text-sm">
        <p className="font-medium">{copy.title}</p>
        <p className="text-muted-foreground">
          {error.message && error.message !== copy.title ? `${error.message} ` : ""}
          {copy.hint}
        </p>
      </div>
      {signIn ? (
        <Button size="sm" onClick={() => openSignIn("Sign in again to continue the conversation with Dr. Wu.")}>
          Sign in again
        </Button>
      ) : (
        copy.retry && (
          <Button size="sm" variant="outline" onClick={onRetry}>
            <RotateCcw aria-hidden /> Try again
          </Button>
        )
      )}
    </div>
  );
}

function EmergencyReply({ summary, language }: { summary: string; language?: string }) {
  return (
    <div role="alert" className="rounded-xl border-2 border-destructive bg-destructive/10 p-4 sm:p-5" data-testid="emergency">
      <p className="flex items-center gap-2 text-lg font-semibold text-destructive">
        <Phone className="size-5" aria-hidden /> Call emergency services now
      </p>
      <p className="mt-2 text-[15px] leading-relaxed" dir="auto" lang={language}>
        {summary}
      </p>
      <p className="mt-3 text-sm text-muted-foreground">
        In Europe dial <strong className="text-foreground">112</strong>, in the US and Canada{" "}
        <strong className="text-foreground">911</strong>. Dr. Wu is not able to help in an emergency.
      </p>
    </div>
  );
}

export function AssistantTurnView({
  turn,
  isLatest,
  language,
  onRetry,
  onSend,
  onSkipFollowUp,
  onConfirmChip,
  onRemoveChip,
  onUndoChip,
  onCorrectChip,
}: {
  turn: Turn;
  isLatest: boolean;
  language?: string;
  onRetry: () => void;
  onSend: (text: string) => void;
  onSkipFollowUp: () => void;
  onConfirmChip: (i: number) => void;
  onRemoveChip: (i: number) => void;
  onUndoChip: (i: number) => void;
  onCorrectChip: (i: number, hit: SearchHit) => void;
}) {
  const r = turn.reply;
  const streaming = turn.phase === "streaming";
  const emergency = isEmergencyReply(turn);
  const focus = r.graph_focus;
  const focusHref = focus?.node_ids.length
    ? `/atlas?focus=${encodeURIComponent(focus.node_ids[0])}${focus.highlight_path.length ? `&path=${encodeURIComponent(focus.highlight_path.join(","))}` : ""}`
    : null;
  const gap = r.gap_search;

  return (
    <article
      className="space-y-3.5"
      aria-label="Dr. Wu's reply"
      aria-busy={streaming}
      data-testid="assistant-turn"
      data-phase={turn.phase}
    >
      <header className="flex flex-wrap items-center gap-2">
        <span className="flex size-7 items-center justify-center rounded-full bg-primary/15 text-primary">
          <Bot className="size-4" aria-hidden />
        </span>
        <span className="text-sm font-semibold">Dr. Wu</span>
        <AiDisclosure variant="inline" />
        {r.ai_notice && <span className="text-xs text-muted-foreground" data-testid="ai-notice">{r.ai_notice}</span>}
      </header>

      <div className="space-y-3.5 sm:pl-9">
        <StatusLines turn={turn} />

        {emergency ? (
          <EmergencyReply summary={r.summary} language={language} />
        ) : (
          <>
            {r.uncertainty && (
              <p className="flex items-start gap-2 rounded-lg border border-status-flag/60 bg-status-flag/10 px-3 py-2 text-sm" data-testid="uncertainty" dir="auto">
                <TriangleAlert className="mt-0.5 size-4 shrink-0 text-status-flag" aria-hidden />
                <span>
                  <span className="sr-only">Uncertain: </span>
                  {r.uncertainty}
                </span>
              </p>
            )}

            {r.summary && (
              <p className="text-[16px] leading-relaxed text-pretty" dir="auto" lang={language} data-testid="summary">
                {r.summary}
                {streaming && <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-primary align-middle motion-reduce:animate-none" aria-hidden />}
              </p>
            )}

            <Chips chips={r.chips} onConfirm={onConfirmChip} onRemove={onRemoveChip} onUndo={onUndoChip} onCorrect={onCorrectChip} />
            <Claims reply={r} />
            <Cards cards={r.cards} />
            <Actions actions={r.actions} edgeIds={focus?.highlight_path ?? []} language={language} />

            {(focusHref || gap) && (
              <div className="flex flex-wrap gap-2">
                {focusHref && (
                  <Link href={focusHref} className={cn(buttonVariants({ variant: "outline", size: "sm" }))} data-testid="show-in-graph">
                    <MapIcon aria-hidden /> Show in graph
                  </Link>
                )}
                {gap && (
                  <Link
                    href={`/path?from=${encodeURIComponent(gap.from_id)}&to=${encodeURIComponent(gap.to_id)}`}
                    className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
                    data-testid="gap-search-link"
                  >
                    <Route aria-hidden /> Search for the missing evidence
                  </Link>
                )}
              </div>
            )}

            {r.follow_up && (
              <FollowUpQuestion
                followUp={r.follow_up}
                active={isLatest && !turn.followUpDone && !streaming}
                onReply={onSend}
                onSkip={onSkipFollowUp}
              />
            )}
          </>
        )}

        {turn.phase === "stopped" && <p className="text-xs text-muted-foreground" data-testid="stopped">You stopped this answer.</p>}
        {turn.phase === "error" && turn.error && <TurnErrorNotice error={turn.error} onRetry={onRetry} />}
      </div>
    </article>
  );
}
