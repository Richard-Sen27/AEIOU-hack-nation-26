"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";

import { useSession } from "@/components/providers/session-provider";
import { getMyCard, type Schemas } from "@/lib/api";
import type { ApiError } from "@/lib/api/errors";

type MyCard = Schemas.MyCard;

type State = {
  userId: string | null;
  status: "idle" | "loading" | "ready" | "error";
  card: MyCard | null;
  error: ApiError | null;
};

const EMPTY: State = { userId: null, status: "idle", card: null, error: null };

// Shared by the work details form, the card section and the panel's note.
let state: State = EMPTY;
let generation = 0;
const listeners = new Set<() => void>();

function set(next: Partial<State>) {
  state = { ...state, ...next };
  listeners.forEach((l) => l());
}

const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};
const snapshot = () => state;

async function load(userId: string, quietReload = false) {
  const gen = ++generation;
  set(quietReload && state.userId === userId ? {} : { userId, status: "loading", card: null, error: null });
  const { data, error } = await getMyCard({ meta: { quiet: true }, cache: "no-store" });
  if (gen !== generation || state.userId !== userId) return;
  set(data ? { status: "ready", card: data, error: null } : { status: "error", error: error as unknown as ApiError });
}

/**
 * The signed-in professional's verification state, card settings and preview
 * (`GET /me/professional/card`). `enabled: false` reads nothing (patients, the
 * welcome flow).
 */
export function useMyCard({ enabled = true }: { enabled?: boolean } = {}) {
  const { user } = useSession();
  const snap = useSyncExternalStore(subscribe, snapshot, snapshot);
  const professional = user?.role === "doctor" || user?.role === "researcher";
  // The role is part of the key: a role change ends the verification server-side, so read again.
  const userId = enabled && professional && user?.age_confirmed ? `${user.id}:${user.role}` : null;

  useEffect(() => {
    if (!userId) return;
    if (state.userId !== userId) void load(userId);
  }, [userId]);

  const current = userId && snap.userId === userId ? snap : EMPTY;

  /** Re-read after a change elsewhere (work details saved, ORCID return); keeps the old state visible meanwhile. */
  const reload = useCallback(async () => {
    if (userId) await load(userId, true);
  }, [userId]);

  /** Take a fresh MyCard from a write response. */
  const apply = useCallback((card: MyCard) => {
    generation++;
    set({ status: "ready", card, error: null });
  }, []);

  return { ...current, reload, apply };
}
