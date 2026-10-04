"use client";

import { ArrowUp, Bot, ChevronDown, CircleAlert, Clock, KeyRound, MessageSquareText, Phone, RotateCcw, Sparkles, Square, WifiOff, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState, useSyncExternalStore } from "react";
import { toast } from "sonner";

import { isEmergencyReply, type AssistantTurn, type PartialReply, type TurnError } from "@/components/chat/types";
import { useChat } from "@/components/chat/use-chat";
import { ContinueWithChatGPT } from "@/components/gates/continue-with-chatgpt";
import { useGate } from "@/components/providers/gate-provider";
import { useLens } from "@/components/providers/lens-provider";
import { useSession } from "@/components/providers/session-provider";
import { AiDisclosure } from "@/components/shell/ai-disclosure";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";
import { nodeTypeMeta } from "@/lib/graph/meta";
import { cn } from "@/lib/utils";

import type { AtlasSelect, AtlasWuDockProps, WuFound } from "./atlas-props";
import type { TreeIndex } from "./tree-model";

/*
 * Privacy (docs/compliance.md): what the user types and the ids Dr. Wu finds
 * from it are health data. They live in React state only: no URL, no
 * storage, no link that carries them (so no "Show in graph" / "Open in
 * Atlas" links from the chat's turn view here, only buttons).
 */

const MOBILE_QUERY = "(max-width: 767px)";

function useIsMobile() {
  return useSyncExternalStore(
    (cb) => {
      const m = window.matchMedia(MOBILE_QUERY);
      m.addEventListener("change", cb);
      return () => m.removeEventListener("change", cb);
    },
    () => window.matchMedia(MOBILE_QUERY).matches,
    () => false,
  );
}

/** Ids from a final reply that are entities on the map, deduplicated, in reply order. */
function collectFound(reply: PartialReply, index: TreeIndex): WuFound {
  const seen = new Set<string>();
  const nodeIds: string[] = [];
  const add = (id: string | null | undefined) => {
    if (!id || seen.has(id)) return;
    seen.add(id);
    if (index.nodes.get(id)?.kind === "entity") nodeIds.push(id);
  };
  reply.graph_focus?.node_ids.forEach(add);
  reply.cards.forEach((c) => c.node_ids.forEach(add));
  // Negated chips ("no feeding problems") are not something to find.
  reply.chips.forEach((c) => !c.negated && c.state !== "removed" && add(c.id));
  const edgeIds = (reply.graph_focus?.highlight_path ?? []).filter((id) => index.edges.has(id));
  return { nodeIds, edgeIds };
}

/** Dr. Wu dock: a floating card bottom-left of the Atlas canvas, a bottom Sheet on mobile. */
export function AtlasWuDock(props: AtlasWuDockProps) {
  const { user } = useSession();
  return user ? <SignedInDock {...props} /> : <GuestDock {...props} />;
}

// ---------------------------------------------------------------------------
// Frame: collapsed button, expanded card (desktop) or Sheet (mobile)

