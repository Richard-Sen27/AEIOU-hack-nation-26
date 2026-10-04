"use client";

import { cn } from "@/lib/utils";

import type { AtlasOutlineProps } from "./atlas-props";

/** Accessible treeview alternative to the canvas. */
export function AtlasOutline({ className }: AtlasOutlineProps) {
  return <div data-testid="atlas-outline" className={cn("flex h-full min-h-0 flex-col", className)} />;
}
