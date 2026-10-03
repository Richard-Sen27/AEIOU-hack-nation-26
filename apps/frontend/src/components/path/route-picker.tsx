"use client";

import { ArrowLeftRight, ArrowUpDown } from "lucide-react";

import { useLens } from "@/components/providers/lens-provider";
import { EDGE_FAMILY_META } from "@/lib/graph/meta";
import { cn } from "@/lib/utils";

import { EntityPicker } from "./entity-picker";
import { FAMILIES, type Endpoint, type Family } from "./types";

const ALL_LABEL = { plain: "Any connection", clinical: "All link types", technical: "All families" } as const;

export function familyLabel(family: Family, style: "plain" | "clinical" | "technical") {
  return family === "all" ? ALL_LABEL[style] : EDGE_FAMILY_META[family].label[style];
}

/** From, to (entity search), swap, and the edge-family filter. */
export function RoutePicker({
  from,
  to,
  family,
  onFrom,
  onTo,
  onSwap,
  onFamily,
}: {
  from: Endpoint | null;
  to: Endpoint | null;
  family: Family;
  onFrom: (e: Endpoint | null) => void;
  onTo: (e: Endpoint | null) => void;
  onSwap: () => void;
  onFamily: (f: Family) => void;
}) {
  const { labelStyle } = useLens();
  return (
    <section aria-label="Choose a route" className="space-y-4" data-testid="route-picker">
      <div className="flex flex-col gap-2 md:flex-row md:items-end md:gap-3">
        <EntityPicker
          label="From"
          value={from}
          onChange={onFrom}
          placeholder="A disease, gene or symptom…"
          testId="pick-from"
        />
        <button
          type="button"
          onClick={onSwap}
          disabled={!from && !to}
          className="flex h-11 w-11 shrink-0 items-center justify-center self-center rounded-full border bg-card text-muted-foreground shadow-xs outline-none transition hover:bg-muted hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-40 md:self-end"
          aria-label="Swap from and to"
          data-testid="swap"
        >
          <ArrowLeftRight className="hidden size-4 md:block" aria-hidden />
          <ArrowUpDown className="size-4 md:hidden" aria-hidden />
        </button>
        <EntityPicker
          label="To"
          value={to}
          onChange={onTo}
          placeholder="Where should the route lead?"
          testId="pick-to"
        />
      </div>

      <fieldset className="flex flex-wrap items-center gap-x-3 gap-y-2" data-testid="family-filter">
        <legend className="sr-only">Kind of connection</legend>
        <span aria-hidden className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-muted-foreground">
          Follow
        </span>
        <div className="flex flex-wrap gap-1.5">
          {FAMILIES.map((f) => (
            <label
              key={f}
              className={cn(
                "relative inline-flex h-8 cursor-pointer items-center gap-2 rounded-full border px-3 text-[13px] transition-colors",
                "has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-ring/50",
                family === f
                  ? "border-foreground/70 bg-foreground text-background"
                  : "bg-card text-foreground hover:bg-muted",
              )}
            >
              <input
                type="radio"
                name="family"
                value={f}
                checked={family === f}
                onChange={() => onFamily(f)}
                className="sr-only"
              />
              {f !== "all" && (
                <span
                  aria-hidden
                  className="size-2 rounded-full"
                  style={{ background: `var(${EDGE_FAMILY_META[f].colorVar})` }}
                />
              )}
              {familyLabel(f, labelStyle)}
            </label>
          ))}
        </div>
      </fieldset>
    </section>
  );
}