function DockFrame({
  open,
  onOpenChange,
  found,
  index,
  onClear,
  onSelect,
  className,
  body,
  footer,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  found: WuFound | null;
  index: TreeIndex;
  onClear: () => void;
  onSelect: AtlasSelect;
  className?: string;
  body: React.ReactNode;
  footer?: React.ReactNode;
}) {
  const mobile = useIsMobile();
  const count = found?.nodeIds.length ?? 0;
  const bodyId = useId();

  const header = (
    <div className="flex shrink-0 items-center gap-2 border-b px-3 py-2">
      <span className="flex size-7 items-center justify-center rounded-full bg-primary/15 text-primary">
        <Bot className="size-4" aria-hidden />
      </span>
      <h2 className="text-sm font-semibold">Dr. Wu</h2>
      <AiDisclosure variant="inline" />
      {!mobile && (
        <Button variant="ghost" size="icon-sm" className="ml-auto" onClick={() => onOpenChange(false)} aria-label="Collapse Dr. Wu">
          <ChevronDown aria-hidden />
        </Button>
      )}
    </div>
  );

  const content = (
    <>
      <div id={bodyId} className="min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain px-3 py-3" data-testid="atlas-wu-body">
        {count > 0 && <FoundList found={found!} index={index} onClear={onClear} onSelect={onSelect} />}
        {body}
      </div>
      {footer && <div className="shrink-0 border-t px-3 py-2.5">{footer}</div>}
    </>
  );

  const showCard = open && !mobile;

  return (
    <div className={cn("flex flex-col items-start gap-2", className)} data-testid="atlas-wu-dock" data-tour="wu" data-open={open || undefined}>
      {showCard ? (
        <section
          aria-label="Ask Dr. Wu"
          className="flex max-h-[min(34rem,calc(100dvh-12rem))] w-[min(22rem,calc(100vw-1.5rem))] flex-col overflow-hidden rounded-xl border bg-card/95 shadow-lg backdrop-blur"
        >
          {header}
          {content}
        </section>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            className="h-10 rounded-full bg-card/95 pr-4 pl-2 shadow-md backdrop-blur"
            onClick={() => onOpenChange(true)}
            aria-expanded={open}
            aria-controls={showCard ? bodyId : undefined}
            data-testid="atlas-wu-open"
          >
            <span className="flex size-7 items-center justify-center rounded-full bg-primary/15 text-primary">
              <Bot className="size-4" aria-hidden />
            </span>
            Ask Dr. Wu
          </Button>
          {count > 0 && !open && (
            <span
              className="inline-flex h-8 items-center gap-1 rounded-full border border-primary/40 bg-card/95 pr-1 pl-3 text-xs font-medium shadow-md backdrop-blur"
              data-testid="atlas-wu-found"
            >
              <button type="button" onClick={() => onOpenChange(true)} className="rounded outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring">
                Dr. Wu found {count}
              </button>
              <Button variant="ghost" size="icon-xs" className="rounded-full" onClick={onClear} aria-label="Clear what Dr. Wu found">
                <X aria-hidden />
              </Button>
            </span>
          )}
        </div>
      )}

      {mobile && (
        <Sheet open={open} onOpenChange={onOpenChange}>
          <SheetContent side="bottom" className="max-h-[85dvh] gap-0 rounded-t-2xl p-0" data-testid="atlas-wu-sheet">
            <SheetHeader className="sr-only">
              <SheetTitle>Ask Dr. Wu</SheetTitle>
              <SheetDescription>Describe the problem and Dr. Wu finds the matching dots on the map.</SheetDescription>
            </SheetHeader>
            {header}
            {content}
          </SheetContent>
        </Sheet>
      )}
    </div>
  );
}

