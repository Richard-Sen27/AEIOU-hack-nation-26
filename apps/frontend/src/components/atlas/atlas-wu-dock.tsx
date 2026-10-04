"use client";

import { cn } from "@/lib/utils";

import type { AtlasWuDockProps } from "./atlas-props";

/** Dr. Wu dock: a floating card bottom-left of the Atlas canvas. */
export function AtlasWuDock({ className }: AtlasWuDockProps) {
  return (
    <div className={cn("rounded-xl border bg-card p-2 text-sm", className)} data-testid="atlas-wu-dock" data-tour="wu">
      Ask Dr. Wu
    </div>
  );
}
