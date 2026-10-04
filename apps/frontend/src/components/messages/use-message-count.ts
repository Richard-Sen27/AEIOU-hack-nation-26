"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useSession } from "@/components/providers/session-provider";
import { getMessageUnreadCount } from "@/lib/api";
import { backgroundPaused } from "@/lib/api/errors";

const POLL_MS = 60_000;
const MIN_GAP_MS = 2_000;

type Counts = { count: number; requests: number };
const ZERO: Counts = { count: 0, requests: 0 };

// The Messages page knows the counts first (it just read a conversation): it
// pushes them here so the header updates without waiting for the next poll.
const listeners = new Set<(c: Counts) => void>();
export function publishMessageCounts(counts: Counts) {
  listeners.forEach((l) => l(counts));
}

/**
 * Unread messages and waiting requests for the header. Polled every 60 s while
 * the tab is visible, and on focus; never for guests or before the 16+
 * confirmation (the routes answer 403 until then), not while a 429 asks to
 * wait. Only counts, never content.
 */
export function useMessageCount() {
  const { user } = useSession();
  const enabled = !!user?.age_confirmed;
  const userId = enabled ? user.id : null;
  const [counts, setCounts] = useState<Counts>(ZERO);
  const last = useRef(0);

  const refresh = useCallback(async () => {
    last.current = Date.now();
    const { data } = await getMessageUnreadCount({ meta: { quiet: true }, cache: "no-store" });
    if (data) setCounts({ count: data.count, requests: data.requests_waiting });
  }, []);

  useEffect(() => {
    listeners.add(setCounts);
    return () => {
      listeners.delete(setCounts);
    };
  }, []);

  useEffect(() => {
    if (!userId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- signed out
      setCounts(ZERO);
      return;
    }
    let timer: number | undefined;
    const visible = () => document.visibilityState === "visible";
    const tick = () => {
      if (visible() && !backgroundPaused() && Date.now() - last.current >= MIN_GAP_MS) void refresh();
    };
    const stop = () => {
      if (timer !== undefined) window.clearInterval(timer);
      timer = undefined;
    };
    const start = () => {
      stop();
      timer = window.setInterval(tick, POLL_MS);
    };
    const onVisibility = () => {
      if (visible()) {
        tick();
        start();
      } else stop();
    };
    if (visible()) {
      last.current = 0;
      tick();
      start();
    }
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("focus", tick);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("focus", tick);
    };
  }, [userId, refresh]);

  return { enabled, ...counts, refresh };
}
