"use client";

import { ArrowUpRight, Boxes, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import { DiseaseCalls } from "@/components/calls/disease-calls";
import { EdgeTrustRow, NodeChip, OriginBadge, VusNotice } from "@/components/graph-ui";
import { useLens } from "@/components/providers/lens-provider";
import type { Schemas } from "@/lib/api";
import { EDGE_FAMILY_META, nodeTypeMeta, relationLabel } from "@/lib/graph/meta";
import { EDGE_FAMILIES, isVus, type EdgeFamily } from "@/lib/graph/types";
import { cn } from "@/lib/utils";

type NodeLite = Pick<Schemas.Node, "id" | "type" | "label">;

/** Human labels for the type-specific attributes that make a node actionable. */
const ATTR_LABEL: Record<string, string> = {
  country: "Country",
  city: "City",
  location: "Where",
  locations: "Where",
  kind: "Kind",
  phase: "Phase",
  status: "Status",
  funder: "Funder",
  institution: "Institution",
  affiliation: "Affiliation",
  amount: "Amount",
  start_date: "Start",
  end_date: "End",
  year: "Year",
  journal: "Journal",
  classification: "Classification",
  consequence: "Consequence",
  hgvs: "HGVS",
  registry: "Runs a registry",
  natural_history_study: "Natural history study",
  contact_url: "Contact",
  website: "Website",
  frequency: "Frequency",
};
const INTERNAL_ATTRS = new Set(["fixture", "placeholder_id", "gene", "x", "y"]);
const ACTIONABLE = new Set(["patient_org", "registry", "trial", "researcher", "grant", "doctor", "institution", "network"]);

function formatAttr(v: unknown): string {
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (Array.isArray(v)) return v.map(formatAttr).join(", ");
  if (typeof v === "string") return v.replace(/_/g, " ");
  if (v && typeof v === "object") {
    // Structured records (e.g. Orphanet prevalence rows) read as "key value" pairs.
    return Object.entries(v)
      .filter(([, x]) => x !== null && x !== undefined && x !== "")
      .map(([k, x]) => `${k.replace(/_/g, " ")} ${formatAttr(x)}`)
      .join(", ");
  }
  return String(v);
}

function safeHref(url: unknown): string | null {
  if (typeof url !== "string") return null;
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.toString() : null;
  } catch {
    return null;
  }
}

