"use client";

import { BellPlus, Loader2, TriangleAlert, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { followErrorText, useFollows } from "@/components/follows/use-follows";
import { useGate } from "@/components/providers/gate-provider";
import { useSession } from "@/components/providers/session-provider";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { announce } from "@/lib/a11y";
import { hasConsent } from "@/lib/api/types";

import { routeGlobalError } from "./api-errors";

const GLOBAL = ["sign_in_required", "reauth_required", "age_confirmation_required", "consent_required"];

/** The diseases the user follows, unfollow, and one click to follow the profile's diagnoses. */
export function FollowingSection() {
  const { user } = useSession();
  const { requireConsent } = useGate();
  const follows = useFollows();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  async function unfollow(nodeId: string, label: string) {
    setError(null);
    setBusy(nodeId);
    const res = await follows.unfollow(nodeId);
    setBusy(null);
    if (res.ok) return announce(`Stopped following ${label}.`);
    const err = routeGlobalError(res.error);
    if (!err || !GLOBAL.includes(err.code)) setError(followErrorText(err ?? undefined, follows.limit));
  }

  async function fromProfile() {
    setError(null);
    setResult(null);
    if (!hasConsent(user, "health_data") && !(await requireConsent("health_data", "Following a disease needs your consent."))) return;
    setBusy("profile");
    const res = await follows.followFromProfile();
    setBusy(null);
    if (!res.ok) {
      const err = routeGlobalError(res.error);
      if (!err || !GLOBAL.includes(err.code)) setError(followErrorText(err ?? undefined, follows.limit));
      return;
    }
    const r = res.result;
    const parts = [
      r.added.length ? `Added: ${r.added.map((f) => f.label ?? f.node_id).join(", ")}.` : "Nothing new to add.",
      r.not_in_atlas.length ? `${r.not_in_atlas.length} not in the atlas.` : "",
      r.limit_reached ? `Limit of ${follows.limit} reached.` : "",
    ];
    const text = parts.filter(Boolean).join(" ");
    setResult(text);
    announce(text);
  }

  return (
    <div className="space-y-3" data-testid="following-section">
      {follows.status === "loading" && <Skeleton className="h-9 w-full" />}
      {follows.status === "error" && <p className="text-sm text-muted-foreground">Couldn&apos;t load.</p>}
      {follows.status === "ready" && follows.items.length === 0 && (
        <p className="text-sm text-muted-foreground" data-testid="following-empty">
          Not following any disease.
        </p>
      )}
      {follows.items.length > 0 && (
        <ul className="divide-y rounded-lg border" data-testid="following-list">
          {follows.items.map((f) => {
            const label = f.label ?? f.node_id;
            return (
              <li key={f.node_id} className="flex items-center gap-2 px-3 py-2 text-sm" data-testid="following-item">
                <div className="min-w-0 flex-1">
                  {f.in_atlas ? (
                    <Link href={`/node/${encodeURIComponent(f.node_id)}`} className="font-medium underline-offset-2 hover:underline">
                      {label}
                    </Link>
                  ) : (
                    <span className="font-medium">{label}</span>
                  )}
                  {(!f.in_atlas || !f.updates_available) && (
                    <span className="ml-2 text-xs text-muted-foreground">
                      {!f.in_atlas ? "No longer in the atlas" : "New studies only"}
                    </span>
                  )}
                </div>
                <Button
                  variant="ghost"
                  size="xs"
                  onClick={() => void unfollow(f.node_id, label)}
                  disabled={busy === f.node_id}
                  aria-label={`Unfollow ${label}`}
                  data-testid="following-unfollow"
                >
                  {busy === f.node_id ? <Loader2 className="animate-spin" aria-hidden /> : <X aria-hidden />}
                  Unfollow
                </Button>
              </li>
            );
          })}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Button variant="outline" size="sm" onClick={() => void fromProfile()} disabled={busy === "profile"} data-testid="following-from-profile">
          {busy === "profile" ? <Loader2 className="animate-spin" data-icon="inline-start" aria-hidden /> : <BellPlus data-icon="inline-start" aria-hidden />}
          Follow the diseases in my profile
        </Button>
        {result && (
          <p className="text-sm text-muted-foreground" role="status" data-testid="following-result">
            {result}
          </p>
        )}
      </div>
      {error && (
        <p role="alert" className="flex items-center gap-1.5 text-sm" data-testid="following-error">
          <TriangleAlert className="size-4 shrink-0 text-status-flag" aria-hidden />
          {error}
        </p>
      )}
    </div>
  );
}
