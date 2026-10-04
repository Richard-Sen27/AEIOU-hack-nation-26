"use client";

import { cn } from "@/lib/utils";

import type { AtlasPanelProps } from "./atlas-props";

/** Right-hand summary panel for the node selected on the Atlas. */
export function AtlasPanel({ nodeId, className }: AtlasPanelProps) {
  return (
    <aside className={cn("flex flex-col overflow-hidden rounded-xl border bg-card", className)} data-testid="atlas-panel">
      <p className="p-4 text-sm text-muted-foreground">{nodeId ?? "Search or click a dot"}</p>
    </aside>
  );
}
