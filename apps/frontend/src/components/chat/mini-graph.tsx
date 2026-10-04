"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { atlasHandoffClick } from "@/components/atlas/atlas-handoff";
import { useLens } from "@/components/providers/lens-provider";
import { nodeTypeMeta, relationLabel } from "@/lib/graph/meta";
import { edgeVisual, svgDashArray } from "@/lib/graph/style";
import type { Origin } from "@/lib/graph/types";

import type { Loaded } from "./graph-data";
import type { EdgeEvidence, NodeDetail } from "./types";

type GNode = { id: string; type: string; label: string };

const W = 640;
const H = 300;

function truncate(s: string, n: number) {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

/**
 * A small inline graph of the card's nodes and edges with the same line
 * rules as every other view: colour = edge family, solid = data, dashed =
 * hypothesis, dotted = patient-reported, width = confidence, flagged edges
 * marked. The first node sits in the middle, the rest on a ring.
 */
export function MiniGraph({
  nodeIds,
  edgeIds,
  edges,
  nodes,
}: {
  nodeIds: string[];
  edgeIds: string[];
  edges: Loaded<EdgeEvidence>;
  nodes: Loaded<NodeDetail>;
}) {
  const router = useRouter();
  const { labelStyle } = useLens();
  const byId = new Map<string, GNode>();
  const add = (n: GNode | undefined | null) => n && !byId.has(n.id) && byId.set(n.id, { id: n.id, type: n.type, label: n.label });
  nodeIds.forEach((id) => add(nodes[id]?.node ?? null));
  const loadedEdges = edgeIds.map((id) => edges[id]).filter((e): e is EdgeEvidence => !!e);
  loadedEdges.forEach((e) => {
    add(e.source);
    add(e.target);
  });
  // Card order first, then anything only reachable through edges.
  const order = [...nodeIds.filter((id) => byId.has(id)), ...[...byId.keys()].filter((id) => !nodeIds.includes(id))];
  const list = order.map((id) => byId.get(id)!);

  const pos = new Map<string, { x: number; y: number }>();
  const cx = W / 2;
  const cy = H / 2;
  if (list.length === 1) pos.set(list[0].id, { x: cx, y: cy });
  else if (list.length > 1) {
    const center = list.length > 3;
    if (center) pos.set(list[0].id, { x: cx, y: cy });
    const ring = center ? list.slice(1) : list;
    ring.forEach((n, i) => {
      const a = -Math.PI / 2 + (2 * Math.PI * i) / ring.length;
      pos.set(n.id, { x: cx + Math.cos(a) * (W / 2 - 120), y: cy + Math.sin(a) * (H / 2 - 42) });
    });
  }

  if (list.length === 0) {
    return <div className="h-40 animate-pulse rounded-lg bg-muted motion-reduce:animate-none" aria-label="Loading graph" />;
  }

  const description = loadedEdges
    .map((e) => `${e.source.label} ${relationLabel(e.edge.relation, labelStyle)} ${e.target.label}`)
    .join("; ");

  return (
    <figure className="space-y-2" data-testid="mini-graph">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto max-h-80 w-full rounded-lg border bg-[var(--graph-bg)]"
        role="group"
        aria-label={`Graph of ${list.length} items${description ? `: ${description}` : ""}`}
      >
        {loadedEdges.map((e) => {
          const a = pos.get(e.source.id);
          const b = pos.get(e.target.id);
          if (!a || !b) return null;
          const v = edgeVisual({ family: e.edge.family, origin: e.edge.origin as Origin, status: e.edge.status, confidence: e.edge.confidence });
          return (
            <g key={e.edge.id} data-edge-origin={e.edge.origin}>
              <line
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke={v.color}
                strokeOpacity={v.opacity}
                strokeWidth={v.width * 1.3}
                strokeDasharray={svgDashArray(v.line)}
                strokeLinecap="round"
              />
              {v.flagged && (
                <circle cx={(a.x + b.x) / 2} cy={(a.y + b.y) / 2} r={4.5} fill="var(--status-flag)" stroke="var(--card)" strokeWidth={1.5}>
                  <title>Pending or under review</title>
                </circle>
              )}
            </g>
          );
        })}
        {list.map((n) => {
          const p = pos.get(n.id)!;
          const meta = nodeTypeMeta(n.type);
          const label = `${n.label} (${meta.label[labelStyle]})`;
          return (
            <a
              key={n.id}
              href={`/node/${encodeURIComponent(n.id)}`}
              onClick={(ev) => {
                ev.preventDefault();
                router.push(`/node/${encodeURIComponent(n.id)}`);
              }}
              aria-label={label}
              className="outline-none [&:focus-visible>circle:first-child]:stroke-[var(--ring)]"
            >
              <circle cx={p.x} cy={p.y} r={11} fill={`var(${meta.colorVar})`} stroke="var(--card)" strokeWidth={2.5} />
              <text
                x={p.x}
                y={p.y + 25}
                textAnchor="middle"
                className="fill-foreground text-[11px] font-medium"
                style={{ paintOrder: "stroke", stroke: "var(--graph-bg)", strokeWidth: 3 }}
              >
                {truncate(n.label, 30)}
              </text>
              <title>{label}</title>
            </a>
          );
        })}
      </svg>
      <figcaption className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <svg width="20" height="6" aria-hidden><line x1="1" y1="3" x2="19" y2="3" stroke="currentColor" strokeWidth="2" /></svg>
          Data
        </span>
        <span className="inline-flex items-center gap-1.5">
          <svg width="20" height="6" aria-hidden><line x1="1" y1="3" x2="19" y2="3" stroke="currentColor" strokeWidth="2" strokeDasharray="6 4" /></svg>
          Hypothesis
        </span>
        <span className="inline-flex items-center gap-1.5">
          <svg width="20" height="6" aria-hidden><line x1="1" y1="3" x2="19" y2="3" stroke="currentColor" strokeWidth="2" strokeDasharray="1.5 3" /></svg>
          Patient-reported
        </span>
        <span>Thicker line = more confident</span>
        {list[0] && (
          <Link
            href="/atlas"
            onClick={atlasHandoffClick({ nodeIds: list.map((n) => n.id), edgeIds })}
            className="ml-auto font-medium text-foreground underline-offset-2 hover:underline">
            Open in Atlas
          </Link>
        )}
      </figcaption>
    </figure>
  );
}
