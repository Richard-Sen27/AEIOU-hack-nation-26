"use client";

import { Bell, BellRing, Loader2, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { routeGlobalError } from "@/components/account/api-errors";
import { useGate } from "@/components/providers/gate-provider";
import { useSession } from "@/components/providers/session-provider";
import { Button } from "@/components/ui/button";
import { announce } from "@/lib/a11y";
import { hasConsent } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { followErrorText, useFollows } from "./use-follows";

/**
 * "Follow" / "Following" for one atlas disease. Guests get the sign-in dialog,
 * the first follow the health-data consent. The disease id goes in the request
 * body only.
 */
export function FollowButton({
  nodeId,
  label,
  updatesAvailable,
  className,
}: {
  nodeId: string;
  label: string;
  /** False when no papers, trials or groups are collected for this disease (only new studies notify). */
  updatesAvailable?: boolean;
  className?: string;
}) {
  const { user, status } = useSession();
  const { requireSignIn, requireConsent } = useGate();
  const follows = useFollows();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const followed = follows.get(nodeId);
  const following = !!followed;
  const noUpdates = (followed?.updates_available ?? updatesAvailable) === false;

  async function toggle() {
    setError(null);
    if (!user) {
      const here = `${window.location.pathname}${window.location.search}`;
      await requireSignIn("Sign in to follow a disease.", here);
      return;
    }
    if (!following && !hasConsent(user, "health_data")) {
      if (!(await requireConsent("health_data", "Following a disease needs your consent."))) return;
    }
    setBusy(true);
    const res = following ? await follows.unfollow(nodeId) : await follows.follow(nodeId);
    setBusy(false);
    if (res.ok) {
      announce(following ? `Stopped following ${label}.` : `Following ${label}.`);
      return;
    }
    const err = routeGlobalError(res.error);
    if (err && ["sign_in_required", "reauth_required", "age_confirmation_required", "consent_required"].includes(err.code)) return;
    setError(followErrorText(err ?? undefined, follows.limit));
  }

  return (
    <div className={cn("space-y-1", className)} data-testid="follow">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <Button
          variant={following ? "secondary" : "outline"}
          size="sm"
          onClick={() => void toggle()}
          disabled={busy || status === "loading" || (!!user && follows.status === "loading")}
          aria-pressed={user ? following : undefined}
          data-testid="follow-toggle"
        >
          {busy ? (
            <Loader2 className="animate-spin" data-icon="inline-start" aria-hidden />
          ) : following ? (
            <BellRing className="text-primary" data-icon="inline-start" aria-hidden />
          ) : (
            <Bell data-icon="inline-start" aria-hidden />
          )}
          {following ? "Following" : "Follow"}
          <span className="sr-only"> {label}</span>
        </Button>
        {noUpdates && (
          <span className="text-xs text-muted-foreground" data-testid="follow-no-updates">
            Notifies you about new studies only.
          </span>
        )}
      </div>
      {error && (
        <p role="alert" className="flex items-center gap-1.5 text-xs" data-testid="follow-error">
          <TriangleAlert className="size-3.5 shrink-0 text-status-flag" aria-hidden />
          {error}
        </p>
      )}
    </div>
  );
}
