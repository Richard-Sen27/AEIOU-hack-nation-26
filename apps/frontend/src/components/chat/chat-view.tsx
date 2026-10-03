"use client";

import { Bot, FileUp, History } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { useGate } from "@/components/providers/gate-provider";
import { useLens } from "@/components/providers/lens-provider";
import { useSession } from "@/components/providers/session-provider";
import { AiDisclosure } from "@/components/shell/ai-disclosure";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";
import { setPendingUploads, takePendingChatMessage } from "@/lib/handoff";

import { AssistantTurnView } from "./assistant-turn";
import { Composer, type ComposerHandle } from "./composer";
import { SessionList } from "./session-list";
import { useChat } from "./use-chat";

const STARTERS = [
  "My son has Dravet syndrome. Which other conditions share the same cause?",
  "What registries or natural history studies exist for STXBP1?",
  "Who studies SCN2A loss of function?",
];

/** Signed-in chat with Dr. Wu: sessions, the conversation, and the composer. */
export function ChatView() {
  const router = useRouter();
  const { user } = useSession();
  const { role } = useLens();
  const { requireConsent } = useGate();
  const [expertMode, setExpertMode] = useState<boolean>(() => !!user?.expert_mode || role === "researcher");
  const chat = useChat({ expertMode });
  const composer = useRef<ComposerHandle>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const dragDepth = useRef(0);
  const language = user?.language || undefined;

  // Free text handed over from the landing page (in memory only).
  const tookPending = useRef(false);
  const { send } = chat;
  // The first message is the first use of health information: ask for the
  // health-data consent just in time. Declining sends nothing and keeps the text.
  const gatedSend = useCallback(
    async (text: string) => {
      if (await requireConsent("health_data", "Dr. Wu needs your consent to use the health information you share.")) {
        send(text);
        return;
      }
      composer.current?.fill(text);
      toast("Nothing was sent", { description: "Your message is still in the box." });
    },
    [requireConsent, send],
  );
  useEffect(() => {
    if (tookPending.current) return;
    tookPending.current = true;
    const text = takePendingChatMessage();
    if (text) void gatedSend(text);
  }, [gatedSend]);

  // Keep the newest content in view while the user is near the bottom.
  const lastTurn = chat.turns[chat.turns.length - 1];
  useEffect(() => {
    const el = logRef.current;
    if (!el) return;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 240) el.scrollTop = el.scrollHeight;
  }, [lastTurn]);

  async function handleFiles(list: FileList | null) {
    const files = list ? Array.from(list) : [];
    if (!files.length) return;
    const ok = await requireConsent("health_data", "Reading a report needs your consent.");
    if (!ok) {
      toast("Nothing was uploaded", { description: "You can add a report any time from Documents." });
      return;
    }
    setPendingUploads(files);
    router.push("/documents");
  }

  const sessionList = (
    <SessionList
      status={chat.sessions.status}
      items={chat.sessions.items}
      activeId={chat.sessionId}
      disabled={chat.streaming}
      onNew={() => {
        chat.newConversation();
        setSheetOpen(false);
        composer.current?.focus();
      }}
      onOpen={(id) => {
        void chat.openSession(id);
        setSheetOpen(false);
      }}
      onDelete={(id) => void chat.deleteSession(id)}
    />
  );

  return (
    <div className="mx-auto flex h-[calc(100dvh-57px)] w-full max-w-[1280px] gap-6 px-3 sm:px-6">
      <aside className="hidden w-64 shrink-0 py-6 lg:block">{sessionList}</aside>

      <section
        className="relative flex min-w-0 flex-1 flex-col"
        aria-labelledby="chat-title"
        onDragEnter={(e) => {
          if (!e.dataTransfer.types.includes("Files")) return;
          dragDepth.current += 1;
          setDragging(true);
        }}
        onDragOver={(e) => e.dataTransfer.types.includes("Files") && e.preventDefault()}
        onDragLeave={() => {
          dragDepth.current = Math.max(0, dragDepth.current - 1);
          if (!dragDepth.current) setDragging(false);
        }}
        onDrop={(e) => {
          if (!e.dataTransfer.files.length) return;
          e.preventDefault();
          dragDepth.current = 0;
          setDragging(false);
          void handleFiles(e.dataTransfer.files);
        }}
        data-testid="chat-drop-zone"
        data-dragging={dragging || undefined}
      >
        <div className="flex items-center gap-2 pt-4 pb-3">
          <h1 id="chat-title" className="text-lg font-semibold tracking-tight sm:text-xl">
            Ask Dr. Wu
          </h1>
          <Button variant="ghost" size="sm" className="ml-auto lg:hidden" onClick={() => setSheetOpen(true)}>
            <History aria-hidden /> Conversations
          </Button>
        </div>
        <AiDisclosure className="hidden sm:flex" />
        <AiDisclosure variant="inline" className="self-start sm:hidden" />

        <div ref={logRef} className="-mx-1 min-h-0 flex-1 overflow-y-auto px-1 py-5" data-testid="chat-log">
          {chat.loadingSession ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Spinner className="size-4" /> Opening the conversation…
            </p>
          ) : chat.turns.length === 0 ? (
            <div className="mx-auto max-w-xl py-6 text-center sm:py-10">
              <span className="mx-auto flex size-11 items-center justify-center rounded-full bg-primary/15 text-primary">
                <Bot className="size-5" aria-hidden />
              </span>
              <p className="mt-4 text-lg font-medium text-balance">
                Tell me about the diagnosis, a gene or the symptoms, in your own words.
              </p>
              <p className="mt-2 text-sm text-muted-foreground text-pretty">
                I answer only from cited sources in the atlas. You confirm what I understood before
                anything is saved, and I never give a diagnosis or treatment advice.
              </p>
              <ul className="mt-5 flex flex-col gap-2">
                {STARTERS.map((s) => (
                  <li key={s}>
                    <button
                      type="button"
                      onClick={() => composer.current?.fill(s)}
                      className="w-full rounded-xl border bg-card px-3.5 py-2.5 text-left text-sm outline-none transition-colors hover:border-primary/50 focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      {s}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <ol className="mx-auto max-w-3xl space-y-8" aria-label="Conversation">
              {chat.turns.map((t, i) =>
                t.kind === "user" ? (
                  <li key={t.id} className="flex justify-end">
                    <p
                      className="max-w-[85%] rounded-2xl rounded-br-md bg-secondary px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap text-secondary-foreground"
                      dir="auto"
                      data-testid="user-message"
                    >
                      <span className="sr-only">You: </span>
                      {t.text}
                    </p>
                  </li>
                ) : (
                  <li key={t.id}>
                    <AssistantTurnView
                      turn={t}
                      isLatest={i === chat.turns.length - 1}
                      language={language}
                      onRetry={() => chat.retry(t.id)}
                      onSend={(text) => void gatedSend(text)}
                      onSkipFollowUp={() => chat.dismissFollowUp(t.id)}
                      onConfirmChip={(ci) => void chat.confirmChip(t.id, ci)}
                      onRemoveChip={(ci) => void chat.removeChip(t.id, ci)}
                      onUndoChip={(ci) => chat.undoRemove(t.id, ci)}
                      onCorrectChip={(ci, hit) => void chat.correctChip(t.id, ci, hit)}
                      onConfirmHint={(k) => void chat.confirmHint(t.id, k)}
                      onDismissHint={(k) => chat.dismissHint(t.id, k)}
                      showChildOffer={chat.profileAboutChild === false}
                      onConfirmChild={() => chat.markAboutChild(t.id)}
                      onDismissChild={() => chat.dismissChildOffer(t.id)}
                    />
                  </li>
                ),
              )}
            </ol>
          )}
        </div>

        <div className="mx-auto w-full max-w-3xl pb-4">
          <Composer
            ref={composer}
            streaming={chat.streaming}
            expertMode={expertMode}
            onExpertMode={setExpertMode}
            onSend={(text) => void gatedSend(text)}
            onStop={chat.stop}
            onFiles={(f) => void handleFiles(f)}
          />
          <p className="mt-1.5 px-1 text-[11px] text-muted-foreground">
            Information, not medical advice. Please don&apos;t include names, birth dates or addresses.
          </p>
        </div>

        {dragging && (
          <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-2xl border-2 border-dashed border-primary bg-background/90" aria-hidden>
            <p className="flex items-center gap-2 text-sm font-medium">
              <FileUp className="size-5 text-primary" /> Drop a report to read its findings
            </p>
          </div>
        )}
      </section>

      <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
        <SheetContent side="left" className="w-80 p-4">
          <SheetHeader className="p-0">
            <SheetTitle>Conversations</SheetTitle>
          </SheetHeader>
          {sessionList}
        </SheetContent>
      </Sheet>
    </div>
  );
}
