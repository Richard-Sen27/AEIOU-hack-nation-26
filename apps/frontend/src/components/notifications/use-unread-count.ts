"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useSession } from "@/components/providers/session-provider";
import { getUnreadNotificationCount } from "@/lib/api";
import { backgroundPaused } from "@/lib/api/errors";

const POLL_MS = 60_000;
/** A focus and a visibility change often arrive together: one request for both. */
const MIN_GAP_MS = 2_000;

/**
 * Unread notifications for the signed-in user. Polled every 60 s while the tab
 * is visible, and on focus; never for guests or before the 16+ confirmation
 * (the routes answer 403 until then), and not while a 429 asks to wait.
 */
export function useUnreadCount() {
  const { user } = useSession();
  const enabled = !!user?.age_confirmed;
  const userId = enabled ? user.id : null;
  const [count, setCount] = useState(0);
  const last = useRef(0);

  const refresh = useCallback(async () => {
    last.current = Date.now();
    const { data } = await getUnreadNotificationCount({ meta: { quiet: true }, cache: "no-store" });
    if (data) setCount(data.count);
  }, []);

  useEffect(() => {
    if (!userId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- signed out
      setCount(0);
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

  return { enabled, count, setCount, refresh };
}
