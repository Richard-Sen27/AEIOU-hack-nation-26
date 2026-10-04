import { Info } from "lucide-react";

import type { Schemas } from "@/lib/api";
import { cn } from "@/lib/utils";

export type Thread = Schemas.ThreadSummary;
export type ThreadStatus = Schemas.ThreadStatus;

export const MAX_BODY = 2000;
export const MAX_NAME = 60;

export function counterpartName(t: Thread) {
  if (t.counterpart.deleted) return "Deleted account";
  return t.counterpart.name || "Someone";
}

/** A short status word for everything but an ordinary open conversation. */
export function statusLabel(t: Thread): string | null {
  if (t.counterpart.deleted) return "Account deleted";
  switch (t.status) {
    case "requested":
      return t.can_respond ? "Request" : "Waiting";
    case "declined":
      return "Declined";
    case "closed":
      return "Closed";
    case "blocked":
      return "Blocked";
    default:
      return null;
  }
}

/** One line under the conversation instead of the composer when nothing can be sent. */
export function closedNote(t: Thread): string | null {
  const name = counterpartName(t);
  if (t.counterpart.deleted) return "This account was deleted. Its messages were removed.";
  switch (t.status) {
    case "requested":
      return t.can_respond ? null : `Waiting for ${name} to accept.`;
    case "declined":
      return t.my_role === "recipient" ? "You declined this request." : `${name} declined this request.`;
    case "closed":
      return "This conversation is closed.";
    case "blocked":
      return t.blocked_by_me ? "You blocked this person." : "You can't reply here.";
    default:
      return t.can_send ? null : "This conversation is closed.";
  }
}

export function formatWhen(iso: string | null | undefined) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  return sameDay
    ? d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

function Banner({ children, className, testId }: { children: React.ReactNode; className?: string; testId: string }) {
  return (
    <p
      className={cn("flex items-start gap-2 rounded-lg bg-muted/70 px-3 py-2 text-xs leading-relaxed text-muted-foreground", className)}
      data-testid={testId}
    >
      <Info className="mt-px size-3.5 shrink-0" aria-hidden />
      <span>{children}</span>
    </p>
  );
}

export function PatientBanner({ className }: { className?: string }) {
  return (
    <Banner className={className} testId="banner-patient">
      You are writing to a person, not Dr. Wu. Messages are not a medical consultation or a medical record. In an emergency call
      112/911.
    </Banner>
  );
}

export function ExpertBanner({ className }: { className?: string }) {
  return (
    <Banner className={className} testId="banner-expert">
      You are writing to a person, not Dr. Wu. Do not give individual medical advice or prescribe through Amber.
    </Banner>
  );
}
