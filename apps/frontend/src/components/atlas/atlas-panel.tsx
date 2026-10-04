"use client";

import {
  Archive,
  ArrowRight,
  Bot,
  ChevronRight,
  ExternalLink,
  FolderTree,
  Info,
  RefreshCw,
  Route,
  Sparkles,
  TriangleAlert,
  X,
} from "lucide-react";
import Link from "next/link";
import { Fragment, useEffect, useMemo, useState } from "react";

import { FollowButton } from "@/components/follows/follow-button";
import { ConfidenceBadge, OriginBadge, StatusFlag, VusNotice } from "@/components/graph-ui";
import { useGate } from "@/components/providers/gate-provider";
import { useLens } from "@/components/providers/lens-provider";
import { useSession } from "@/components/providers/session-provider";
import { AiDisclosure } from "@/components/shell/ai-disclosure";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { announce } from "@/lib/a11y";
import { getAtlasSummary, getNeighborhood, streamSSE, type Schemas } from "@/lib/api";
import type { ApiError } from "@/lib/api/errors";
import { nodeTypeMeta, type LabelStyle } from "@/lib/graph/meta";
import { cn } from "@/lib/utils";

import { loadEdge } from "@/components/chat/graph-data";

import { categoryLabel } from "./atlas-categories";
import { idLinks, OffMapMark } from "./atlas-offmap";
import type { AtlasPanelProps } from "./atlas-props";
import { ancestorsOf, type AtlasTreeNode, type GroupBasis, type TreeIndex } from "./tree-model";

type Summary = Schemas.AtlasSummary;
type SummaryItem = Schemas.SummaryItem;
type SectionKey = Schemas.SummarySectionKey;
type ExplainEvent = Schemas.ExplainEvent;
type ExplainFinal = Schemas.ExplainFinalEvent;

/** Human heading per summary lens. Exhaustive over the SDK's section keys. */
const SECTION_HEADING: Record<SectionKey, string> = {
  clusters: "Mechanism group",
  diseases: "Conditions",
  similar_diseases: "Similar conditions",
  genes: "Genes",
  variants: "Gene changes",
  mechanisms: "Mechanisms",
  pathways: "Body processes",
  symptoms: "Symptoms",
  researchers: "Leading researchers",
  doctors: "Doctors",
  institutions: "Hospitals & universities",
  papers: "Papers",
  trials: "Trials",
  grants: "Funding",
  patient_orgs: "Patient groups",
  registries: "Registries & studies",
  networks: "Networks",
  claims: "Claims",
};

/** Public professional information about people and institutions (Art. 14 notice). */
const PEOPLE = new Set(["researcher", "doctor", "institution"]);

/** The panel shell: a fixed header, one scrolling body, an optional fixed footer. */
function Shell({
  className,
  header,
  footer,
  children,
  busy,
}: {
  className?: string;
  header?: React.ReactNode;
  footer?: React.ReactNode;
  children: React.ReactNode;
  busy?: boolean;
}) {
  return (
    <aside
      aria-labelledby={header ? "atlas-panel-title" : undefined}
      aria-label={header ? undefined : "Summary"}
      aria-busy={busy || undefined}
      className={cn("flex min-h-0 flex-col overflow-hidden rounded-xl border bg-card/95 shadow-lg backdrop-blur", className)}
      data-testid="atlas-panel"
    >
      {header}
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain" data-testid="atlas-panel-body">
        {children}
      </div>
      {footer}
    </aside>
  );
}

function Breadcrumb({ index, nodeId, onSelect }: { index: TreeIndex; nodeId: string; onSelect: (id: string) => void }) {
  const { labelStyle } = useLens();
  const crumbs = ancestorsOf(index, nodeId).filter((n) => n.kind !== "root");
  if (crumbs.length === 0) return null;
  return (
    <nav aria-label="Place in the atlas" className="mt-1">
      <ol className="flex flex-wrap items-center gap-x-0.5 gap-y-0.5 text-[11px] text-muted-foreground">
        {crumbs.map((c, i) => (
          <li key={c.id} className="flex min-w-0 items-center gap-0.5">
            {i > 0 && <ChevronRight className="size-3 shrink-0 opacity-60" aria-hidden />}
            <button
              type="button"
              onClick={() => onSelect(c.id)}
              className="max-w-[12rem] truncate rounded px-0.5 outline-none hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring"
              data-testid="atlas-crumb"
            >
              {crumbLabel(c, labelStyle)}
            </button>
          </li>
        ))}
      </ol>
    </nav>
  );
}

