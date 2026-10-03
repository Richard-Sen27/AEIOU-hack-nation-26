"use client";

import { List, Waypoints } from "lucide-react";

import { cn } from "@/lib/utils";

export type ViewMode = "graph" | "list";

/**
 * Visible switch between the canvas graph and its list/table equivalent.
 * The canvas is invisible to screen readers, so the list is a first-class
 * view, not a hidden fallback. Radio semantics, arrow keys move.
 */
export function ViewToggle({
  value,
  onChange,
  graphLabel = "Map",
  className,
}: {
  value: ViewMode;
  onChange: (v: ViewMode) => void;
  graphLabel?: string;
  className?: string;
}) {
  const items: Array<{ v: ViewMode; label: string; Icon: typeof List }> = [
    { v: "graph", label: graphLabel, Icon: Waypoints },
    { v: "list", label: "List", Icon: List },
  ];
  return (
    <div
      role="radiogroup"
      aria-label="How to show the graph"
      className={cn("inline-flex h-8 items-center rounded-lg border bg-card p-0.5", className)}
      data-testid="view-toggle"
      onKeyDown={(e) => {
        if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) {
          e.preventDefault();
          const next = value === "graph" ? "list" : "graph";
          onChange(next);
          (e.currentTarget.querySelector(`[data-value="${next}"]`) as HTMLElement | null)?.focus();
        }
      }}
    >
      {items.map(({ v, label, Icon }) => {
        const active = value === v;
        return (
          <button
            key={v}
            type="button"
            role="radio"
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            data-value={v}
            onClick={() => onChange(v)}
            className={cn(
              "inline-flex h-full items-center gap-1.5 rounded-md px-2.5 text-[13px] font-medium text-muted-foreground transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring",
              active ? "bg-muted text-foreground shadow-xs" : "hover:text-foreground",
            )}
          >
            <Icon className="size-3.5" aria-hidden />
            {label}
          </button>
        );
      })}
    </div>
  );
}
