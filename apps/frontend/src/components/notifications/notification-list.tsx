"use client";

import { RefreshCw, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { listNotifications, markNotificationsRead, type Schemas } from "@/lib/api";
import { cn } from "@/lib/utils";

type Notification = Schemas.Notification;

const ITEM_NAME: Record<string, string> = {
  paper: "paper",
  trial: "trial",
  grant: "grant",
  patient_org: "patient group",
};

/**
 * One line from the fields. A paper is "added to the atlas" with its year,
 * never "just published": the year is when it was published, not when it was found.
 */
export function notificationText(n: Notification): string {
  const disease = n.disease_label ?? n.disease_id ?? "a followed disease";
  if (n.kind === "now_recruiting") {
    return ["New trial recruiting", disease, n.registry_id ?? n.item_label].filter(Boolean).join(" · ");
  }
  const name = (n.item_type && ITEM_NAME[n.item_type]) || "item";
  const what = n.item_type === "paper" && n.year ? `paper (${n.year})` : name;
  const parts = ["Added to the atlas", what, disease];
  if (n.item_type === "trial" && n.registry_id) parts.push(n.registry_id);
  return parts.join(" · ");
}

type Load = { kind: "loading" } | { kind: "ready"; items: Notification[] } | { kind: "error" };

/** The newest notifications, loaded when opened. Clicking one opens its node page and marks it read. */
export function NotificationList({
  onCount,
  onNavigate,
  showTitle = true,
  className,
}: {
  onCount: (count: number) => void;
  onNavigate?: () => void;
  /** False where the opener already says "Notifications" (the phone menu). */
  showTitle?: boolean;
  className?: string;
}) {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let alive = true;
    listNotifications({ meta: { quiet: true }, cache: "no-store" }).then(({ data }) => {
      if (!alive) return;
      if (!data) return setLoad({ kind: "error" });
      const items = [...data.items].sort((a, b) => b.created_at.localeCompare(a.created_at));
      setLoad({ kind: "ready", items });
      onCount(data.unread_count);
    });
    return () => {
      alive = false;
    };
    // onCount is a state setter from the header.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt]);

  const items = load.kind === "ready" ? load.items : [];
  const unread = items.filter((n) => !n.read_at).length;

  const markRead = useCallback(
    async (body: Schemas.MarkRead) => {
      const now = new Date().toISOString();
      const ids = body.ids ? new Set(body.ids) : null;
      setLoad((l) =>
        l.kind === "ready" ? { ...l, items: l.items.map((n) => (!n.read_at && (!ids || ids.has(n.id)) ? { ...n, read_at: now } : n)) } : l,
      );
      const { data } = await markNotificationsRead({ body, meta: { quiet: true } });
      if (data) onCount(data.count);
    },
    [onCount],
  );

  return (
    <div className={cn("flex min-h-0 flex-col", className)} data-testid="notifications">
      <div className={cn("flex items-center gap-2 px-1 pb-1.5", showTitle ? "justify-between" : "justify-end")}>
        {showTitle && <h2 className="text-sm font-semibold">Notifications</h2>}
        <Button
          variant="ghost"
          size="xs"
          disabled={unread === 0}
          onClick={() => void markRead({ all: true })}
          data-testid="notifications-mark-all"
        >
          Mark all read
        </Button>
      </div>

      {load.kind === "loading" && (
        <div className="space-y-1.5 px-1" role="status" aria-label="Loading notifications">
          <Skeleton className="h-7 w-full" />
          <Skeleton className="h-7 w-full" />
        </div>
      )}

      {load.kind === "error" && (
        <div className="flex items-center gap-2 px-1 py-1 text-sm" role="alert" data-testid="notifications-error">
          <TriangleAlert className="size-4 shrink-0 text-status-flag" aria-hidden />
          <p className="flex-1">Couldn&apos;t load.</p>
          <Button variant="outline" size="xs" onClick={() => (setLoad({ kind: "loading" }), setAttempt((a) => a + 1))}>
            <RefreshCw aria-hidden /> Retry
          </Button>
        </div>
      )}

      {load.kind === "ready" && items.length === 0 && (
        <p className="px-1 py-2 text-sm text-muted-foreground" data-testid="notifications-empty">
          Nothing new yet.
        </p>
      )}

      {items.length > 0 && (
        <ul className="-mx-1 max-h-80 overflow-y-auto overscroll-contain" data-testid="notifications-list">
          {items.map((n) => {
            const text = notificationText(n);
            const dot = (
              <span
                className={cn("size-1.5 shrink-0 rounded-full", n.read_at ? "bg-transparent" : "bg-primary")}
                aria-hidden
              />
            );
            const label = (
              <>
                {dot}
                <span className="min-w-0 flex-1 truncate">{text}</span>
                {!n.read_at && <span className="sr-only">(unread)</span>}
              </>
            );
            const row = cn("flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px]", !n.read_at && "font-medium");
            return (
              <li key={n.id} data-testid="notification" data-read={n.read_at ? "true" : "false"} data-gone={n.gone || undefined} title={text}>
                {n.gone ? (
                  <div className={cn(row, "text-muted-foreground")}>
                    {label}
                    <span className="shrink-0 text-[11px]">No longer in the atlas</span>
                  </div>
                ) : (
                  <Link
                    href={`/node/${encodeURIComponent(n.item_id)}`}
                    onClick={() => {
                      if (!n.read_at) void markRead({ ids: [n.id] });
                      onNavigate?.();
                    }}
                    className={cn(row, "outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring")}
                  >
                    {label}
                  </Link>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
