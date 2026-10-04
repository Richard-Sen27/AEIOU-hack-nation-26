"use client";

import { SearchX, TriangleAlert, WifiOff } from "lucide-react";
import Link from "next/link";

import { needsOnboarding } from "@/components/account/onboarding";
import { PersonCalls } from "@/components/calls/person-calls";
import { SessionLoading, SignInPrompt } from "@/components/account/sign-in-prompt";
import { useSession } from "@/components/providers/session-provider";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

import { cardHref, PublicCardView } from "./public-card";
import { usePersonCard } from "./use-people";

/**
 * `/people/<card_id>`: one public card. Signed-in users only: guests get the
 * sign-in prompt, accounts without the age check are sent to /welcome by the
 * global onboarding redirect.
 */
export function PersonCardPage({ cardId }: { cardId: string }) {
  const { user, status } = useSession();
  const card = usePersonCard(cardId);

  if (status === "loading" || needsOnboarding(user)) return <SessionLoading />;
  if (!user) {
    return (
      <SignInPrompt
        title="Sign in to see this card"
        description="Cards of verified doctors and researchers are shown to signed-in users only."
        returnTo={cardHref(cardId)}
      />
    );
  }
  if (card.kind === "idle" || card.kind === "loading") {
    return (
      <div className="space-y-3 rounded-xl border bg-card p-5" aria-busy="true" aria-label="Loading the card">
        <Skeleton className="h-6 w-1/2" />
        <Skeleton className="h-4 w-1/3" />
        <Skeleton className="h-12 w-full" />
      </div>
    );
  }
  if (card.kind === "error") {
    const notFound = card.error.status === 404 || card.error.code === "not_found" || card.error.status === 422;
    const offline = card.error.code === "network_error";
    const Icon = notFound ? SearchX : offline ? WifiOff : TriangleAlert;
    return (
      <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed p-8 text-center" data-testid="card-error" role="status">
        <span className="flex size-10 items-center justify-center rounded-full bg-muted">
          <Icon className="size-5 text-muted-foreground" aria-hidden />
        </span>
        <h1 className="text-lg font-semibold tracking-tight">
          {notFound ? "This card is not shown" : offline ? "Amber's server can't be reached" : "This card could not be loaded"}
        </h1>
        <p className="text-sm text-muted-foreground">
          {notFound ? "It was switched off or never existed." : "Please try again in a moment."}
        </p>
        <Link href="/atlas" className={buttonVariants({ variant: "outline" })}>
          Go to the Atlas
        </Link>
      </div>
    );
  }
  return (
    <PublicCardView card={card.data} heading="h1">
      {/* Stage 5 passes a "Message" action. */}
      <PersonCalls cardId={card.data.card_id} className="mt-4 border-t pt-4" />
    </PublicCardView>
  );
}
