"use client";

import { MessageCircleQuestion } from "lucide-react";

import { Button } from "@/components/ui/button";

import type { FollowUp } from "./types";

/** At most one question with quick replies; always skippable. */
export function FollowUpQuestion({
  followUp,
  active,
  onReply,
  onSkip,
}: {
  followUp: FollowUp;
  active: boolean;
  onReply: (text: string) => void;
  onSkip: () => void;
}) {
  if (!active) return null;
  return (
    <section
      aria-labelledby="follow-up-q"
      className="rounded-xl border border-primary/40 bg-primary/5 p-3.5"
      data-testid="follow-up"
    >
      <p id="follow-up-q" className="flex items-start gap-2 text-[15px] font-medium" dir="auto">
        <MessageCircleQuestion className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
        {followUp.question}
      </p>
      <div className="mt-2.5 flex flex-wrap gap-2 pl-6" role="group" aria-label="Quick replies">
        {followUp.quick_replies.map((r) => (
          <Button key={r} variant="outline" size="sm" onClick={() => onReply(r)}>
            <span dir="auto">{r}</span>
          </Button>
        ))}
        <Button variant="ghost" size="sm" onClick={onSkip} className="text-muted-foreground">
          Skip this question
        </Button>
      </div>
    </section>
  );
}
