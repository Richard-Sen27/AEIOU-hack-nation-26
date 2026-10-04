"use client";

import { ArrowUpRight, BookOpen, ChevronDown, CircleSlash, Database, FlaskConical, Globe, Landmark, Sigma } from "lucide-react";
import { useMemo, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { useEdges, useNodes, type Loaded } from "./graph-data";
import type { EdgeEvidence } from "./types";

/*
 * Sources in words a layperson understands: each cited record is shown by what it is (a paper
 * with its title and year, a trial with its registry number, a database such as Orphanet or
 * ClinVar) with a link, never as a raw id or an internal relation name.
 */

type Evidence = EdgeEvidence["supporting"][number];
type GraphNode = EdgeEvidence["source"];

export type SourceKind = "paper" | "trial" | "grant" | "database" | "website" | "computed";

export type SourceDoc = {
  key: string;
  kind: SourceKind;
  title: string;
  /** Short second line: year, registry number, what the database is. */
  detail: string | null;
  href: string | null;
  contradicts: boolean;
  /** 1-based numbers of the statements this source backs (when given). */
  refs: number[];
};

const DATABASES: Record<string, { name: string; what: string }> = {
  hpo: { name: "Human Phenotype Ontology", what: "symptom records" },
  clinvar: { name: "ClinVar", what: "genetic variant records" },
  orphanet: { name: "Orphanet", what: "rare disease database" },
  omim: { name: "OMIM", what: "genetic disease catalogue" },
  clingen: { name: "ClinGen", what: "gene–disease reviews" },
  gene2phenotype: { name: "Gene2Phenotype", what: "gene–disease records" },
  mondo: { name: "Mondo", what: "disease classification" },
  hgnc: { name: "HGNC", what: "gene names" },
  go: { name: "Gene Ontology", what: "what genes do" },
  reactome: { name: "Reactome", what: "biological pathways" },
  mane: { name: "NCBI MANE", what: "gene positions" },
  uniprot: { name: "UniProt", what: "protein records" },
  fixture: { name: "Example data", what: "test data, not a real source" },
};

const PMID = /^(?:PMID:)?(\d{4,9})$/i;

/** The paper a PubMed record points to, if it is one of the edge's own nodes. */
function paperNode(edge: EdgeEvidence, pmid: string): GraphNode | null {
  for (const n of [edge.source, edge.target]) if (n.type === "paper" && n.id === `PMID:${pmid}`) return n;
  return null;
}

function endpoint(edge: EdgeEvidence, type: string, id?: string | null): GraphNode | null {
  for (const n of [edge.source, edge.target]) if (n.type === type && (!id || n.id.endsWith(id))) return n;
  return null;
}

function hostname(url: string): string | null {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

/** PubMed ids cited without their paper among the edge's nodes (their title needs a lookup). */
export function paperIdsToLoad(edges: EdgeEvidence[]): string[] {
  const ids = new Set<string>();
  for (const edge of edges) {
    for (const ev of [...edge.supporting, ...edge.contradicting]) {
      const m = ev.source_type === "pubmed" ? PMID.exec(ev.source_id ?? "") : null;
      if (m && !paperNode(edge, m[1])) ids.add(`PMID:${m[1]}`);
    }
  }
  return [...ids];
}

/** One evidence record as what it is; `papers` holds looked-up paper nodes by id. */
export function describeEvidence(ev: Evidence, edge: EdgeEvidence, papers: Loaded<{ node: GraphNode }> = {}): SourceDoc {
  const type = ev.source_type.toLowerCase();
  const sid = ev.source_id ?? "";
  const base = { href: ev.url ?? null, contradicts: ev.polarity === "contradicts", refs: [] as number[] };
  const pmid = type === "pubmed" ? PMID.exec(sid)?.[1] : undefined;
  if (pmid) {
    const node = paperNode(edge, pmid) ?? papers[`PMID:${pmid}`]?.node ?? null;
    const year = node?.attrs?.year as number | undefined;
    return {
      ...base,
      key: `pubmed:${pmid}`,
      kind: "paper",
      title: node?.label ?? "A paper on PubMed",
      detail: [year, "Paper, PubMed"].filter(Boolean).join(" · "),
      href: ev.url ?? `https://pubmed.ncbi.nlm.nih.gov/${pmid}/`,
    };
  }
  if (type === "clinicaltrials") {
    const trial = endpoint(edge, "trial", sid);
    return { ...base, key: `trial:${sid}`, kind: "trial", title: trial?.label ?? "A clinical trial", detail: `Clinical trial ${sid}, ClinicalTrials.gov` };
  }
  if (type === "reporter") {
    const grant = endpoint(edge, "grant", sid);
    return { ...base, key: `grant:${sid}`, kind: "grant", title: grant?.label ?? "A research grant", detail: `NIH grant ${sid}` };
  }
  if (type === "patient_org_site") {
    const org = endpoint(edge, "patient_org");
    const host = ev.url ? hostname(ev.url) : null;
    return { ...base, key: `site:${ev.url ?? sid}`, kind: "website", title: org ? `${org.label} website` : "Patient organisation website", detail: host };
  }
  if (type === "analytics" || (ev.tier === "computed" && !DATABASES[type])) {
    return { ...base, key: `computed:${edge.edge.id}`, kind: "computed", title: "Worked out by Amber from the data above", detail: "A hypothesis, not a finding of a study", href: null };
  }
  const db = DATABASES[type];
  const name = db?.name ?? ev.source_type.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
  // One row per database record; the same database for many links collapses by its record.
  return { ...base, key: `${type}:${sid || ev.url || edge.edge.id}`, kind: "database", title: name, detail: db?.what ?? null };
}

/** The distinct sources behind a set of links, with the statement numbers each one backs. */
export function collectSources(
  groups: Array<{ edgeIds: string[]; ref?: number }>,
  edges: Loaded<EdgeEvidence>,
  papers: Loaded<{ node: GraphNode }>,
): SourceDoc[] {
  const out = new Map<string, SourceDoc>();
  for (const g of groups) {
    for (const id of g.edgeIds) {
      const edge = edges[id];
      if (!edge) continue;
      for (const ev of [...edge.supporting, ...edge.contradicting]) {
        const doc = describeEvidence(ev, edge, papers);
        const have = out.get(doc.key);
        const target = have ?? doc;
        if (!have) out.set(doc.key, doc);
        if (doc.contradicts) target.contradicts = true;
        if (g.ref && !target.refs.includes(g.ref)) target.refs.push(g.ref);
      }
    }
  }
  // Papers, trials and grants first, then databases and websites, Amber's own work last.
  const order: SourceKind[] = ["paper", "trial", "grant", "database", "website", "computed"];
  return [...out.values()].sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind));
}

