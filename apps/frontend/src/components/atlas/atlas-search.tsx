"use client";

import { cn } from "@/lib/utils";

import type { AtlasSearchProps } from "./atlas-props";

/** "Search the map": combobox centred at the top of the canvas. */
export function AtlasSearch({ className }: AtlasSearchProps) {
  return <div data-testid="atlas-search" data-tour="search" className={cn("w-full max-w-md", className)} />;
}