/** Node summary first, then its connections grouped by relation. */
export function NodePanel({
  detail,
  center,
  edges,
  nodes,
  highlightFamilies,
  hiddenFamilies,
  onEdge,
}: {
  detail: Schemas.NodeDetail | null;
  center: Schemas.Node;
  edges: Schemas.Edge[];
  nodes: Map<string, NodeLite>;
  highlightFamilies: EdgeFamily[];
  hiddenFamilies: Set<EdgeFamily>;
  onEdge: (id: string) => void;
}) {
  const { labelStyle } = useLens();
  const node = detail?.node ?? center;
  const meta = nodeTypeMeta(node.type);
  const attrs = Object.entries(node.attrs ?? {}).filter(([k, v]) => !INTERNAL_ATTRS.has(k) && v !== null && v !== "" && !/url$/i.test(k));
  const links = Object.entries(node.attrs ?? {}).filter(([k, v]) => /url$/i.test(k) && safeHref(v));
  const source = safeHref(node.url);
  const classification = detail?.classification ?? (node.attrs?.classification as string | undefined);
  const placeholder = node.attrs?.placeholder_id === true;
  const summary = detail?.summary ?? node.description;

  const groups = useMemo(() => {
    const direct = edges.filter((e) => e.source_id === center.id || e.target_id === center.id);
    const byRel = new Map<string, { relation: string; family: EdgeFamily; outgoing: boolean; items: Schemas.Edge[] }>();
    for (const e of direct) {
      const outgoing = e.source_id === center.id;
      const key = `${e.relation}|${outgoing ? "out" : "in"}`;
      const g = byRel.get(key) ?? { relation: e.relation, family: e.family, outgoing, items: [] };
      g.items.push(e);
      byRel.set(key, g);
    }
    const rank = (f: EdgeFamily) => {
      const i = highlightFamilies.indexOf(f);
      return i === -1 ? 10 + EDGE_FAMILIES.indexOf(f) : i;
    };
    return [...byRel.values()]
      .map((g) => ({ ...g, items: g.items.sort((a, b) => b.confidence - a.confidence) }))
      .sort((a, b) => rank(a.family) - rank(b.family) || b.items.length - a.items.length);
  }, [edges, center.id, highlightFamilies]);

  return (
    <div className="flex flex-col" data-testid="node-panel">
      <section aria-labelledby="node-summary-title" className="space-y-3 border-b px-4 py-4">
        <h2 id="node-summary-title" className="sr-only">
          Summary
        </h2>
        {isVus(classification) && <VusNotice />}
        {summary ? (
          <p className="text-sm leading-relaxed text-pretty">{summary}</p>
        ) : (
          <p className="text-sm text-muted-foreground">No description from the source yet.</p>
        )}
        {detail?.synonyms && detail.synonyms.length > 0 && (
          <p className="text-xs text-muted-foreground">
            <span className="font-medium text-foreground">Also called: </span>
            {detail.synonyms.join(" · ")}
          </p>
        )}

        {(ACTIONABLE.has(node.type) || attrs.length > 0) && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs" data-testid="node-attrs">
            <dt className="text-muted-foreground">What it is</dt>
            <dd>{meta.label[labelStyle]}</dd>
            {attrs.map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-muted-foreground">{ATTR_LABEL[k] ?? k.replace(/_/g, " ")}</dt>
                <dd>{formatAttr(v)}</dd>
              </div>
            ))}
            {links.map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-muted-foreground">{ATTR_LABEL[k] ?? "Link"}</dt>
                <dd>
                  <a href={safeHref(v)!} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer" className="inline-flex items-center gap-0.5 underline underline-offset-2">
                    {new URL(safeHref(v)!).hostname}
                    <ArrowUpRight className="size-3" aria-hidden />
                    <span className="sr-only">(opens in a new tab)</span>
                  </a>
                </dd>
              </div>
            ))}
          </dl>
        )}
        {["researcher", "doctor", "institution"].includes(node.type) && (
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
            <span>Public professional information only.</span>
            <Link
              href={`/about-data?entry=${encodeURIComponent(node.id)}#claim`}
              className="font-medium text-foreground underline underline-offset-2"
              data-testid="claim-entry-link"
            >
              Claim or remove this entry
            </Link>
          </p>
        )}

        <div className="flex flex-wrap items-center gap-2">
          {source && (
            <a
              href={source}
              target="_blank"
              rel="noopener noreferrer"
              referrerPolicy="no-referrer"
              className="inline-flex items-center gap-1 rounded-md border bg-background px-2 py-1 text-xs font-medium hover:bg-muted"
              data-testid="node-source-link"
            >
              Source record <ArrowUpRight className="size-3" aria-hidden />
              <span className="sr-only">(opens in a new tab)</span>
            </a>
          )}
          {placeholder && (
            <span className="rounded-md border border-dashed px-2 py-1 text-[11px] text-muted-foreground">
              Placeholder identifier (demo data)
            </span>
          )}
        </div>

        {detail?.cluster && node.type !== "cluster" && (
          <Link
            href={`/node/${encodeURIComponent(detail.cluster.id)}`}
            className="flex items-center gap-2.5 rounded-lg border bg-background/60 px-3 py-2 text-sm transition-colors hover:bg-muted"
            data-testid="node-cluster-link"
          >
            <Boxes className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                Mechanism group <OriginBadge origin="inferred" />
              </span>
              <span className="block truncate font-medium">{detail.cluster.label}</span>
            </span>
            <ChevronRight className="size-4 text-muted-foreground" aria-hidden />
          </Link>
        )}
      </section>

      {node.type === "disease" && <DiseaseCalls diseaseId={node.id} className="border-b px-4 py-4" />}

      {node.type === "cluster" && (
        <section aria-labelledby="node-members-title" className="border-b px-4 py-4" data-testid="cluster-members">
          <h2 id="node-members-title" className="mb-1 text-sm font-semibold">
            Members · {[...nodes.values()].filter((n) => n.id !== node.id).length}
          </h2>
          <p className="mb-2.5 text-xs text-muted-foreground">
            Grouped by analysis of shared genes, pathways and symptoms. Membership is a hypothesis.
          </p>
          <ul className="flex flex-wrap gap-1.5">
            {[...nodes.values()]
              .filter((n) => n.id !== node.id)
              .map((n) => (
                <li key={n.id}>
                  <NodeChip id={n.id} type={n.type} label={n.label} size="sm" />
                </li>
              ))}
          </ul>
        </section>
      )}

      <section aria-labelledby="node-connections-title" className="px-4 py-4">
        <h2 id="node-connections-title" className="mb-3 text-sm font-semibold">
          Connections
        </h2>
        {groups.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {node.type === "cluster" ? "A group has members rather than sourced connections of its own." : "No direct connections recorded yet."}
          </p>
        )}
        <div className="space-y-4">
          {groups.map((g) => {
            const fam = EDGE_FAMILY_META[g.family];
            const hidden = hiddenFamilies.has(g.family);
            const heading = g.outgoing
              ? `${node.label} ${relationLabel(g.relation, labelStyle)}`
              : `${relationLabel(g.relation, labelStyle)} ${node.label}`;
            return (
              <section key={`${g.relation}-${g.outgoing}`} aria-label={heading} className={cn(hidden && "opacity-60")} data-testid="relation-group">
                <h3 className="mb-1.5 flex items-center gap-2 text-xs font-medium">
                  <span className="size-2 shrink-0 rounded-full" style={{ background: `var(${fam.colorVar})` }} aria-hidden />
                  <span className={cn("min-w-0 flex-1", labelStyle === "technical" && "font-mono")} data-testid="relation-heading">
                    {g.outgoing ? "" : "← "}
                    {relationLabel(g.relation, labelStyle)}
                  </span>
                  <span className="font-mono tabular text-muted-foreground">{g.items.length}</span>
                </h3>
                <ul className="space-y-1.5">
                  {g.items.map((e) => {
                    const otherId = e.source_id === center.id ? e.target_id : e.source_id;
                    const other = nodes.get(otherId);
                    return (
                      <li key={e.id} className="rounded-lg border bg-background/50 px-2.5 py-2">
                        <div className="flex items-center gap-2">
                          {other ? (
                            <NodeChip id={other.id} type={other.type} label={other.label} size="sm" className="min-w-0 border-0 bg-transparent px-0" />
                          ) : (
                            <span className="font-mono text-xs">{otherId}</span>
                          )}
                          <button
                            type="button"
                            onClick={() => onEdge(e.id)}
                            className="ml-auto shrink-0 rounded px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground underline-offset-2 outline-none hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring"
                            data-testid="open-edge"
                          >
                            Sources
                            <span className="sr-only"> for {other?.label ?? otherId}</span>
                          </button>
                        </div>
                        <EdgeTrustRow edge={e} className="mt-1" />
                      </li>
                    );
                  })}
                </ul>
              </section>
            );
          })}
        </div>
      </section>
    </div>
  );
}
