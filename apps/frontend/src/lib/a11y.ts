"use client";

import { announce as ariaAnnounce, clearAnnouncer } from "@react-aria/live-announcer";

/**
 * Announce a change to screen readers through React Aria's shared live
 * region, e.g. after a graph view changes:
 *
 *   announce("Showing 24 diseases that share the STXBP1 mechanism.");
 *
 * Use "assertive" only for errors that block the user. Never announce raw
 * health data typed by the user back verbatim in logs; announcing UI state
 * on-device is fine.
 */
export function announce(
  message: string,
  politeness: "polite" | "assertive" = "polite",
): void {
  if (typeof window === "undefined" || !message) return;
  ariaAnnounce(message, politeness);
}

export function clearAnnouncements(politeness?: "polite" | "assertive"): void {
  if (typeof window === "undefined") return;
  clearAnnouncer(politeness ?? "polite");
}
