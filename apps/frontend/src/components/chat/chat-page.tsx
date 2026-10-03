"use client";

import { needsOnboarding } from "@/components/account/onboarding";
import { useSession } from "@/components/providers/session-provider";
import { Spinner } from "@/components/ui/spinner";

import { ChatGuest } from "./chat-guest";
import { ChatView } from "./chat-view";

/** `/chat`: signed in → the conversation; guests → what Dr. Wu does + sign-in. */
export function ChatPage() {
  const { user, status } = useSession();
  // A first sign-in is on its way to the welcome step: keep the conversation
  // (and any text handed over from the landing page) until it is back.
  if (status === "loading" || needsOnboarding(user)) {
    return (
      <div className="flex flex-1 items-center justify-center gap-2 py-24 text-sm text-muted-foreground">
        <h1 className="sr-only">Ask Dr. Wu</h1>
        <Spinner className="size-4" /> Loading…
      </div>
    );
  }
  if (!user) return <ChatGuest offline={status === "offline"} />;
  // Remount per user so nothing from one account survives into another.
  return <ChatView key={user.id} />;
}
