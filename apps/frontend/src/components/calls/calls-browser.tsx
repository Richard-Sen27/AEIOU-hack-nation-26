"use client";

import { useState } from "react";

import { NativeSelect } from "@/components/account/native-select";
import { SignInPrompt } from "@/components/account/sign-in-prompt";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

import { CALL_KINDS, callErrorText, KIND_META, type CallKind } from "./call-meta";
import { CallRow } from "./call-parts";
import { usePublishedCalls } from "./use-published-calls";

const ALL = "all";

/**
 * The list of published calls with a kind and a disease filter. Both filters
 * run in the browser and live in component state only: disease ids never go
 * into a URL.
 */
export function CallsBrowser() {
  const calls = usePublishedCalls();
  const [kind, setKind] = useState<CallKind | typeof ALL>(ALL);
  const [disease, setDisease] = useState<string>(ALL);

  const items = calls.kind === "ready" ? calls.items : [];
  const byId = new Map<string, string>();
  for (const c of items) for (const d of c.diseases) byId.set(d.id, d.label ?? d.id);
  const diseases = [...byId.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  const shown = items.filter((c) => (kind === ALL || c.kind === kind) && (disease === ALL || c.diseases.some((d) => d.id === disease)));

  if (calls.kind === "guest") {
    return (
      <SignInPrompt
        title="Sign in to see open calls"
        description="Surveys, studies and trials from verified researchers and doctors. Nothing about what you read is stored."
        returnTo="/calls"
      />
    );
  }
  if (calls.kind === "loading") {
    return (
      <div className="space-y-3" aria-busy="true" aria-label="Loading calls">
        <Skeleton className="h-9 w-80 max-w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }
  if (calls.kind === "error") {
    return (
      <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground" role="status" data-testid="calls-error">
        {callErrorText(calls.error)}
        <Button variant="outline" size="sm" onClick={calls.retry}>
          Try again
        </Button>
      </div>
    );
  }

  const filtered = kind !== ALL || disease !== ALL;
  return (
    <div className="space-y-4" data-testid="calls-browser">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <ToggleGroup
          value={[kind]}
          onValueChange={(v: unknown[]) => setKind((v[0] as CallKind | undefined) ?? ALL)}
          variant="outline"
          size="sm"
          aria-label="Kind"
          className="w-full sm:w-auto"
          data-testid="calls-kind-filter"
        >
          <ToggleGroupItem value={ALL} className="flex-1 sm:flex-none">
            All
          </ToggleGroupItem>
          {CALL_KINDS.map((k) => (
            <ToggleGroupItem key={k} value={k} className="flex-1 sm:flex-none">
              {KIND_META[k].plural}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        {diseases.length > 0 && (
          <NativeSelect
            value={disease}
            onChange={(e) => setDisease(e.target.value)}
            aria-label="Disease"
            className="sm:max-w-72"
            data-testid="calls-disease-filter"
          >
            <option value={ALL}>All diseases</option>
            {diseases.map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </NativeSelect>
        )}
        <p className="text-xs text-muted-foreground sm:ml-auto" aria-live="polite" data-testid="calls-count">
          {shown.length} open
        </p>
      </div>

      {shown.length > 0 ? (
        <ul className="space-y-2.5" data-testid="calls-list">
          {shown.map((c) => (
            <li key={c.id}>
              <CallRow call={c} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="flex flex-wrap items-center gap-2 py-6 text-sm text-muted-foreground" data-testid="calls-empty">
          {filtered ? "Nothing open matches." : "No open calls right now."}
          {filtered && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setKind(ALL);
                setDisease(ALL);
              }}
            >
              Show all
            </Button>
          )}
        </p>
      )}
    </div>
  );
}
