"use client";

import { useEffect, useState } from "react";

import { getAtlasTree, getStats, type Schemas } from "@/lib/api";

import { buildAtlasPreview, type AtlasPreviewModel } from "./atlas-preview-model";

/** Run after hydration, when the browser is idle (Safari has no requestIdleCallback). */
function whenIdle(fn: () => void) {
  if (typeof window.requestIdleCallback === "function") window.requestIdleCallback(fn, { timeout: 1500 });
  else window.setTimeout(fn, 200);
}

function once<T>(load: () => Promise<T | null>): () => Promise<T | null> {
  let promise: Promise<T | null> | null = null;
  return () => {
    promise ??= new Promise<T | null>((resolve) => whenIdle(() => load().then(resolve, () => resolve(null))));
    return promise;
  };
}

// One fetch per page load, shared by the hero and the graph section. Errors stay quiet:
// the frames and the "Open the Atlas" link remain.
const loadPreview = once(async () => {
  const { data, error } = await getAtlasTree({ meta: { quiet: true } });
  if (error !== undefined || !data) return null;
  return buildAtlasPreview(data);
});

const loadStats = once(async () => {
  const { data, error } = await getStats({ meta: { quiet: true } });
  return error !== undefined || !data ? null : data;
});

export type Loaded<T> = { status: "loading" } | { status: "ready"; data: T } | { status: "error" };

function useOnce<T>(load: () => Promise<T | null>): Loaded<T> {
  const [state, setState] = useState<Loaded<T>>({ status: "loading" });
  useEffect(() => {
    let live = true;
    void load().then((data) => {
      if (live) setState(data ? { status: "ready", data } : { status: "error" });
    });
    return () => {
      live = false;
    };
  }, [load]);
  return state;
}

/** True once the element has come within `margin` of the viewport (stays true). */
export function useInView<T extends Element>(ref: React.RefObject<T | null>, margin = "300px"): boolean {
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || seen) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) setSeen(true);
      },
      { rootMargin: margin },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [ref, margin, seen]);
  return seen;
}

/** The live Atlas tree, transformed for the landing preview. */
export function useAtlasPreview(): Loaded<AtlasPreviewModel> {
  return useOnce(loadPreview);
}

/** Headline counts from `GET /stats` (cached by the API per data version). */
export function useLandingStats(): Loaded<Schemas.AtlasStats> {
  return useOnce(loadStats);
}