function FoundList({
  found,
  index,
  onClear,
  onSelect,
}: {
  found: WuFound;
  index: TreeIndex;
  onClear: () => void;
  onSelect: AtlasSelect;
}) {
  const { labelStyle } = useLens();
  return (
    <section aria-labelledby="atlas-wu-found-title" className="rounded-lg border border-primary/40 bg-primary/5 p-2.5" data-testid="atlas-wu-found">
      <div className="mb-1.5 flex items-center gap-2">
        <Sparkles className="size-3.5 text-primary" aria-hidden />
        <h3 id="atlas-wu-found-title" className="flex-1 text-xs font-semibold">
          Dr. Wu found {found.nodeIds.length}
        </h3>
        <Button variant="ghost" size="xs" onClick={onClear} data-testid="atlas-wu-clear">
          <X aria-hidden /> Clear
        </Button>
      </div>
      <ul className="max-h-40 space-y-0.5 overflow-y-auto">
        {found.nodeIds.map((id) => {
          const n = index.nodes.get(id);
          const meta = nodeTypeMeta(n?.entity_type ?? "disease");
          const Icon = meta.icon;
          return (
            <li key={id}>
              <button
                type="button"
                onClick={() => onSelect(id, { center: true, persist: false })}
                className="flex w-full items-center gap-1.5 rounded px-1 py-1 text-left text-[13px] outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
                data-testid="atlas-wu-found-item"
              >
                <Icon className="size-3.5 shrink-0" style={{ color: `var(${meta.colorVar})` }} aria-hidden />
                <span className="min-w-0 flex-1 truncate">{n?.label ?? id}</span>
                <span className="sr-only">({meta.label[labelStyle]}). Show on the map</span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Guests: the sign-in offer

function GuestDock({ index, pendingQuestion, onPendingConsumed, found, onClear, onSelect, className }: AtlasWuDockProps) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (pendingQuestion == null) return;
    // Guests cannot ask yet; the text is dropped, never kept or stored.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- handover from the search bar
    setOpen(true);
    onPendingConsumed();
  }, [pendingQuestion, onPendingConsumed]);

  return (
    <DockFrame
      open={open}
      onOpenChange={setOpen}
      found={found}
      index={index}
      onClear={onClear}
      onSelect={onSelect}
      className={className}
      body={
        <div className="space-y-3" data-testid="atlas-wu-guest">
          <p className="text-sm leading-relaxed text-pretty">
            Tell Dr. Wu the problem in your own words, for example the symptoms and the family of conditions you
            suspect, and he finds the matching dots on the map.
          </p>
          <AiDisclosure />
          <p className="text-xs text-muted-foreground">
            Dr. Wu runs on your own ChatGPT plan, so he needs you to sign in.
          </p>
          <ContinueWithChatGPT className="w-full" />
          <p className="text-[11px] text-muted-foreground">
            You must be 16 or older. Nothing is sold or shared.{" "}
            <Link href="/privacy" className="underline underline-offset-2">
              Privacy notice
            </Link>
          </p>
        </div>
      }
    />
  );
}

// ---------------------------------------------------------------------------
// Signed in: compact composer and the last turn

function SignedInDock({
  index,
  pendingQuestion,
  onPendingConsumed,
  found,
  onFound,
  onClear,
  onSelect,
  className,
}: AtlasWuDockProps) {
  const { user } = useSession();
  const { role } = useLens();
  const { requireConsent } = useGate();
  const chat = useChat({ expertMode: !!user?.expert_mode || role === "researcher" });
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const boxRef = useRef<HTMLTextAreaElement>(null);
  const language = user?.language || undefined;

  // Question handed over from the search bar: into the box, not sent.
  useEffect(() => {
    if (pendingQuestion == null) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- handover from the search bar
    setOpen(true);
    setDraft(pendingQuestion);
    onPendingConsumed();
    requestAnimationFrame(() => boxRef.current?.focus());
  }, [pendingQuestion, onPendingConsumed]);

  // The first message is the first use of health information: ask for the
  // health-data consent just in time. Declining sends nothing and keeps the text.
  const { send } = chat;
  const gatedSend = useCallback(
    async (text: string) => {
      if (await requireConsent("health_data", "Dr. Wu needs your consent to use the health information you share.")) {
        send(text);
        return;
      }
      setDraft(text);
      toast("Nothing was sent", { description: "Your message is still in the box." });
    },
    [requireConsent, send],
  );

  // Report the finds of each new final reply (in state only, owned by the view).
  const lastTurn = chat.turns[chat.turns.length - 1];
  const lastAssistant = lastTurn?.kind === "assistant" ? lastTurn : null;
  const lastUser = [...chat.turns].reverse().find((t) => t.kind === "user");
  const reported = useRef<PartialReply | null>(null);
  const [lastCount, setLastCount] = useState<number | null>(null);
  useEffect(() => {
    if (!lastAssistant || !lastAssistant.final || lastAssistant.phase !== "done") return;
    if (reported.current === lastAssistant.reply) return;
    reported.current = lastAssistant.reply;
    const next = isEmergencyReply(lastAssistant) ? { nodeIds: [], edgeIds: [] } : collectFound(lastAssistant.reply, index);
    setLastCount(next.nodeIds.length);
    if (next.nodeIds.length > 0) onFound(next);
    else onClear();
  }, [lastAssistant, index, onFound, onClear]);

  const submit = () => {
    const text = draft.trim();
    if (!text || chat.streaming) return;
    setDraft("");
    void gatedSend(text);
  };

  return (
    <DockFrame
      open={open}
      onOpenChange={setOpen}
      found={found}
      index={index}
      onClear={onClear}
      onSelect={onSelect}
      className={className}
      body={
        <div className="space-y-3" data-testid="atlas-wu-chat">
          {!lastAssistant ? (
            <>
              <p className="text-sm leading-relaxed text-pretty">
                Describe the problem in your own words, for example &ldquo;I have these symptoms and I think it is a
                condition from this family&rdquo;. Dr. Wu finds the matching dots on the map.
              </p>
              <AiDisclosure className="text-xs" />
            </>
          ) : (
            <>
              {lastUser && lastUser.kind === "user" && (
                <p className="line-clamp-2 rounded-xl rounded-br-md bg-secondary px-3 py-1.5 text-[13px] text-secondary-foreground" dir="auto" data-testid="atlas-wu-question">
                  <span className="sr-only">You: </span>
                  {lastUser.text}
                </p>
              )}
              <CompactTurn
                turn={lastAssistant}
                language={language}
                foundCount={lastCount}
                onRetry={() => chat.retry(lastAssistant.id)}
              />
            </>
          )}
        </div>
      }
      footer={
        <div className="space-y-2">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
            className="flex items-end gap-1.5 rounded-xl border bg-background focus-within:border-ring/60 focus-within:ring-3 focus-within:ring-ring/20"
            data-testid="atlas-wu-composer"
          >
            <label htmlFor="atlas-wu-message" className="sr-only">
              Message Dr. Wu
            </label>
            <textarea
              id="atlas-wu-message"
              ref={boxRef}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  submit();
                }
              }}
              rows={1}
              maxLength={4000}
              placeholder="Symptoms, a gene, a family of conditions…"
              className="field-sizing-content block max-h-28 min-h-10 flex-1 resize-none bg-transparent px-3 py-2 text-base leading-snug outline-none placeholder:text-muted-foreground sm:text-sm"
            />
            {chat.streaming ? (
              <button
                type="button"
                onClick={chat.stop}
                aria-label="Stop the answer"
                className="m-1 flex size-8 shrink-0 items-center justify-center rounded-full bg-foreground text-background outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                <Square className="size-3 fill-current" aria-hidden />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!draft.trim()}
                aria-label="Send"
                className="m-1 flex size-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground outline-none transition-colors hover:bg-primary/85 focus-visible:ring-3 focus-visible:ring-ring/50 disabled:bg-muted disabled:text-muted-foreground"
              >
                <ArrowUp className="size-4" aria-hidden />
              </button>
            )}
          </form>
          <div className="flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
            <span>Information, not medical advice.</span>
            <Link href="/chat" className="inline-flex items-center gap-1 font-medium text-foreground underline-offset-2 hover:underline" data-testid="atlas-wu-full">
              <MessageSquareText className="size-3.5" aria-hidden /> Open full conversation
            </Link>
          </div>
        </div>
      }
    />
  );
}

