"use client";

import { ArrowRight } from "lucide-react";
import { useRouter } from "next/navigation";

import { useSession } from "@/components/providers/session-provider";
import { setPendingChatMessage } from "@/lib/handoff";

import { DEMO_MESSAGE } from "./landing-config";

/** Demo mode only: one line that starts the demo family's journey (Dr. Wu signed in, else the tour). */
export function DemoJourney() {
  const router = useRouter();
  const { user, demoMode } = useSession();
  if (!demoMode) return null;
  return (
    <div className="mx-auto w-full max-w-5xl px-4 pb-16 text-center sm:px-6" data-testid="demo-journey">
      <button
        type="button"
        onClick={() => {
          if (user) {
            setPendingChatMessage(DEMO_MESSAGE);
            router.push("/chat");
          } else {
            router.push("/atlas?tour=1");
          }
        }}
        className="inline-flex h-10 items-center gap-1.5 rounded-full border border-primary/40 bg-primary/10 px-5 text-sm font-medium outline-none transition-colors hover:bg-primary/15 focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        Try one family&apos;s journey
        <ArrowRight className="size-4" aria-hidden />
      </button>
    </div>
  );
}
