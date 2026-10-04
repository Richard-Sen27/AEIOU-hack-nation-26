"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";

import { useSession } from "@/components/providers/session-provider";
import { trackEvent } from "@/lib/analytics";
import { followDisease, followProfileDiseases, listFollows, unfollowDisease, type Schemas } from "@/lib/api";
import type { ApiError } from "@/lib/api/errors";

type Follow = Schemas.Follow;
type FromProfile = Schemas.FollowFromProfileResult;

type State = {
  /** The user the list belongs to; null for guests and accounts without the age check. */
  userId: string | null;
  status: "idle" | "loading" | "ready" | "error";
  items: Follow[];
  limit: number;
};

const EMPTY: State = { userId: null, status: "idle", items: [], limit: 50 };

// In memory only: which diseases a user follows is health data, never in browser storage.
let state: State = EMPTY;
let mutations = 0;
const listeners = new Set<() => void>();

function set(next: Partial<State>) {
  state = { ...state, ...next };
  listeners.forEach((l) => l());
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => listeners.delete(l);
}

const snapshot = () => state;

async function load(userId: string) {
  const startedAt = mutations;
  set({ userId, status: "loading", items: [] });
  const { data } = await listFollows({ meta: { quiet: true }, cache: "no-store" });
  if (state.userId !== userId) return;
  // A follow or unfollow landed while the list was loading: fetch again.
  if (mutations !== startedAt) return void load(userId);
  set(data ? { status: "ready", items: data.items, limit: data.limit } : { status: "error" });
}

export type FollowResult = { ok: true } | { ok: false; error: ApiError };

/** The signed-in user's followed diseases, shared by every Follow toggle and the profile. */
export function useFollows() {
  const { user } = useSession();
  const snap = useSyncExternalStore(subscribe, snapshot, snapshot);
  const userId = user?.age_confirmed ? user.id : null;

  useEffect(() => {
    if (!userId) {
      if (state.userId !== null) set(EMPTY);
      return;
    }
    if (state.userId !== userId) void load(userId);
  }, [userId]);

  const current = snap.userId === userId ? snap : EMPTY;

  const follow = useCallback(async (nodeId: string): Promise<FollowResult> => {
    mutations++;
    const { data, error } = await followDisease({ body: { node_id: nodeId }, meta: { quiet: true } });
    if (!data) return { ok: false, error: error as unknown as ApiError };
    set({ items: [data, ...state.items.filter((f) => f.node_id !== nodeId)] });
    trackEvent("follow", { source: "disease" });
    return { ok: true };
  }, []);

  const unfollow = useCallback(async (nodeId: string): Promise<FollowResult> => {
    mutations++;
    const { error } = await unfollowDisease({ body: { node_id: nodeId }, meta: { quiet: true } });
    if (error) return { ok: false, error: error as unknown as ApiError };
    set({ items: state.items.filter((f) => f.node_id !== nodeId) });
    trackEvent("unfollow");
    return { ok: true };
  }, []);

  const followFromProfile = useCallback(async (): Promise<{ ok: true; result: FromProfile } | { ok: false; error: ApiError }> => {
    mutations++;
    const { data, error } = await followProfileDiseases({ meta: { quiet: true } });
    if (!data) return { ok: false, error: error as unknown as ApiError };
    const added = new Set(data.added.map((f) => f.node_id));
    set({ items: [...data.added, ...state.items.filter((f) => !added.has(f.node_id))] });
    trackEvent("follow", { source: "profile" });
    return { ok: true, result: data };
  }, []);

  const get = useCallback((nodeId: string) => current.items.find((f) => f.node_id === nodeId), [current.items]);

  return { ...current, get, follow, unfollow, followFromProfile };
}

/** Short error line for a failed follow, unfollow or profile follow. */
export function followErrorText(error: ApiError | undefined, limit = 50): string {
  switch (error?.code) {
    case "conflict":
      return `You can follow up to ${limit} diseases.`;
    case "not_found":
      return "Not a disease in the atlas.";
    case "network_error":
      return "Server unreachable.";
    case "rate_limited":
      return "Too many requests. Try again shortly.";
    default:
      return error?.status === 409 ? `You can follow up to ${limit} diseases.` : "Couldn't save. Try again.";
  }
}
