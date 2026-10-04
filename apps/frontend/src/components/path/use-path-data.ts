"use client";

import { useEffect, useState } from "react";

import { trackEvent } from "@/lib/analytics";
import { findPath, getNode } from "@/lib/api";
import type { ApiError } from "@/lib/api/errors";

import type { ApiNode, Family, PathResponse } from "./types";

export type PathQueryState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; data: PathResponse }
  | { kind: "error"; error: ApiError };

/** `GET /path` for the current from/to/family. Errors are handled by the page (quiet). */
export function usePathQuery(from: string | null, to: string | null, family: Family, attempt = 0) {
  const [state, setState] = useState<PathQueryState>({ kind: "idle" });

  useEffect(() => {
    if (!from || !to) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- derived from the URL
      setState({ kind: "idle" });
      return;
    }
    const ctrl = new AbortController();
    setState({ kind: "loading" });
    findPath({
      query: { from, to, family, k: 3 },
      signal: ctrl.signal,
      meta: { quiet: true },
    }).then(({ data, error }) => {
      if (ctrl.signal.aborted) return;
      if (error) {
        const err = error as unknown as ApiError;
        if (err.code === "aborted") return;
        setState({ kind: "error", error: err });
      } else if (data) {
        setState({ kind: "ready", data: data as PathResponse });
        trackEvent("path_search");
      }
    });
    return () => ctrl.abort();
  }, [from, to, family, attempt]);

  return state;
}

const nodeCache = new Map<string, ApiNode | null>();

/** Label and type for a prefilled node id (`GET /node/{id}`), cached for the session. */
export function useNode(id: string | null, known?: ApiNode | null) {
  const [node, setNode] = useState<ApiNode | null>(() => (id ? (nodeCache.get(id) ?? null) : null));

  useEffect(() => {
    if (!id) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- derived from the URL
      setNode(null);
      return;
    }
    if (known && known.id === id) {
      nodeCache.set(id, known);
      setNode(known);
      return;
    }
    if (nodeCache.has(id)) {
      setNode(nodeCache.get(id) ?? null);
      return;
    }
    const ctrl = new AbortController();
    getNode({ path: { node_id: id }, signal: ctrl.signal, meta: { quiet: true } }).then(({ data }) => {
      if (ctrl.signal.aborted) return;
      const n = (data as { node?: ApiNode } | undefined)?.node ?? null;
      nodeCache.set(id, n);
      setNode(n);
    });
    return () => ctrl.abort();
  }, [id, known]);

  return node;
}

/** Remember a node the user picked so the URL round-trip doesn't refetch it. */
export function rememberNode(node: ApiNode) {
  nodeCache.set(node.id, node);
}
