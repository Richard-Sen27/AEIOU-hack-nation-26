"use client";

import { createContext, useContext, useMemo } from "react";

import { LABEL_STYLE_BY_ROLE, type LabelStyle } from "@/lib/graph/meta";
import type { Role } from "@/lib/graph/types";

import { useSession } from "./session-provider";

/**
 * The role lens decides where you start and how things are worded, never
 * what you can see. It follows the signed-in user's role from their settings
 * (changed on the profile page); signed-out visitors always get the guest lens.
 */
type LensContextValue = {
  role: Role;
  labelStyle: LabelStyle;
};

const LensContext = createContext<LensContextValue | null>(null);

export function LensProvider({ children }: { children: React.ReactNode }) {
  const { user } = useSession();
  const role: Role = user?.role ?? "guest";

  const value = useMemo<LensContextValue>(() => ({ role, labelStyle: LABEL_STYLE_BY_ROLE[role] }), [role]);
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
