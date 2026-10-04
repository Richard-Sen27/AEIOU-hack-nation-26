"use client";

import { useEffect, useState } from "react";

import { routeGlobalError } from "@/components/account/api-errors";
import { useSession } from "@/components/providers/session-provider";
import { listCalls } from "@/lib/api";
import type { ApiError } from "@/lib/api/errors";

import type { Call } from "./call-meta";

export type PublishedCalls =
  | { kind: "guest" }
  | { kind: "loading" }
  | { kind: "ready"; heading: string; items: Call[] }
  | { kind: "error"; error: ApiError | null };

// Published calls are the same for every signed-in user (no health data), so
// one in-memory copy serves the list, the node page and the card page.
const TTL_MS = 60_000;
let cache: { userId: string; at: number; promise: Promise<{ heading: string; items: Call[] }> } | null = null;

function fetchCalls(userId: string) {
  if (cache && cache.userId === userId && Date.now() - cache.at < TTL_MS) return cache.promise;
  // Never a disease parameter: the disease filter runs here, in the browser.
  const promise = listCalls({ meta: { quiet: true }, cache: "no-store" }).then(({ data, error }) => {
    if (error !== undefined || !data) throw error;
    return { heading: data.heading ?? "", items: data.items };
  });
  cache = { userId, at: Date.now(), promise };
  promise.catch(() => {
    if (cache?.promise === promise) cache = null;
  });
  return promise;
}

/** Drop the cached list (after the user's own call changed). */
export function invalidatePublishedCalls() {
  cache = null;
}

/** Every published, open call, for signed-in users with the age check; `guest` otherwise. */
export function usePublishedCalls({ silent = false }: { silent?: boolean } = {}): PublishedCalls & { retry: () => void } {
  const { user, status } = useSession();
  // Without the age check the API answers 403 and the global handler sends the
  // user to /welcome; `silent` sections simply wait for it.
  const userId = user && (user.age_confirmed || !silent) ? user.id : null;
  const [state, setState] = useState<PublishedCalls>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!userId) return;
    let live = true;
    fetchCalls(userId).then(
      (data) => live && setState({ kind: "ready", ...data }),
      (e) => {
        if (!live) return;
        // `silent` sections (node page, card page) never open the global dialogs.
        const err = silent ? ((e as ApiError) ?? null) : routeGlobalError(e);
        setState({ kind: "error", error: err });
      },
    );
    return () => {
      live = false;
    };
  }, [userId, attempt, silent]);

  const retry = () => {
    cache = null;
    setState({ kind: "loading" });
    setAttempt((a) => a + 1);
  };

  if (status === "loading") return { kind: "loading", retry };
  if (!user) return { kind: "guest", retry };
  if (!userId) return { kind: "loading", retry };
  return { ...state, retry };
}
