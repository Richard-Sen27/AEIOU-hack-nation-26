"use client";

import { Sparkles } from "lucide-react";
import { useCallback, useEffect, useId, useState } from "react";
import { toast } from "sonner";

import { useConnectFlow } from "@/components/messages/connect-flow";
import { useSession } from "@/components/providers/session-provider";
import { Switch } from "@/components/ui/switch";
import { getSuggestionSettings, listSuggestedCalls, setSuggestionSettings, type Schemas } from "@/lib/api";
import { ApiError } from "@/lib/api/errors";

import { CallRow } from "./call-parts";

type SuggestedCall = Schemas.SuggestedCall;

/** Age and country as information only: they never hide a suggestion. */
function infoLine(s: SuggestedCall): string | null {
  const parts = [
    s.age_fits === true ? "Your age range is within the call's ages" : s.age_fits === false ? "Your age range is outside the call's ages" : null,
    s.country_listed === true ? "your country is listed" : s.country_listed === false ? "your country is not listed" : null,
  ].filter(Boolean) as string[];
  if (!parts.length) return null;
  const line = parts.join(", ");
  return line.charAt(0).toUpperCase() + line.slice(1) + ".";
}

function errorText(e: unknown): string {
  const code = e instanceof ApiError ? e.code : "";
  if (code === "network_error") return "Amber's server is not reachable. Please try again.";
  if (code === "consent_required") return "Your consent is needed first.";
  return "That did not work. Try again in a moment.";
}

/**
 * Suggestions on the calls page, for patients: a switch (off by default) and,
 * when it is on, the calls that overlap the confirmed profile, each with the
 * backend's sentence as sent. Computed inside the user's own account; nothing
 * here is an eligibility decision, and every call stays in the full list.
 */
export function SuggestedCalls() {
  const { user } = useSession();
  const id = useId();
  const flow = useConnectFlow();
  const patient = user?.role === "patient" && user.age_confirmed;
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [items, setItems] = useState<SuggestedCall[] | null>(null);
  const [busy, setBusy] = useState(false);

  const fetchItems = useCallback(async () => {
    const { data } = await listSuggestedCalls({ meta: { quiet: true }, cache: "no-store" });
    setItems(data && data.consent_active && data.enabled ? data.items : []);
  }, []);

  useEffect(() => {
    if (!patient) return;
    let live = true;
    getSuggestionSettings({ meta: { quiet: true }, cache: "no-store" }).then(({ data }) => {
      if (!live || !data) return;
      const on = data.enabled && data.consent_active;
      setEnabled(on);
      if (on) void fetchItems();
    });
    return () => {
      live = false;
    };
  }, [patient, fetchItems]);

  async function save(on: boolean, renewed = false): Promise<void> {
    const { data, error } = await setSuggestionSettings({ body: { enabled: on }, meta: { quiet: true } });
    if (data) {
      setEnabled(data.enabled);
      if (data.enabled) await fetchItems();
      else setItems(null);
      return;
    }
    if (on && !renewed && error instanceof ApiError && error.code === "consent_required") {
      if (await flow.ensure(true, { current: true })) return save(true, true);
      return;
    }
    toast(errorText(error));
  }

  async function toggle(on: boolean) {
    setBusy(true);
    try {
      if (on && !(await flow.ensure(false, { current: true }))) return;
      await save(on);
    } finally {
      setBusy(false);
    }
  }

  if (!patient || enabled === null) return null;
  return (
    <section aria-labelledby={`${id}-h`} className="space-y-3" data-testid="suggestions">
      <div className="flex items-start gap-3">
        <Switch
          id={`${id}-switch`}
          checked={enabled}
          disabled={busy}
          onCheckedChange={(v) => void toggle(v)}
          className="mt-0.5"
          data-testid="suggestions-switch"
        />
        <label htmlFor={`${id}-switch`} className="min-w-0 text-sm">
          <span id={`${id}-h`} className="block font-medium">
            Suggest calls that fit my profile
          </span>
          <span className="block text-muted-foreground">Compared inside your account. Study teams never see who was suggested.</span>
        </label>
      </div>
      {enabled && items && (
        <div className="space-y-2.5" data-testid="suggestions-block">
          <h2 className="flex items-center gap-1.5 text-sm font-semibold">
            <Sparkles className="size-4 text-primary" aria-hidden /> Suggested for you
          </h2>
          {items.length === 0 ? (
            <p className="text-sm text-muted-foreground" data-testid="suggestions-empty">
              Nothing matches your confirmed profile right now.
            </p>
          ) : (
            <ul className="space-y-2.5" data-testid="suggestions-list">
              {items.map((s) => {
                const info = infoLine(s);
                return (
                  <li key={s.call.id} className="space-y-1.5" data-testid="suggestion">
                    <CallRow call={s.call} />
                    <p className="px-1 text-xs text-muted-foreground" data-testid="suggestion-sentence">
                      {s.sentence}
                    </p>
                    {info && (
                      <p className="px-1 text-xs text-muted-foreground" data-testid="suggestion-info">
                        {info}
                      </p>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
      {flow.dialog}
    </section>
  );
}
