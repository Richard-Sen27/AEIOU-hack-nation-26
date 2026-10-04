"use client";

import { Loader2, ShieldCheck, ShieldOff } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { CONSENT_LABELS, WITHDRAWAL_EFFECT } from "@/components/privacy/consent-texts";
import { useGate } from "@/components/providers/gate-provider";
import { useSession } from "@/components/providers/session-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { announce } from "@/lib/a11y";
import { ApiError } from "@/lib/api/errors";
import { listConsents, revokeConsent, unwrap } from "@/lib/api";
import type { Consent } from "@/lib/api/generated/types.gen";
import type { ConsentType } from "@/lib/api/types";

import { formatDate } from "./labels";

const TYPES: ConsentType[] = ["health_data", "contribute"];

/**
 * Current state and history of each consent. Granting and withdrawing are
 * one action each (Art. 7(3): as easy to withdraw as to give); what
 * withdrawal deletes is stated next to the button before it is pressed.
 */
export function ConsentsSection({ onChanged }: { onChanged?: () => void }) {
  const { user, refresh } = useSession();
  const { requireConsent } = useGate();
  const [list, setList] = useState<Consent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<ConsentType | null>(null);

  const load = useCallback(async () => {
    try {
      setList(await unwrap(listConsents({ meta: { quiet: true }, cache: "no-store" })));
      setError(null);
    } catch (e) {
      const code = e instanceof ApiError ? e.code : "";
      setError(code === "not_implemented" ? "Consent history is not available yet." : "Consent history could not be loaded.");
      setList([]);
    }
  }, []);

  // Reload when the active consents change anywhere (e.g. granted from the contribute form).
  const activeKey = (user?.consents ?? []).join(",");
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch, state set after await
    void load();
  }, [load, activeKey]);

  async function withdraw(type: ConsentType) {
    setBusy(type);
    try {
      await unwrap(revokeConsent({ path: { consent_type: type }, meta: { quiet: true } }));
      await Promise.all([refresh(), load()]);
      onChanged?.();
      const msg = `${CONSENT_LABELS[type].title} consent withdrawn.`;
      toast(msg, { description: WITHDRAWAL_EFFECT[type] });
      announce(msg);
    } catch (e) {
      const code = e instanceof ApiError ? e.code : "";
      toast("Consent not withdrawn", {
        description: code === "network_error" ? "Amber's server is not reachable. Please try again." : "Please try again.",
      });
    } finally {
      setBusy(null);
    }
  }

  async function grant(type: ConsentType) {
    setBusy(type);
    const ok = await requireConsent(type);
    if (ok) {
      await load();
      onChanged?.();
      toast(`${CONSENT_LABELS[type].title} consent given.`);
    }
    setBusy(null);
  }

  const history = [...(list ?? [])].sort((a, b) => b.granted_at.localeCompare(a.granted_at));

  return (
    <div className="space-y-5">
      <ul className="grid gap-3 lg:grid-cols-2">
        {TYPES.map((type) => {
          const record = list?.find((c) => c.consent_type === type && c.active);
          const active = !!record || !!user?.consents?.includes(type);
          return (
            <li key={type} className="flex flex-col gap-3 rounded-lg border bg-background p-4" data-testid={`consent-${type}`}>
              <div className="flex items-start gap-3">
                {active ? (
                  <ShieldCheck className="mt-0.5 size-5 shrink-0 text-secondary" aria-hidden />
                ) : (
                  <ShieldOff className="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-hidden />
                )}
                <div className="min-w-0 flex-1 space-y-1">
                  <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
                    {CONSENT_LABELS[type].title}
                    <Badge variant={active ? "secondary" : "outline"} data-testid={`consent-${type}-state`}>
                      {active ? "Given" : "Not given"}
                    </Badge>
                  </p>
                  <p className="text-sm text-muted-foreground">{CONSENT_LABELS[type].description}</p>
                  {record && (
                    <p className="text-xs text-muted-foreground">
                      Given {formatDate(record.granted_at, true)} · text version {record.version}
                      {record.about_child ? " · about a child, parental responsibility confirmed" : ""}
                    </p>
                  )}
                </div>
              </div>
              {active ? (
                <div className="mt-auto space-y-2 border-t pt-3">
                  <p className="text-xs text-muted-foreground">{WITHDRAWAL_EFFECT[type]}</p>
                  <Button
                    variant="outline"
                    onClick={() => void withdraw(type)}
                    disabled={busy === type}
                    data-testid={`withdraw-${type}`}
                  >
                    {busy === type && <Loader2 className="animate-spin" aria-hidden />}
                    Withdraw consent
                  </Button>
                </div>
              ) : (
                <div className="mt-auto border-t pt-3">
                  <Button variant="outline" onClick={() => void grant(type)} disabled={busy === type} data-testid={`grant-${type}`}>
                    Give consent
                  </Button>
                </div>
              )}
            </li>
          );
        })}
      </ul>

      <details className="text-sm">
        <summary className="cursor-pointer font-medium">Consent history</summary>
        {error ? (
          <p className="mt-2 text-muted-foreground">{error}</p>
        ) : history.length ? (
          <ol className="mt-2 divide-y rounded-lg border bg-background" data-testid="consent-history">
            {history.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-xs">
                <span className="font-medium text-foreground">{CONSENT_LABELS[c.consent_type].title}</span>
                <span className="text-muted-foreground">given {formatDate(c.granted_at, true)}</span>
                {c.revoked_at && <span className="text-muted-foreground">withdrawn {formatDate(c.revoked_at, true)}</span>}
                <span className="font-mono text-muted-foreground">{c.version}</span>
                {c.about_child && <span className="text-muted-foreground">about a child</span>}
              </li>
            ))}
          </ol>
        ) : (
          <p className="mt-2 text-muted-foreground">No consents yet.</p>
        )}
      </details>
    </div>
  );
}
