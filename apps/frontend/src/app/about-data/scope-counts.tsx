"use client";

import { useEffect, useState } from "react";

import { getStats, type Schemas } from "@/lib/api";

const fmt = (n: number) => n.toLocaleString("en");

/** The inclusion rule in one sentence, with live counts from `GET /stats` when they load. */
export function ScopeCounts() {
  const [stats, setStats] = useState<Schemas.AtlasStats | null>(null);
  useEffect(() => {
    let alive = true;
    getStats({ meta: { quiet: true } })
      .then(({ data }) => alive && data && setStats(data))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);
  return (
    <p data-testid="scope-rule">
      The atlas includes every rare disease with a MONDO identifier, at least one known gene and one recorded symptom,
      leaving out susceptibilities and broad disease groups
      {stats ? (
        <span data-testid="scope-counts">
          : {fmt(stats.diseases)} diseases, {fmt(stats.genes)} genes and {fmt(stats.symptoms)} symptoms right now.
        </span>
      ) : (
        "."
      )}
    </p>
  );
}
