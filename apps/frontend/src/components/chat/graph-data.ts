"use client";

import { useEffect, useMemo, useState } from "react";

import { apiFetch } from "@/lib/api/fetch";
import type { Schemas } from "@/lib/api";

type EdgeEvidence = Schemas.EdgeEvidence;
type NodeDetail = Schemas.NodeDetail;

/**
 * Cards and claims carry only node and edge IDs; the details come from the
 * public graph endpoints (`GET /edge/{id}/evidence`, `GET /node/{id}`).
 * Cached per page load; failures are not cached so a later view retries.
 */
const edgeCache = new Map<string, Promise<EdgeEvidence | null>>();
const nodeCache = new Map<string, Promise<NodeDetail | null>>();

function cached<T>(cache: Map<string, Promise<T | null>>, key: string, load: () => Promise<T>) {
  let p = cache.get(key);
  if (!p) {
    p = load().catch(() => {
      cache.delete(key);
      return null;
    });
    cache.set(key, p);
  }
  return p;
}

export function loadEdge(id: string) {
  return cached(edgeCache, id, () =>
    apiFetch<EdgeEvidence>(`/edge/${encodeURIComponent(id)}/evidence`, { quiet: true }),
  );
}

export function loadNode(id: string) {
  return cached(nodeCache, id, () => apiFetch<NodeDetail>(`/node/${encodeURIComponent(id)}`, { quiet: true }));
}

/** `undefined` while loading, `null` if it could not be loaded. */
export type Loaded<T> = Record<string, T | null | undefined>;

function useLoaded<T>(ids: string[], load: (id: string) => Promise<T | null>): Loaded<T> {
  const key = ids.join("|");
  const [state, setState] = useState<{ key: string; data: Loaded<T> }>({ key: "", data: {} });
  useEffect(() => {
    let alive = true;
    const list = key ? key.split("|") : [];
    Promise.all(list.map(async (id) => [id, await load(id)] as const)).then((entries) => {
      if (alive) setState({ key, data: Object.fromEntries(entries) });
    });
    return () => {
      alive = false;
    };
  }, [key, load]);
  return state.key === key ? state.data : {};
}

export function useEdges(ids: string[]) {
  const unique = useMemo(() => [...new Set(ids)], [ids]);
  return useLoaded(unique, loadEdge);
}

export function useNodes(ids: string[]) {
  const unique = useMemo(() => [...new Set(ids)], [ids]);
  return useLoaded(unique, loadNode);
}
