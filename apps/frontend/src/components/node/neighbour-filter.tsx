"use client";

import { Search, X } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Filters the loaded neighbourhood of this node (not the atlas): one plain
 * bordered input, like the profile's entity pickers. Escape or the clear
 * button empties it. Nothing typed here leaves the browser.
 */
export function NeighbourFilter({
  value,
  onChange,
  matches,
  total,
  className,
}: {
  value: string;
  onChange: (v: string) => void;
  matches: number;
  total: number;
  className?: string;
}) {
  const active = value.trim().length > 0;
  return (
    <div
      className={cn(
        "flex h-8 items-center gap-1.5 rounded-lg border border-input bg-transparent pr-1 pl-2.5 transition-colors focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50 dark:bg-input/30",
        className,
      )}
      data-testid="neighbour-filter"
    >
      <Search className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape" && value) {
            e.preventDefault();
            e.stopPropagation();
            onChange("");
          }
        }}
        placeholder="Filter connections"
        aria-label="Filter these connections"
        autoComplete="off"
        spellCheck={false}
        className="h-full min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-muted-foreground sm:text-sm"
      />
      {active && (
        <>
          <span className="shrink-0 text-xs text-muted-foreground tabular-nums" aria-live="polite" data-testid="filter-count">
            {matches} of {total}
          </span>
          <button
            type="button"
            onClick={() => onChange("")}
            className="flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
            aria-label="Clear the filter"
          >
            <X className="size-3.5" aria-hidden />
          </button>
        </>
      )}
    </div>
  );
}
