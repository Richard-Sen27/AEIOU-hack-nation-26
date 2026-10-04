/**
 * One wording for every 429 (`rate_limited` or `busy`): when to come back,
 * from the server's `reason`, `retry_after` and `scope`.
 *
 * - budget, or a wait longer than an hour (a per-day route limit): "Try again tomorrow."
 * - rate: "Too many requests. Try again in 40 seconds." (the real wait, counted from `at`)
 * - busy: "… still running. Try again in a moment."
 */
import { ApiError } from "./errors";

export type LimitInfo = {
  reason?: "rate" | "busy" | "budget";
  /** Seconds to wait, as the server said when the error arrived. */
  retryAfter?: number;
  /** budget only: this account's daily limit, or Amber's for everyone. */
  scope?: "account" | "server";
  /** When the error arrived (ms since epoch). */
  at: number;
};

/** A wait longer than this comes from a per-day limit. Same as the API's DAILY_WAIT_S. */
const DAILY_WAIT_S = 3600;

/** The limit details of a 429, or undefined for any other error. */
export function limitInfo(error: unknown): LimitInfo | undefined {
  if (!(error instanceof ApiError) || error.status !== 429) return undefined;
  const d = error.details;
  const retry = Number(d.retry_after);
  // Without the server's details, callers keep their own wording.
  if (d.reason === undefined && d.retry_after === undefined) return undefined;
  return {
    reason: d.reason === "rate" || d.reason === "busy" || d.reason === "budget" ? d.reason : undefined,
    retryAfter: Number.isFinite(retry) && retry > 0 ? retry : undefined,
    scope: d.scope === "account" || d.scope === "server" ? d.scope : undefined,
    at: Date.now(),
  };
}

/** Seconds still to wait at `now`, or undefined when the server gave no wait. */
export function remaining(info: LimitInfo, now = Date.now()): number | undefined {
  if (info.retryAfter === undefined) return undefined;
  return Math.max(0, Math.ceil(info.retryAfter - (now - info.at) / 1000));
}

/** A daily limit: the model budget, or a route limit whose wait is longer than an hour. */
export function isDaily(info: LimitInfo | undefined): boolean {
  if (!info) return false;
  return info.reason === "budget" || (info.reason !== "busy" && (info.retryAfter ?? 0) > DAILY_WAIT_S);
}

/** "in 40 seconds", "in about a minute", "in 12 minutes", "in about an hour". */
export function waitPhrase(seconds: number): string {
  if (seconds < 60) return `in ${seconds} second${seconds === 1 ? "" : "s"}`;
  if (seconds < 120) return "in about a minute";
  if (seconds < DAILY_WAIT_S - 300) return `in ${Math.ceil(seconds / 60)} minutes`;
  return "in about an hour";
}

/**
 * The short message for a limit. `subject` names what is limited, as in
 * "Today's limit for Dr. Wu is reached." ("Dr. Wu", "summaries", "uploads", ...).
 */
export function limitMessage(info: LimitInfo | undefined, subject: string, now = Date.now()): string {
  if (!info) return "The usage limit is reached. Try again later.";
  if (info.reason === "busy") return "Amber is busy right now. Try again in a moment.";
  if (isDaily(info)) {
    return info.scope === "server"
      ? "Amber's daily limit is reached. Try again tomorrow."
      : `Today's limit for ${subject} is reached. Try again tomorrow.`;
  }
  const left = remaining(info, now);
  if (left === undefined) return "Too many requests. Try again in a moment.";
  if (left === 0) return "You can try again now.";
  return `Too many requests. Try again ${waitPhrase(left)}.`;
}