function crumbLabel(n: AtlasTreeNode, labelStyle: LabelStyle) {
  return n.kind === "category" && n.category ? categoryLabel(n.category, labelStyle) : n.label;
}

function PanelHeader({
  kicker,
  title,
  id,
  icon,
  colorVar,
  ids,
  index,
  nodeId,
  onSelect,
  onClose,
}: {
  kicker: string;
  title: string;
  id?: string;
  /** Replaces the plain id line (nodes that are not on the map: linked ids). */
  ids?: React.ReactNode;
  icon: React.ReactNode;
  colorVar?: string;
  index: TreeIndex;
  nodeId: string;
  onSelect: (id: string) => void;
  onClose: () => void;
}) {
  return (
    <div className="flex shrink-0 items-start gap-3 border-b px-4 py-3">
      <span
        className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border bg-background"
        style={colorVar ? { color: `var(${colorVar})` } : undefined}
      >
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[11px] font-medium text-muted-foreground">{kicker}</p>
        <h2 id="atlas-panel-title" className="text-[15px] leading-snug font-semibold text-balance break-words">
          {title}
        </h2>
        {ids ?? (id && <p className="font-mono text-[10.5px] break-all text-muted-foreground">{id}</p>)}
        <Breadcrumb index={index} nodeId={nodeId} onSelect={onSelect} />
      </div>
      <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close summary">
        <X aria-hidden />
      </Button>
    </div>
  );
}

/** Summary panel for the node selected on the Atlas: entity summary, local group panel, or an invitation. */
export function AtlasPanel({ index, nodeId, onSelect, onShowChain, onClose, onMissing, className }: AtlasPanelProps) {
  // Nothing selected: no card (the view shows the map only).
  if (!nodeId) return null;
  const node = index.nodes.get(nodeId);
  if (node && node.kind !== "entity") {
    return <GroupPanel key={nodeId} index={index} node={node} onSelect={onSelect} onClose={onClose} className={className} />;
  }
  return (
    <EntityPanel
      key={nodeId}
      index={index}
      nodeId={nodeId}
      onSelect={onSelect}
      onShowChain={onShowChain}
      onClose={onClose}
      onMissing={onMissing}
      className={className}
    />
  );
}

// ---------------------------------------------------------------------------
// Groups (local, no request)

/** What a group is grouped by, in one short line. */
function basisText(node: AtlasTreeNode): string {
  const basis = node.group_basis as GroupBasis | null;
  const ref = node.ref_id;
  switch (basis) {
    case "subcategory":
      return "Grouped by record type.";
    case "mechanism_cluster":
      return "Grouped by mechanism group (a hypothesis).";
    case "research_field":
      return "Grouped by the mechanism group most of their work is about.";
    case "focus_gene":
      return "Grouped by the gene most of their papers are about.";
    case "hpo_class":
      return `Grouped by HPO class${ref ? ` ${ref}` : ""}.`;
    case "chromosome":
      return `Genes on chromosome ${ref ?? node.label}.`;
    case "pathway_source":
      return `Grouped by source database (${node.label}).`;
    case "institution_kind":
      return "Grouped by keywords in the name, so approximate.";
    case "country":
      return "Grouped by recorded country.";
    case "year_band":
      return `Published ${node.label}.`;
    case "trial_status":
      return "Grouped by trial status.";
    case "agency":
      return "Grouped by funder.";
    case "activity_code":
      return "Grouped by grant activity code.";
    case "registry_kind":
      return "Grouped by kind of registry.";
    case "alpha_range":
      return `Alphabetical slice ${node.label}.`;
    case "not_recorded":
      return "The source does not record this.";
    case "contributed":
      return "Contributed by users, pending review.";
    default:
      return "A group in this tree.";
  }
}