const ERROR_COPY: Record<string, { icon: typeof CircleAlert; title: string; hint: string; retry: boolean }> = {
  rate_limited: {
    icon: Clock,
    title: "Your ChatGPT plan's usage limit is reached",
    hint: "Dr. Wu runs on your own ChatGPT plan. Try again when your plan allows more requests.",
    retry: true,
  },
  reauth_required: { icon: KeyRound, title: "Please sign in again", hint: "Your ChatGPT sign-in has expired.", retry: false },
  sign_in_required: { icon: KeyRound, title: "Please sign in again", hint: "Your session has ended.", retry: false },
  timeout: { icon: Clock, title: "Dr. Wu took too long to answer", hint: "What arrived so far is kept. You can try again.", retry: true },
  network_error: { icon: WifiOff, title: "The connection dropped", hint: "What arrived before the drop is kept. You can try again.", retry: true },
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
  return ERROR_COPY[err.code] ?? { icon: CircleAlert, title: "Dr. Wu could not finish this answer", hint: "You can try again.", retry: true };
}

/** The last reply, compact: progress, uncertainty, summary, error. Same wording as the chat. */
function CompactTurn({
  turn,
  language,
  foundCount,
  onRetry,
}: {
  turn: AssistantTurn;
  language?: string;
  foundCount: number | null;
  onRetry: () => void;
}) {
  const { openSignIn } = useGate();
  const r = turn.reply;
  const streaming = turn.phase === "streaming";
  const emergency = isEmergencyReply(turn);
  const lastStatus = turn.statuses[turn.statuses.length - 1];

  return (
    <article className="space-y-2.5" aria-label="Dr. Wu's reply" aria-busy={streaming} data-testid="atlas-wu-turn" data-phase={turn.phase}>
      {streaming && !r.summary && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="status-line">
          <Spinner className="size-3.5" /> {lastStatus?.message ?? "Reading your message…"}
        </p>
      )}

      {emergency ? (
        <div role="alert" className="rounded-lg border-2 border-destructive bg-destructive/10 p-3" data-testid="emergency">
          <p className="flex items-center gap-2 font-semibold text-destructive">
            <Phone className="size-4" aria-hidden /> Call emergency services now
          </p>
          <p className="mt-1.5 text-sm leading-relaxed" dir="auto" lang={language}>
            {r.summary}
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            In Europe dial <strong className="text-foreground">112</strong>, in the US and Canada{" "}
            <strong className="text-foreground">911</strong>. Dr. Wu is not able to help in an emergency.
          </p>
        </div>
      ) : (
        <>
          {r.uncertainty && (
            <p className="rounded-lg border border-status-flag/60 bg-status-flag/10 px-2.5 py-1.5 text-xs" dir="auto" data-testid="uncertainty">
              <span className="sr-only">Uncertain: </span>
              {r.uncertainty}
            </p>
          )}
          {r.summary && (
            <p className="text-sm leading-relaxed text-pretty" dir="auto" lang={language} data-testid="summary">
              {r.summary}
              {streaming && <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-primary align-middle motion-reduce:animate-none" aria-hidden />}
            </p>
          )}
          {turn.final && foundCount === 0 && (
            <p className="text-xs text-muted-foreground" data-testid="atlas-wu-none">
              No dots on the map match this answer.
            </p>
          )}
          {turn.final && r.chips.some((c) => c.state === "pending") && (
            <p className="text-xs text-muted-foreground">
              Open the full conversation to confirm what Dr. Wu understood before anything is saved.
            </p>
          )}
        </>
      )}

      {turn.phase === "stopped" && (
        <p className="text-xs text-muted-foreground" data-testid="stopped">
          You stopped this answer.
        </p>
      )}
      {turn.phase === "error" && turn.error && (
        <ErrorNotice error={turn.error} onRetry={onRetry} onSignIn={() => openSignIn("Sign in again to continue the conversation with Dr. Wu.")} />
      )}
    </article>
  );
}

function ErrorNotice({ error, onRetry, onSignIn }: { error: TurnError; onRetry: () => void; onSignIn: () => void }) {
  const copy = errorCopy(error);
  const Icon = copy.icon;
  const signIn = error.code === "reauth_required" || error.code === "sign_in_required";
  return (
    <div role="alert" className="space-y-2 rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2.5 text-sm" data-testid="turn-error" data-code={error.code}>
      <p className="flex items-start gap-2 font-medium">
        <Icon className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
        {copy.title}
      </p>
      <p className="text-xs text-muted-foreground">
        {error.message && error.message !== copy.title ? `${error.message} ` : ""}
        {copy.hint}
      </p>
      {signIn ? (
        <Button size="sm" onClick={onSignIn}>
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
