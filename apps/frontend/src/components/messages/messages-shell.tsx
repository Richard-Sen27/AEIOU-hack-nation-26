"use client";

import { MessageSquare, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import { SessionLoading, SignInPrompt } from "@/components/account/sign-in-prompt";
import { useSession } from "@/components/providers/session-provider";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { listThreads, type Schemas } from "@/lib/api";
import { cn } from "@/lib/utils";

import { useConnectFlow } from "./connect-flow";
import { counterpartName, formatWhen, statusLabel, type Thread } from "./labels";
import { publishMessageCounts } from "./use-message-count";

const LIST_POLL_MS = 30_000;

type MessagesContextValue = {
  list: Schemas.ThreadList | null;
  reload: () => Promise<void>;
  flow: ReturnType<typeof useConnectFlow>;
};

const MessagesContext = createContext<MessagesContextValue | null>(null);

export function useMessages() {
  const ctx = useContext(MessagesContext);
  if (!ctx) throw new Error("useMessages must be used inside <MessagesShell>");
  return ctx;
}

/** `/messages` and `/messages/<id>`: the list beside the conversation (desktop), one after the other (phone). */
export function MessagesShell({ children }: { children: React.ReactNode }) {
  const { user, status } = useSession();
  if (status === "loading") {
    return (
      <div className="mx-auto w-full max-w-[1280px] px-4 py-8 sm:px-6">
        <SessionLoading />
      </div>
    );
  }
  if (!user) {
    return (
      <div className="mx-auto w-full max-w-[1280px] px-4 py-8 sm:px-6">
        <SignInPrompt title="Sign in to see your messages" description="Conversations with doctors and researchers." returnTo="/messages" />
      </div>
    );
  }
  return <Shell>{children}</Shell>;
}

function Shell({ children }: { children: React.ReactNode }) {
  const params = useParams<{ id?: string }>();
  const selected = params?.id ?? null;
  const flow = useConnectFlow();
  const [list, setList] = useState<Schemas.ThreadList | null>(null);
  const [failed, setFailed] = useState(false);
  const last = useRef(0);
  const { load } = flow;

  const reload = useCallback(async () => {
    last.current = Date.now();
    const { data } = await listThreads({ meta: { quiet: true }, cache: "no-store" });
    if (data) {
      setList(data);
      setFailed(false);
      publishMessageCounts({ count: data.unread_total, requests: data.requests_waiting });
    } else setFailed(true);
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch, state set after await
    void reload();
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible" && Date.now() - last.current > 5_000) void reload();
    }, LIST_POLL_MS);
    return () => window.clearInterval(timer);
  }, [reload, load]);

  const value = useMemo(() => ({ list, reload, flow }), [list, reload, flow]);

  return (
    <MessagesContext.Provider value={value}>
      <div className="mx-auto flex min-h-0 w-full max-w-[1280px] flex-1 gap-6 px-3 sm:px-6" data-fit-viewport data-testid="messages">
        <aside
          className={cn("min-h-0 w-full flex-col py-4 lg:flex lg:w-80 lg:shrink-0", selected ? "hidden" : "flex")}
          aria-labelledby="messages-title"
          data-testid="thread-list-pane"
        >
          <h1 id="messages-title" className="px-1 pb-3 text-lg font-semibold tracking-tight sm:text-xl">
            Messages
          </h1>
          <ThreadList list={list} failed={failed} selected={selected} onRetry={() => void reload()} />
        </aside>
        <section
          className={cn("min-h-0 min-w-0 flex-1 flex-col lg:flex lg:border-l lg:pl-6", selected ? "flex" : "hidden")}
          data-testid="thread-pane"
        >
          {children}
        </section>
      </div>
      {flow.dialog}
    </MessagesContext.Provider>
  );
}

function ThreadList({
  list,
  failed,
  selected,
  onRetry,
}: {
  list: Schemas.ThreadList | null;
  failed: boolean;
  selected: string | null;
  onRetry: () => void;
}) {
  const { user } = useSession();
  if (!list) {
    if (failed) {
      return (
        <div className="space-y-2 px-1 text-sm text-muted-foreground">
          <p>Messages could not be loaded.</p>
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RefreshCw aria-hidden /> Try again
          </Button>
        </div>
      );
    }
    return (
      <div className="space-y-2" aria-busy="true" aria-label="Loading">
        <Skeleton className="h-14 w-full" />
        <Skeleton className="h-14 w-full" />
      </div>
    );
  }
  if (!list.items.length) {
    return (
      <p className="px-1 text-sm text-muted-foreground" data-testid="threads-empty">
        No conversations yet.
        {user?.role === "patient" && <> Write to a doctor or researcher from their card in the Atlas.</>}
      </p>
    );
  }
  const requests = list.items.filter((t) => t.can_respond);
  const rest = list.items.filter((t) => !t.can_respond);
  return (
    <div className="-mx-1 min-h-0 flex-1 space-y-4 overflow-y-auto px-1 pb-4" data-testid="thread-list">
      {requests.length > 0 && <Group title="Requests" items={requests} selected={selected} testId="requests" />}
      {rest.length > 0 && <Group title={requests.length ? "Conversations" : null} items={rest} selected={selected} testId="conversations" />}
    </div>
  );
}

function Group({ title, items, selected, testId }: { title: string | null; items: Thread[]; selected: string | null; testId: string }) {
  return (
    <section aria-label={title ?? "Conversations"} data-testid={`thread-group-${testId}`}>
      {title && <h2 className="px-2 pb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">{title}</h2>}
      <ul className="space-y-0.5">
        {items.map((t) => (
          <li key={t.id}>
            <ThreadRow t={t} active={t.id === selected} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function ThreadRow({ t, active }: { t: Thread; active: boolean }) {
  const label = statusLabel(t);
  const unread = t.unread_count > 0;
  return (
    <Link
      href={`/messages/${t.id}`}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex items-center gap-3 rounded-lg px-2 py-2.5 outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring",
        active && "bg-accent text-accent-foreground hover:bg-accent",
      )}
      data-testid="thread-row"
      data-status={t.status}
    >
      <span
        className={cn(
          "flex size-9 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground",
          t.counterpart.is_professional && "bg-primary/15 text-primary",
          t.counterpart.deleted && "opacity-60",
        )}
        aria-hidden
      >
        <MessageSquare className="size-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline gap-2">
          <span className={cn("truncate text-sm", unread ? "font-semibold" : "font-medium", t.counterpart.deleted && "text-muted-foreground italic")}>
            {counterpartName(t)}
          </span>
          <span className="ml-auto shrink-0 text-xs text-muted-foreground tabular">{formatWhen(t.last_message_at ?? t.created_at)}</span>
        </span>
        <span className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
          {label ? (
            <span className={cn(t.can_respond && "font-medium text-primary")} data-testid="thread-status">
              {label}
            </span>
          ) : (
            <span>{t.counterpart.is_professional ? "Doctor or researcher" : "Patient or family"}</span>
          )}
          {unread && (
            <span
              className="ml-auto flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 font-mono text-[10px] leading-none font-semibold text-primary-foreground tabular"
              data-testid="thread-unread"
            >
              <span className="sr-only">Unread: </span>
              {t.unread_count > 9 ? "9+" : t.unread_count}
            </span>
          )}
        </span>
      </span>
    </Link>
  );
}

/** Desktop placeholder beside the list when no conversation is open. */
export function NoThreadSelected() {
  return (
    <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground" data-testid="no-thread">
      Select a conversation.
    </div>
  );
}
