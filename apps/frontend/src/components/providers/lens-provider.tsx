"use client";

import { createContext, useCallback, useContext, useMemo, useSyncExternalStore } from "react";

import { LABEL_STYLE_BY_ROLE, type LabelStyle } from "@/lib/graph/meta";
import { ROLES, type Role } from "@/lib/graph/types";

import { useSession } from "./session-provider";

/**
 * The role lens decides where you start and how things are worded, never
 * what you can see. Anyone (guest or signed in) may switch it; a signed-in
 * user's saved role is the default. The choice is a UI preference stored in
 * localStorage (not health data).
 */
type LensContextValue = {
  role: Role;
  labelStyle: LabelStyle;
  /** True when the user picked a lens that differs from the default. */
  overridden: boolean;
  setRole: (role: Role) => void;
  /** Forget the manual choice and use the default again. */
  resetRole: () => void;
};

const STORAGE_KEY = "amber.lens";
const LensContext = createContext<LensContextValue | null>(null);

const listeners = new Set<() => void>();
function subscribe(cb: () => void) {
  listeners.add(cb);
  const onStorage = (e: StorageEvent) => e.key === STORAGE_KEY && cb();
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", onStorage);
  };
}
function readStored(): Role | null {
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    return v && (ROLES as string[]).includes(v) ? (v as Role) : null;
  } catch {
    return null;
  }
}
function writeStored(role: Role | null) {
  try {
    if (role) window.localStorage.setItem(STORAGE_KEY, role);
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage blocked: the lens just won't persist */
  }
  listeners.forEach((l) => l());
}

export function LensProvider({ children }: { children: React.ReactNode }) {
  const { user } = useSession();
  const stored = useSyncExternalStore(subscribe, readStored, () => null);
  const fallback: Role = user?.role ?? "guest";
  const role = stored ?? fallback;

  const setRole = useCallback((next: Role) => writeStored(next), []);
  const resetRole = useCallback(() => writeStored(null), []);

  const value = useMemo<LensContextValue>(
    () => ({
      role,
      labelStyle: LABEL_STYLE_BY_ROLE[role],
      overridden: stored !== null && stored !== fallback,
      setRole,
      resetRole,
    }),
    [role, stored, fallback, setRole, resetRole],
  );
  return <LensContext.Provider value={value}>{children}</LensContext.Provider>;
}

export function useLens(): LensContextValue {
  const ctx = useContext(LensContext);
  if (!ctx) throw new Error("useLens must be used inside <LensProvider>");
  return ctx;
}

export const ROLE_LABELS: Record<Role, { label: string; description: string }> = {
  guest: { label: "Guest", description: "A guided tour in simple language." },
  patient: { label: "Patient or family", description: "Start at your condition, in plain language." },
  doctor: { label: "Doctor", description: "Start with the symptom profile, in clinical terms." },
  researcher: { label: "Researcher", description: "Start with mechanism clusters, with IDs shown." },
};