function GroupPanel({
  index,
  node,
  onSelect,
  onClose,
  className,
}: {
  index: TreeIndex;
  node: AtlasTreeNode;
  onSelect: (id: string) => void;
  onClose: () => void;
  className?: string;
}) {
  const { labelStyle } = useLens();
  const children = (index.children.get(node.id) ?? []).map((id) => index.nodes.get(id)).filter((n): n is AtlasTreeNode => !!n);
  const groups = children.filter((c) => c.kind !== "entity").length;
  const isCategory = node.kind === "category" && node.category;
  const title = isCategory ? categoryLabel(node.category!, labelStyle) : node.kind === "root" ? "The whole atlas" : node.label;
  const description =
    node.kind === "root" ? "Every entry, in nine trees." : isCategory ? "One of the nine trees of the atlas." : basisText(node);

  return (
    <Shell
      className={className}
      header={
        <PanelHeader
          kicker={isCategory ? "Category" : "Group"}
          title={title}
          icon={<FolderTree className="size-4 text-muted-foreground" aria-hidden />}
          index={index}
          nodeId={node.id}
          onSelect={onSelect}
          onClose={onClose}
        />
      }
    >
      <div className="space-y-3 px-4 py-3" data-testid="atlas-group-panel">
        <div className="space-y-1">
          <p className="text-sm text-muted-foreground" data-testid="atlas-group-basis">
            {description}
          </p>
          <p className="font-mono text-xs tabular text-muted-foreground" data-testid="atlas-group-counts">
            {node.entity_count.toLocaleString("en")} entries · {node.child_count.toLocaleString("en")} {groups > 0 ? "branches" : "here"}
          </p>
        </div>
        <section aria-label={`In this ${isCategory ? "category" : "group"}`}>
          <ul className="space-y-1" data-testid="atlas-group-children">
            {children.map((c) => {
              const meta = c.entity_type ? nodeTypeMeta(c.entity_type) : null;
              const Icon = meta?.icon ?? FolderTree;
              return (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => onSelect(c.id)}
                    className="flex w-full items-center gap-2 rounded-lg border bg-background/50 px-2.5 py-1.5 text-left text-[13px] outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
                    data-testid="atlas-group-child"
                  >
                    <Icon
                      className={cn("size-3.5 shrink-0", !meta && "text-muted-foreground")}
                      style={meta ? { color: `var(${meta.colorVar})` } : undefined}
                      aria-hidden
                    />
                    <span className="min-w-0 flex-1 truncate">{c.label}</span>
                    {c.kind !== "entity" && (
                      <span className="shrink-0 font-mono text-[11px] tabular text-muted-foreground">{c.entity_count}</span>
                    )}
                    {c.contributed && (
                      <span className="shrink-0 rounded border border-dashed px-1 text-[10px] text-muted-foreground">pending</span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      </div>
    </Shell>
  );
}

// ---------------------------------------------------------------------------
// Entities (summary from the API)

type Load =
  | { kind: "loading" }
  | { kind: "ready"; data: Summary }
  | { kind: "not_found" }
  | { kind: "error" };

function EntityPanel({
  index,
  nodeId,
  onSelect,
  onShowChain,
  onClose,
  onMissing,
  className,
}: {
  index: TreeIndex;
  nodeId: string;
  onSelect: (id: string) => void;
  onShowChain: (edgeIds: string[]) => void;
  onClose: () => void;
  onMissing?: (id: string) => void;
  className?: string;
}) {
  const { labelStyle, role } = useLens();
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const treeNode = index.nodes.get(nodeId);
  /** Exists in the atlas but is not drawn on the map (no tree node). */
  const offMap = !treeNode;

  useEffect(() => {
    let alive = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- new request
    setLoad({ kind: "loading" });
    getAtlasSummary({ path: { node_id: nodeId }, query: { role }, meta: { quiet: true } })
      .then(({ data, error }) => {
        if (!alive) return;
        if (data) setLoad({ kind: "ready", data });
        else setLoad({ kind: (error as ApiError | undefined)?.code === "not_found" ? "not_found" : "error" });
      })
      .catch(() => alive && setLoad({ kind: "error" }));
    return () => {
      alive = false;
    };
  }, [nodeId, role, attempt]);

  // An id that is neither on the map nor in the atlas: the view shows its own notice instead.
  useEffect(() => {
    if (offMap && load.kind === "not_found") onMissing?.(nodeId);
  }, [offMap, load.kind, nodeId, onMissing]);

  const data = load.kind === "ready" ? load.data : null;
  const details = useOffMapDetails(offMap ? data : null);
  const sections = useMemo(() => (data ? sortByFrequency(data.sections, details) : []), [data, details]);
  const type = data?.node.type ?? treeNode?.entity_type ?? "disease";
  const meta = nodeTypeMeta(type);
  const Icon = meta.icon;
  const label = data?.node.label ?? treeNode?.label ?? nodeId;

  return (
    <Shell
      className={className}
      busy={load.kind === "loading"}
      header={
        <PanelHeader
          kicker={meta.label[labelStyle]}
          title={label}
          id={nodeId}
          ids={offMap ? <OffMapIds node={data?.node ?? { id: nodeId }} /> : undefined}
          icon={<Icon className="size-4" aria-hidden />}
          colorVar={meta.colorVar}
          index={index}
          nodeId={nodeId}
          onSelect={onSelect}
          onClose={onClose}
        />
      }
      footer={
        load.kind !== "not_found" && (
          <div className="shrink-0 border-t px-4 py-3">
            <Link href={`/node/${encodeURIComponent(nodeId)}`} className={cn(buttonVariants(), "w-full")} data-testid="atlas-open-node">
              Open full view
              <ArrowRight data-icon="inline-end" aria-hidden />
            </Link>
          </div>
        )
      }
    >
      {load.kind === "loading" && (
        <div className="space-y-4 px-4 py-3" role="status" aria-label="Loading the summary" data-testid="atlas-summary-loading">
          <div className="space-y-1.5">
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-11/12" />
            <Skeleton className="h-3 w-3/5" />
          </div>
          {[0, 1].map((i) => (
            <div key={i} className="space-y-1.5">
              <Skeleton className="h-3 w-1/3" />
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-full" />
            </div>
          ))}
        </div>
      )}

      {load.kind === "not_found" && (
        <div className="px-4 py-4 text-sm" role="alert" data-testid="atlas-summary-not-found">
          <p className="font-medium">No longer in the atlas.</p>
        </div>
      )}

      {load.kind === "error" && (
        <div className="flex items-center gap-2 px-4 py-4 text-sm" role="alert" data-testid="atlas-summary-error">
          <TriangleAlert className="size-4 shrink-0 text-status-flag" aria-hidden />
          <p className="flex-1">Couldn&apos;t load the summary.</p>
          <Button variant="outline" size="xs" onClick={() => setAttempt((a) => a + 1)}>
            <RefreshCw aria-hidden /> Retry
          </Button>
        </div>
      )}

      {data && (
        <div className="divide-y">
          <section aria-label="Overview" className="space-y-2.5 px-4 py-3">
            {data.vus_notice && <VusNotice compact />}
            {data.headline && <Headline text={data.headline} />}
            {data.coverage === "core" && <CoverageLine count={data.focus_disease_count} disease={data.node.type === "disease"} />}
            {data.node.type === "disease" && (
              <FollowButton nodeId={data.node.id} label={data.node.label} updatesAvailable={data.coverage !== "core"} />
            )}
            {PEOPLE.has(data.node.type) && (
              <p className="text-[11px] text-muted-foreground">
                Public info only ·{" "}
                <Link
                  href={`/about-data?entry=${encodeURIComponent(data.node.id)}#claim`}
                  className="font-medium text-foreground underline underline-offset-2"
                  data-testid="claim-entry-link"
                >
                  Claim or remove
                </Link>
              </p>
            )}
            <WrittenSummary
              nodeId={nodeId}
              edgeIds={data.explain_edge_ids}
              onShowChain={onShowChain}
            />
          </section>

          {sections.length === 0 && (
            <p className="px-4 py-3 text-sm text-muted-foreground">No connections yet.</p>
          )}
          {sections.map((s) => (
            <SummarySectionView
              key={s.key}
              section={s}
              index={index}
              details={details}
              onSelect={onSelect}
              onShowChain={onShowChain}
            />
          ))}
        </div>
      )}
    </Shell>
  );
}

function SummarySectionView({
  section,
  index,
  details,
  onSelect,
  onShowChain,
}: {
  section: Schemas.SummarySection;
  index: TreeIndex;
  details: Details;
  onSelect: (id: string) => void;
  onShowChain: (edgeIds: string[]) => void;
}) {
  const heading = SECTION_HEADING[section.key] ?? section.key.replace(/_/g, " ");
  const headingId = `atlas-section-${section.key}`;
  const people = PEOPLE.has(section.node_type);
  return (
    <section aria-labelledby={headingId} className="px-4 py-3" data-testid="atlas-summary-section" data-section={section.key}>
      <h3 id={headingId} className="mb-2 flex items-baseline gap-2 text-sm font-semibold">
        <span className="min-w-0 flex-1">{heading}</span>
        <span className="font-mono text-xs font-normal tabular text-muted-foreground" data-testid="atlas-summary-total">
          {section.total.toLocaleString("en")}
        </span>
      </h3>
      <ul className="space-y-1.5">
        {section.items.map((item) => (
          <SummaryItemRow
            key={item.id}
            item={item}
            // Only a chain whose links are all on the map can be drawn.
            drawable={item.via.length > 0 && item.via.every((id) => index.edges.has(id))}
            detail={item.via.length === 1 ? details.get(item.via[0])?.text : undefined}
            onSelect={onSelect}
            onShowChain={onShowChain}
          />
        ))}
      </ul>
      {(section.total > section.items.length || people) && (
        <p className="mt-1.5 text-[11px] text-muted-foreground">
          {section.total > section.items.length && <>Top {section.items.length} of {section.total.toLocaleString("en")}</>}
          {section.total > section.items.length && people && " · "}
          {people && (
            <Link href="/about-data" className="underline underline-offset-2 hover:text-foreground">
              About this data
            </Link>
          )}
        </p>
      )}
    </section>
  );
}

function SummaryItemRow({
  item,
  drawable,
  detail,
  onSelect,
  onShowChain,
}: {
  item: SummaryItem;
  /** Every link of the item's chain is on the map, so "Show the link" has something to draw. */
  drawable: boolean;
  /** One short fact about the direct link (a symptom's frequency, a gene's sources). */
  detail?: string;
  onSelect: (id: string) => void;
  onShowChain: (edgeIds: string[]) => void;
}) {
  const { labelStyle } = useLens();
  const meta = nodeTypeMeta(item.type);
  const Icon = meta.icon;
  // Cluster membership is a stored attribute, not an edge: no chain, no confidence.
  const membership = item.via.length === 0;
  const via = item.via_label ?? (membership ? "Same mechanism group" : item.hops <= 1 ? "Direct" : `${item.hops} steps`);
  return (
    <li className="rounded-lg border bg-background/50 px-2.5 py-1.5" data-testid="atlas-summary-item" data-membership={membership || undefined}>
      <div className="flex items-start gap-2">
        <button
          type="button"
          onClick={() => onSelect(item.id)}
          className="flex min-w-0 flex-1 items-start gap-1.5 rounded text-left text-[13px] font-medium outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Icon className="mt-0.5 size-3.5 shrink-0" style={{ color: `var(${meta.colorVar})` }} aria-hidden />
          <span className="line-clamp-2">{item.label}</span>
          <span className="sr-only">({meta.label[labelStyle]}). Select on the map</span>
        </button>
        {!membership && drawable && (
          <button
            type="button"
            onClick={() => onShowChain(item.via)}
            title="Show the link on the map"
            className="inline-flex size-6 shrink-0 items-center justify-center rounded text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
            data-testid="atlas-summary-chain"
          >
            <Route className="size-3.5" aria-hidden />
            <span className="sr-only">Show the link to {item.label} on the map</span>
          </button>
        )}
      </div>
      <div className="mt-0.5 flex flex-wrap items-center gap-1.5 pl-5">
        <span className="text-xs text-muted-foreground" data-testid="atlas-summary-via">
          {via}
        </span>
        {detail && (
          <span className="text-xs font-medium text-foreground/80" data-testid="atlas-summary-detail">
            {detail}
          </span>
        )}
        {!membership && <ConfidenceBadge confidence={item.best_confidence} showScore={labelStyle === "technical"} />}
        <OriginBadge origin={item.inferred ? "inferred" : "observed"} />
        {item.under_review && <StatusFlag status="under_review" />}
      </div>
      {item.inferred && item.explanation && (
        <p className="mt-1 pl-5 text-xs" data-testid="atlas-summary-explanation">
          {item.explanation} <span className="text-muted-foreground">A hypothesis, not an established fact.</span>
        </p>
      )}
    </li>
  );
}

// ---------------------------------------------------------------------------
// Nodes that are not on the map

/** The node's standard ids, each linked to its public page by id (no names in URLs). */
function OffMapIds({ node }: { node: { id: string; attrs?: Record<string, unknown> | null } }) {
  const links = idLinks(node);
  return (
    <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1" data-testid="atlas-panel-ids">
      <OffMapMark />
      {links.length === 0 && <span className="font-mono text-[10.5px] break-all text-muted-foreground">{node.id}</span>}
      {links.map((l) => (
        <a
          key={l.id}
          href={l.href}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-0.5 font-mono text-[10.5px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          data-testid="atlas-panel-id-link"
        >
          {l.id}
          <ExternalLink className="size-2.5" aria-hidden />
          <span className="sr-only">(opens in a new tab)</span>
        </a>
      ))}
    </div>
  );
}

/** Why a core node's panel has no literature, trials or people: one fixed line. */
function CoverageLine({ count, disease }: { count: number; disease: boolean }) {
  return (
    <p className="flex gap-1.5 text-xs text-muted-foreground" data-testid="atlas-coverage">
      <Info className="mt-px size-3.5 shrink-0" aria-hidden />
      <span>
        Literature, trials, researchers and patient groups are collected for {count.toLocaleString("en")} focus diseases;{" "}
        {disease ? "this one isn't one of them yet." : "this one isn't linked to them yet."}
      </span>
    </p>
  );
}

/** Per direct edge id: a short fact to show (frequency label, gene sources) and a frequency to sort by. */
type Details = ReadonlyMap<string, { text?: string; frequency?: number | null }>;
const NO_DETAILS: Details = new Map();

const SOURCE_NAMES: Record<string, string> = {
  orphanet: "Orphanet",
  hpo: "HPO",
  clinvar: "ClinVar",
  mondo: "MONDO",
  clingen: "ClinGen",
  omim: "OMIM",
  pubmed: "PubMed",
  gene2phenotype: "G2P",
};

/**
 * The summary items carry no frequency or source, so for a node that is not
 * on the map they come from the direct edges: symptom frequencies from its
 * neighbourhood (one request), a gene's sources from that link's evidence
 * (at most a few requests, cached). Public graph ids only.
 */
function useOffMapDetails(data: Summary | null): Details {
  const [state, setState] = useState<{ key: string; details: Details }>({ key: "", details: NO_DETAILS });
  const symptomEdges = useMemo(
    () => data?.sections.find((s) => s.key === "symptoms")?.items.filter((i) => i.via.length === 1).map((i) => i.via[0]) ?? [],
    [data],
  );
  const geneEdges = useMemo(
    () => data?.sections.find((s) => s.key === "genes")?.items.filter((i) => i.via.length === 1).slice(0, 5).map((i) => i.via[0]) ?? [],
    [data],
  );
  const nodeId = data?.node.id ?? "";
  const key = `${nodeId}|${symptomEdges.join(",")}|${geneEdges.join(",")}`;

  useEffect(() => {
    if (!nodeId || (symptomEdges.length === 0 && geneEdges.length === 0)) return;
    let alive = true;
    const out = new Map<string, { text?: string; frequency?: number | null }>();
    const wanted = new Set(symptomEdges);
    const hood =
      symptomEdges.length === 0
        ? Promise.resolve()
        : getNeighborhood({ path: { node_id: nodeId }, meta: { quiet: true } })
            .then(({ data: hoodData }) => {
              for (const e of hoodData?.edges ?? []) {
                if (!wanted.has(e.id)) continue;
                const f = e.features as { frequency?: unknown; frequency_label?: unknown } | null;
                const label = typeof f?.frequency_label === "string" ? f.frequency_label : undefined;
                const frequency = typeof f?.frequency === "number" ? f.frequency : null;
                out.set(e.id, { text: label, frequency });
              }
            })
            .catch(() => undefined);
    const genes = Promise.all(
      geneEdges.map(async (id) => {
        const ev = await loadEdge(id);
        const names = [...new Set((ev?.supporting ?? []).map((x) => SOURCE_NAMES[x.source_type] ?? x.source_type))];
        if (names.length > 0) out.set(id, { text: names.join(" · ") });
      }),
    );
    void Promise.all([hood, genes]).then(() => {
      if (alive) setState({ key, details: out });
    });
    return () => {
      alive = false;
    };
  }, [key, nodeId, symptomEdges, geneEdges]);

  return state.key === key ? state.details : NO_DETAILS;
}

/** Symptoms with a known frequency first, most frequent first; the rest keep the summary's order. */
function sortByFrequency(sections: Schemas.SummarySection[], details: Details): Schemas.SummarySection[] {
  if (details.size === 0) return sections;
  return sections.map((s) => {
    if (s.key !== "symptoms") return s;
    const freq = (i: SummaryItem) => (i.via.length === 1 ? (details.get(i.via[0])?.frequency ?? -1) : -1);
    return { ...s, items: s.items.map((item, i) => ({ item, i })).sort((a, b) => freq(b.item) - freq(a.item) || a.i - b.i).map((x) => x.item) };
  });
}

/** The headline, clamped to three lines with a toggle for the rest. */
function Headline({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > 160;
  return (
    <div>
      <p className={cn("text-sm leading-snug text-pretty text-muted-foreground", !open && long && "line-clamp-3")} data-testid="atlas-summary-headline">
        {text}
      </p>
      {long && (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="mt-0.5 rounded text-xs font-medium text-foreground underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
          data-testid="atlas-summary-more"
        >
          {open ? "Less" : "More"}
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// "Write a summary" (POST /explain with subject_node_id)

type WriteState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "streaming"; text: string }
  | { kind: "done"; final: ExplainFinal }
  | { kind: "sign_in" }
  | { kind: "unavailable" }
  | { kind: "error"; message: string };

function writeError(code: string) {
  switch (code) {
    case "network_error":
      return "Server unreachable.";
    case "rate_limited":
      return "Usage limit reached.";
    case "upstream_error":
      return "The AI service did not respond.";
    case "not_found":
      return "No longer in the atlas.";
    default:
      return "Couldn't write the summary.";
  }
}

const CITATION = /\[(e_[0-9a-zA-Z]+(?:\s*[,;]\s*e_[0-9a-zA-Z]+)*)\]/g;

/** Model text with `[e_…]` citations as numbered buttons that show that link on the map. */
function CitedSummary({
  text,
  edgeIds,
  streaming,
  onShowChain,
}: {
  text: string;
  edgeIds: string[];
  streaming: boolean;
  onShowChain: (edgeIds: string[]) => void;
}) {
  const shown = streaming ? text.replace(/\[[^\]]{0,40}$/, "") : text;
  const order = new Map(edgeIds.map((id, i) => [id, i]));
  const parts: React.ReactNode[] = [];
  let last = 0;
  for (const m of shown.matchAll(CITATION)) {
    parts.push(shown.slice(last, m.index));
    const ids = m[1].split(/\s*[,;]\s*/).filter((id) => order.has(id));
    parts.push(
      <Fragment key={m.index}>
        {ids.map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => onShowChain([id])}
            data-testid="citation"
            data-edge-id={id}
            className="mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-px items-center justify-center rounded-full border border-primary/60 bg-primary/15 px-1 align-middle font-mono text-[10px] font-semibold text-foreground outline-none transition hover:bg-primary hover:text-primary-foreground focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={`Source ${order.get(id)! + 1}: show this link on the map`}
          >
            {order.get(id)! + 1}
          </button>
        ))}
      </Fragment>,
    );
    last = (m.index ?? 0) + m[0].length;
  }
  parts.push(shown.slice(last));
  return <>{parts}</>;
}

function WrittenSummary({
  nodeId,
  edgeIds,
  onShowChain,
}: {
  nodeId: string;
  edgeIds: string[];
  onShowChain: (edgeIds: string[]) => void;
}) {
  const { role } = useLens();
  const { user } = useSession();
  const { requireSignIn } = useGate();
  const [state, setState] = useState<WriteState>({ kind: "idle" });
  const [attempt, setAttempt] = useState(0);
  const language = user?.language || "en";
  const edgeKey = edgeIds.join(",");

  useEffect(() => {
    if (attempt === 0) return;
    const ctrl = new AbortController();
    let text = "";
    // eslint-disable-next-line react-hooks/set-state-in-effect -- new request
    setState({ kind: "loading" });
    const fail = (code: string) => {
      if (code === "sign_in_required" || code === "reauth_required") setState({ kind: "sign_in" });
      else if (code === "not_implemented") setState({ kind: "unavailable" });
      else setState({ kind: "error", message: writeError(code) });
    };
    // Graph ids only: no user content reaches this request.
    streamSSE<ExplainEvent>("/explain", {
      json: { edge_ids: edgeKey.split(","), subject_node_id: nodeId, role, language },
      signal: ctrl.signal,
      quiet: true,
      onEvent: (e) => {
        if (e.type === "delta") {
          text += e.text;
          setState({ kind: "streaming", text });
        } else if (e.type === "final") {
          setState({ kind: "done", final: e });
          announce(e.cached ? "Summary loaded." : "Summary finished.");
        } else if (e.type === "error") {
          fail(e.code);
        }
      },
    }).catch((err: ApiError) => {
      if (ctrl.signal.aborted || err.code === "aborted") return;
      fail(err.code);
    });
    return () => ctrl.abort();
  }, [attempt, edgeKey, nodeId, role, language, user?.id]);

  if (edgeIds.length === 0) return null;

  const write = () => setAttempt((a) => a + 1);
  const signIn = () => {
    const here = typeof window !== "undefined" ? `${window.location.pathname}${window.location.search}` : "/atlas";
    void requireSignIn("Writing a new summary uses Dr. Wu.", here);
  };

  if (state.kind === "idle") {
    return (
      <Button variant="outline" size="sm" className="w-full" onClick={write} data-testid="atlas-summary-write">
        <Sparkles className="text-primary" aria-hidden />
        Write a summary
      </Button>
    );
  }

  return (
    <div className="rounded-lg border bg-background/60 p-2.5" data-testid="atlas-summary-written" aria-live="off">
      <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-1.5 text-xs font-semibold">
          <Bot className="size-3.5 text-primary" aria-hidden />
          Summary
        </h3>
        {(state.kind === "streaming" || state.kind === "done") && <AiDisclosure variant="inline" />}
      </div>

      {state.kind === "loading" && (
        <div className="space-y-1.5" role="status" aria-label="Writing the summary">
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-11/12" />
          <Skeleton className="h-3 w-3/5" />
        </div>
      )}

      {(state.kind === "streaming" || state.kind === "done") && (
        <>
          <p className="text-sm leading-relaxed text-pretty" lang={language} data-testid="atlas-summary-text">
            <CitedSummary
              text={state.kind === "done" ? state.final.text : state.text}
              edgeIds={edgeIds}
              streaming={state.kind === "streaming"}
              onShowChain={onShowChain}
            />
            {state.kind === "streaming" && (
              <span aria-hidden className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse rounded-sm bg-primary align-middle motion-reduce:animate-none" />
            )}
          </p>
          {state.kind === "done" && (
            <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
              {state.final.cached ? (
                <span className="inline-flex items-center gap-1" data-testid="atlas-summary-cached">
                  <Archive className="size-3" aria-hidden /> Cached
                </span>
              ) : (
                <span className="inline-flex items-center gap-1" data-testid="atlas-summary-fresh">
                  <Sparkles className="size-3" aria-hidden /> New
                </span>
              )}
              <span>Not medical advice.</span>
            </p>
          )}
        </>
      )}

      {state.kind === "sign_in" && (
        <div className="flex flex-wrap items-center justify-between gap-2" data-testid="atlas-summary-sign-in">
          <p className="text-sm text-muted-foreground">Not prepared yet.</p>
          <Button variant="outline" size="xs" onClick={signIn}>
            <Bot className="text-primary" aria-hidden />
            Sign in to write it
          </Button>
        </div>
      )}

      {state.kind === "unavailable" && (
        <p className="text-sm text-muted-foreground" data-testid="atlas-summary-unavailable">
          Not available on this server.
        </p>
      )}

      {state.kind === "error" && (
        <div className="flex items-center gap-2 text-sm" role="alert" data-testid="atlas-summary-write-error">
          <TriangleAlert className="size-4 shrink-0 text-status-flag" aria-hidden />
          <p className="flex-1">{state.message}</p>
          <Button variant="ghost" size="xs" onClick={write}>
            <RefreshCw aria-hidden /> Retry
          </Button>
        </div>
      )}
    </div>
  );
}
