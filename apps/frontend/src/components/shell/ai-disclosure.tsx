import { Bot } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * "You are talking to an AI system" (EU AI Act Art. 50). Put it on every
 * assistant surface (chat, explanations, gap search), shown clearly at the
 * latest at the first interaction. Not dismissible.
 *
 * - `banner` (default): full-width strip at the top of an assistant panel.
 * - `inline`: compact pill, e.g. next to a streamed explanation.
 * - `line`: one quiet line at the start of a conversation (Dr. Wu chat and
 *   dock); it scrolls away with the content and is not repeated per turn.
 */
export function AiDisclosure({
  variant = "banner",
  className,
}: {
  variant?: "banner" | "inline" | "line";
  className?: string;
}) {
  if (variant === "line") {
    return (
      <p
        role="note"
        aria-label="AI system disclosure"
        data-testid="ai-disclosure"
        className={cn("flex items-center gap-1.5 text-xs text-muted-foreground", className)}
      >
        <Bot className="size-3.5 shrink-0 text-primary" aria-hidden />
        <span>
          <span className="font-medium text-foreground">Dr. Wu is an AI, not a doctor.</span> It can be wrong and never
          diagnoses.
        </span>
      </p>
    );
  }
  if (variant === "inline") {
    return (
      <span
        role="note"
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-foreground",
          className,
        )}
      >
        <Bot className="size-3.5 text-primary" aria-hidden />
        AI-generated · Dr. Wu
      </span>
    );
  }
  return (
    <div
      role="note"
      aria-label="AI system disclosure"
      data-testid="ai-disclosure"
      className={cn(
        "flex items-start gap-3 rounded-lg border border-primary/40 bg-primary/10 px-3.5 py-2.5 text-sm",
        className,
      )}
    >
      <Bot className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
      <p className="leading-snug">
        <span className="font-semibold">You are talking to an AI system.</span>{" "}
        <span className="text-muted-foreground">
          Dr. Wu is an AI assistant, not a person or a doctor. It answers only from cited sources
          in the atlas, can be wrong, and never gives a diagnosis or treatment advice.
        </span>
      </p>
    </div>
  );
}