const KIND_ICON: Record<SourceKind, typeof BookOpen> = {
  paper: BookOpen,
  trial: FlaskConical,
  grant: Landmark,
  database: Database,
  website: Globe,
  computed: Sigma,
};

export function SourceRow({ doc }: { doc: SourceDoc }) {
  const Icon = KIND_ICON[doc.kind];
  const title = (
    <>
      <span>{doc.title}</span>
      {doc.href && (
        <>
          <ArrowUpRight className="ml-0.5 inline size-3 align-[-1px]" aria-hidden />
          <span className="sr-only"> (opens in a new tab)</span>
        </>
      )}
    </>
  );
  return (
    <li className="flex items-start gap-2 py-1.5" data-testid="source" data-kind={doc.kind}>
      <Icon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" aria-hidden />
      <div className="min-w-0 flex-1 text-[13px] leading-snug">
        {doc.href ? (
          <a href={doc.href} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer" className="font-medium underline-offset-2 hover:underline">
            {title}
          </a>
        ) : (
          <span className="font-medium">{title}</span>
        )}
        <p className="text-xs text-muted-foreground">
          {[doc.detail, doc.refs.length ? `for ${doc.refs.join(", ")}` : null].filter(Boolean).join(" · ")}
          {doc.contradicts && (
            <span className="ml-1 inline-flex items-center gap-0.5 text-confidence-low">
              <CircleSlash className="size-3" aria-hidden /> disagrees
            </span>
          )}
        </p>
      </div>
    </li>
  );
}

type Groups = Array<{ edgeIds: string[]; ref?: number }>;

/** Loads the links (and the titles of papers they cite) and returns their distinct sources. */
export function useSources(groups: Groups, { titles = true }: { titles?: boolean } = {}) {
  const ids = useMemo(() => groups.flatMap((g) => g.edgeIds), [groups]);
  const edges = useEdges(ids);
  const loadedEdges = useMemo(() => ids.map((id) => edges[id]).filter((e): e is EdgeEvidence => !!e), [ids, edges]);
  const paperIds = useMemo(() => (titles ? paperIdsToLoad(loadedEdges).slice(0, 12) : []), [loadedEdges, titles]);
  const papers = useNodes(paperIds);
  const docs = useMemo(() => collectSources(groups, edges, papers), [groups, edges, papers]);
  const loading = ids.some((id) => edges[id] === undefined);
  return { docs, loading, edges };
}

function DocList({ docs, loading, className }: { docs: SourceDoc[]; loading: boolean; className?: string }) {
  if (loading && docs.length === 0) {
    return (
      <div className={cn("space-y-2", className)} aria-busy="true">
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-4 w-1/2" />
      </div>
    );
  }
  if (docs.length === 0) return <p className={cn("text-xs text-muted-foreground", className)}>The sources could not be loaded right now.</p>;
  return (
    <ul className={cn("divide-y", className)} data-testid="sources-list">
      {docs.map((d) => (
        <SourceRow key={d.key} doc={d} />
      ))}
    </ul>
  );
}

/** The tidy list of sources behind the given links (loads them; papers get their titles). */
export function SourcesList({ groups, className }: { groups: Groups; className?: string }) {
  const { docs, loading } = useSources(groups);
  return <DocList docs={docs} loading={loading} className={className} />;
}

/**
 * One short line per answer, "Sources · N", collapsed by default; it opens the tidy list.
 * N is the number of distinct sources (the cited links' count while they load).
 */
export function SourcesToggle({ groups, defaultOpen = false }: { groups: Groups; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const { docs, loading } = useSources(groups, { titles: open });
  const links = new Set(groups.flatMap((g) => g.edgeIds)).size;
  if (links === 0) return null;
  const count = loading && docs.length === 0 ? links : docs.length;
  return (
    <div data-testid="sources">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="inline-flex h-7 items-center gap-1 rounded-md px-1.5 text-xs font-medium text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ChevronDown className={cn("size-3.5 transition-transform motion-reduce:transition-none", open && "rotate-180")} aria-hidden />
        {open ? "Hide sources" : "Sources"} · <span className="tabular-nums">{count}</span>
      </button>
      {open && (
        <div className="mt-1 rounded-lg border bg-card/60 px-3 py-1.5">
          <p className="pt-1 text-xs text-muted-foreground">
            Where these statements come from: papers, trials and public databases. Numbers refer to the statements above.
          </p>
          <DocList docs={docs} loading={loading} />
        </div>
      )}
    </div>
  );
}
