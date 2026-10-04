"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { useSession } from "@/components/providers/session-provider";
import { Button } from "@/components/ui/button";
import { getConnectStatus, listBlocks, setConnectAgeGroup, unblock, unwrap, type Schemas } from "@/lib/api";

import { AGE_GROUP_LABEL, messagingErrorText, type AgeGroup, type ConnectStatus } from "./connect-flow";

/**
 * Messaging settings beside the account settings: the stated age group (correctable)
 * and the people blocked, with unblock. Renders nothing when neither exists.
 */
export function ConnectSettings() {
  const { user } = useSession();
  const consentKey = (user?.consents ?? []).join(",");
  const [status, setStatus] = useState<ConnectStatus | null>(null);
  const [blocks, setBlocks] = useState<Schemas.Block[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [s, b] = await Promise.all([
      getConnectStatus({ meta: { quiet: true }, cache: "no-store" }),
      listBlocks({ meta: { quiet: true }, cache: "no-store" }),
    ]);
    if (s.data) setStatus(s.data);
    if (b.data) setBlocks(b.data.items);
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch, state set after await
    void load();
  }, [load, consentKey]);

  async function changeAge(group: AgeGroup) {
    setBusy("age");
    try {
      setStatus(await unwrap(setConnectAgeGroup({ body: { age_group: group }, meta: { quiet: true } })));
      toast("Age group saved.");
    } catch (e) {
      toast(messagingErrorText(e));
    } finally {
      setBusy(null);
    }
  }

  async function lift(b: Schemas.Block) {
    setBusy(b.id);
    try {
      await unwrap(unblock({ path: { block_id: b.id }, meta: { quiet: true } }));
      setBlocks((list) => list.filter((x) => x.id !== b.id));
      toast(`${b.name ?? "This person"} is unblocked.`);
    } catch (e) {
      toast(messagingErrorText(e));
    } finally {
      setBusy(null);
    }
  }

  const showAge = !!status?.consent_active && !!status.age_group;
  if (!showAge && blocks.length === 0) return null;

  return (
    <div className="mt-6 space-y-5 border-t pt-5" data-testid="connect-settings">
      {showAge && status?.age_group && (
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm font-medium">Age group for messages</span>
          <div className="flex gap-1" role="radiogroup" aria-label="Age group for messages">
            {(Object.keys(AGE_GROUP_LABEL) as AgeGroup[]).map((g) => (
              <Button
                key={g}
                size="sm"
                variant={status.age_group === g ? "secondary" : "ghost"}
                role="radio"
                aria-checked={status.age_group === g}
                disabled={busy === "age"}
                onClick={() => status.age_group !== g && void changeAge(g)}
                data-testid={`age-${g}`}
              >
                {AGE_GROUP_LABEL[g]}
              </Button>
            ))}
          </div>
        </div>
      )}
      {blocks.length > 0 && (
        <div className="space-y-2" data-testid="blocked-people">
          <h3 className="text-sm font-medium">Blocked</h3>
          <ul className="divide-y rounded-lg border bg-background">
            {blocks.map((b) => (
              <li key={b.id} className="flex items-center gap-3 px-3 py-2 text-sm" data-testid="blocked-person">
                <span className="min-w-0 flex-1 truncate">{b.name ?? "Deleted account"}</span>
                <Button variant="outline" size="sm" onClick={() => void lift(b)} disabled={busy === b.id} data-testid="unblock">
                  Unblock
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
