"use client";

import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { readGraphTheme, type GraphTheme } from "./style";

/**
 * Resolved graph colours for canvas/WebGL renderers; `null` until mounted.
 * Re-reads whenever the light/dark theme changes.
 */
export function useGraphTheme(): GraphTheme | null {
  const { resolvedTheme } = useTheme();
  const [theme, setTheme] = useState<GraphTheme | null>(null);
  useEffect(() => {
    // next-themes toggles the class synchronously; read on the next frame.
    const id = requestAnimationFrame(() => setTheme(readGraphTheme()));
    return () => cancelAnimationFrame(id);
  }, [resolvedTheme]);
  return theme;
}
