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
import { Fragment, useEffect, useState } from "react";

import { FollowButton } from "@/components/follows/follow-button";
import { ConfidenceBadge, OriginBadge, StatusFlag, VusNotice } from "@/components/graph-ui";
import { InAmberChip } from "@/components/people/in-amber-chip";
import { useGate } from "@/components/providers/gate-provider";
import { useLens } from "@/components/providers/lens-provider";
import { useSession } from "@/components/providers/session-provider";
import { AiDisclosure } from "@/components/shell/ai-disclosure";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { fadeWords, useSmoothReveal } from "@/components/ui/smooth-reveal";
import { announce } from "@/lib/a11y";
import { getAtlasSummary, streamSSE, type Schemas } from "@/lib/api";
import type { ApiError } from "@/lib/api/errors";
import { nodeTypeMeta, type LabelStyle } from "@/lib/graph/meta";
import { cn } from "@/lib/utils";

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
  shared_gene_diseases: "Same gene",
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
  const sections = data?.sections ?? [];
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
          ids={
            offMap || type === "disease" ? <NodeIds node={data?.node ?? { id: nodeId }} offMap={offMap} /> : undefined
          }
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
  onSelect,
  onShowChain,
}: {
  section: Schemas.SummarySection;
  index: TreeIndex;
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
            detail={itemDetail(item)}
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
  // A computed link (inferred, one step) is never worded as a fact and is drawn dashed.
  const computed = !membership && item.inferred && item.hops <= 1;
  const via =
    item.via_label ??
    (membership ? "Same mechanism group" : computed ? "Computed link" : item.hops <= 1 ? "Direct" : `${item.hops} steps`);
  return (
    <li
      className={cn("rounded-lg border bg-background/50 px-2.5 py-1.5", computed && "border-dashed border-foreground/30")}
      data-testid="atlas-summary-item"
      data-membership={membership || undefined}
      data-computed={computed || undefined}
    >
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
        {/* A plain "Direct" adds nothing next to a detail (frequency, sources). */}
        {!(detail && via === "Direct") && (
          <span className="text-xs text-muted-foreground" data-testid="atlas-summary-via">
            {via}
          </span>
        )}
        {detail && (
          <span className="text-xs font-medium text-foreground/80" data-testid="atlas-summary-detail">
            {detail}
          </span>
        )}
        {!membership && <ConfidenceBadge confidence={item.best_confidence} showScore={labelStyle === "technical"} />}
        <OriginBadge origin={item.inferred ? "inferred" : "observed"} />
        {item.under_review && <StatusFlag status="under_review" />}
        {item.card_id && (item.type === "researcher" || item.type === "doctor") && <InAmberChip cardId={item.card_id} name={item.label} />}
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
function NodeIds({ node, offMap }: { node: { id: string; attrs?: Record<string, unknown> | null }; offMap: boolean }) {
  const links = idLinks(node);
  return (
    <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1" data-testid="atlas-panel-ids">
      {offMap && <OffMapMark />}
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
 * One short fact about an item's direct link, as the summary gives it: a
 * symptom's frequency label (the source's wording, no invented percentage)
 * or where a gene link comes from. The summary already sorts symptoms by
 * frequency.
 */
function itemDetail(item: SummaryItem): string | undefined {
  if (item.frequency_label) return item.frequency_label;
  const sources = item.sources ?? [];
  if (sources.length > 0) return [...new Set(sources.map((s) => SOURCE_NAMES[s] ?? s))].join(" · ");
  return undefined;
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

/**
 * `working` holds the server's step lines, the checked text received so far
 * (the API sends text only after the citation check passed) and the final
 * event once it arrived; the text is then revealed smoothly, word by word (the shared reveal).
 */
type WriteState =
  | { kind: "idle" }
  | { kind: "working"; steps: string[]; text: string; final: ExplainFinal | null }
  | { kind: "sign_in" }
  | { kind: "unavailable" }
  | { kind: "error"; message: string };

const WORKING: WriteState = { kind: "working", steps: [], text: "", final: null };

/** No event for this long: the request is given up as timed out. */
const WRITE_IDLE_TIMEOUT_MS = 100_000;

function writeError(code: string) {
  switch (code) {
    case "network_error":
      return "Server unreachable.";
    case "rate_limited":
      return "Usage limit reached.";
    case "upstream_error":
      return "The AI service did not respond.";
    case "timeout":
      return "Dr. Wu took too long.";
    case "age_confirmation_required":
      return "Confirm your age first.";
    case "consent_required":
      return "Consent needed first.";
    case "not_found":
      return "No longer in the atlas.";
    default:
      return "Couldn't write the summary.";
  }
}

/** Three calm dots while Dr. Wu works; still with reduced motion. */
function WritingDots() {
  return (
    <span aria-hidden className="inline-flex items-center gap-0.5">
      {[0, 150, 300].map((delay) => (
        <span
          key={delay}
          className="size-1 animate-pulse rounded-full bg-primary motion-reduce:animate-none"
          style={{ animationDelay: `${delay}ms` }}
        />
      ))}
    </span>
  );
}

const CITATION = /\[(e_[0-9a-zA-Z]+(?:\s*[,;]\s*e_[0-9a-zA-Z]+)*)\]/g;

/** Model text with `[e_…]` citations as numbered buttons that show that link on the map. */
function CitedSummary({
  text,
  edgeIds,
  streaming,
  animate = false,
  onShowChain,
}: {
  text: string;
  edgeIds: string[];
  streaming: boolean;
  /** Being revealed: words fade in, and the buttons wait out of the tab order until it ends. */
  animate?: boolean;
  onShowChain: (edgeIds: string[]) => void;
}) {
  const shown = streaming ? text.replace(/\[[^\]]{0,40}$/, "") : text;
  const order = new Map(edgeIds.map((id, i) => [id, i]));
  const parts: React.ReactNode[] = [];
  const plain = (from: number, to: number) => (animate ? fadeWords(shown.slice(from, to), from) : shown.slice(from, to));
  let last = 0;
  for (const m of shown.matchAll(CITATION)) {
    parts.push(<Fragment key={`t${last}`}>{plain(last, m.index)}</Fragment>);
    const ids = m[1].split(/\s*[,;]\s*/).filter((id) => order.has(id));
    parts.push(
      <Fragment key={m.index}>
        {ids.map((id) => (
          <button
            key={id}
            type="button"
            tabIndex={animate ? -1 : undefined}
            onClick={() => onShowChain([id])}
            data-testid="citation"
            data-edge-id={id}
            className={cn(animate && "smooth-word", "mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-px items-center justify-center rounded-full border border-primary/60 bg-primary/15 px-1 align-middle font-mono text-[10px] font-semibold text-foreground outline-none transition hover:bg-primary hover:text-primary-foreground focus-visible:ring-2 focus-visible:ring-ring")}
            aria-label={`Source ${order.get(id)! + 1}: show this link on the map`}
          >
            {order.get(id)! + 1}
          </button>
        ))}
      </Fragment>,
    );
    last = (m.index ?? 0) + m[0].length;
  }
  parts.push(<Fragment key={`t${last}`}>{plain(last, shown.length)}</Fragment>);
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
    let watchdog: ReturnType<typeof setTimeout> | undefined;
    const fail = (code: string, message?: string) => {
      clearTimeout(watchdog);
      if (code === "sign_in_required" || code === "reauth_required") setState({ kind: "sign_in" });
      else if (code === "not_implemented") setState({ kind: "unavailable" });
      else setState({ kind: "error", message: message || writeError(code) });
    };
    const arm = () => {
      clearTimeout(watchdog);
      watchdog = setTimeout(() => {
        fail("timeout");
        ctrl.abort("timeout");
      }, WRITE_IDLE_TIMEOUT_MS);
    };
    const working = (update: (s: Extract<WriteState, { kind: "working" }>) => WriteState) =>
      setState((s) => (s.kind === "working" ? update(s) : s));
    // eslint-disable-next-line react-hooks/set-state-in-effect -- new request
    setState(WORKING);
    arm();
    // Graph ids only: no user content reaches this request. `steps` adds the server's
    // progress lines; the text itself arrives only after it passed the citation check.
    streamSSE<ExplainEvent>("/explain", {
      json: { edge_ids: edgeKey.split(","), subject_node_id: nodeId, role, language, steps: true },
      signal: ctrl.signal,
      quiet: true,
      onEvent: (e) => {
        arm();
        if (e.type === "status") {
          working((s) => ({ ...s, steps: [...s.steps, e.message] }));
        } else if (e.type === "delta") {
          working((s) => ({ ...s, text: s.text + e.text }));
        } else if (e.type === "final") {
          clearTimeout(watchdog);
          working((s) => ({ ...s, text: e.text, final: e }));
          announce(e.cached ? "Summary loaded." : "Summary finished.");
        } else if (e.type === "error") {
          // The server's own short line tells a time-out from an unavailable model.
          fail(e.code, e.code === "upstream_error" ? e.message : undefined);
        }
      },
    }).catch((err: ApiError) => {
      if (ctrl.signal.aborted || err.code === "aborted") return;
      fail(err.code);
    });
    return () => {
      clearTimeout(watchdog);
      ctrl.abort();
    };
  }, [attempt, edgeKey, nodeId, role, language, user?.id]);

  const text = state.kind === "working" ? state.text : "";
  // Fresh and cached summaries alike: the shared smooth reveal, at the same pace as Dr. Wu's answers.
  const reveal = useSmoothReveal(text);

  if (edgeIds.length === 0) return null;

  // The block replaces the button in the same render, so a second click has nothing to hit.
  const write = () => {
    setState(WORKING);
    setAttempt((a) => a + 1);
  };
  // Closing the stream stops the model call on the server.
  const cancel = () => {
    setAttempt(0);
    setState({ kind: "idle" });
    announce("Summary cancelled.");
  };
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

  const working = state.kind === "working";
  const done = working && state.final !== null && reveal.done;
  const busy = working && !done;
  let progress = "Starting";
  if (working && state.steps.length > 0) progress = text ? "Sources checked" : state.steps[state.steps.length - 1];
  else if (working && text) progress = "Prepared summary";

  return (
    <div
      className="rounded-lg border bg-background/60 p-2.5"
      data-testid="atlas-summary-written"
      data-state={busy ? "writing" : state.kind === "working" ? "done" : state.kind}
      aria-busy={busy}
    >
      <div className="mb-1.5 flex min-h-6 flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-1.5 text-xs font-semibold">
          <Bot className={cn("size-3.5 text-primary", busy && "animate-pulse motion-reduce:animate-none")} aria-hidden />
          Summary
        </h3>
        {working && <AiDisclosure variant="inline" />}
      </div>

      {working && (
        <>
          {/* One line that changes in place: the steps while writing, then the result's facts. */}
          <div className="mb-1.5 flex h-6 items-center justify-between gap-2">
            <p className="flex min-w-0 items-center gap-1.5 truncate text-[11px] text-muted-foreground" role="status" data-testid="atlas-summary-status">
              {busy ? (
                <>
                  <WritingDots />
                  <span>Dr. Wu is writing</span>
                  <span aria-hidden>·</span>
                  <span className="truncate" data-testid="atlas-summary-step">{progress}</span>
                </>
              ) : state.final!.cached ? (
                <>
                  <span className="inline-flex items-center gap-1" data-testid="atlas-summary-cached">
                    <Archive className="size-3" aria-hidden /> Cached
                  </span>
                  <span>· Not medical advice.</span>
                </>
              ) : (
                <>
                  <span className="inline-flex items-center gap-1" data-testid="atlas-summary-fresh">
                    <Sparkles className="size-3" aria-hidden /> New
                  </span>
                  <span>· Not medical advice.</span>
                </>
              )}
            </p>
            {busy && (
              <Button variant="ghost" size="xs" className="shrink-0" onClick={cancel} data-testid="atlas-summary-cancel">
                <X aria-hidden /> Cancel
              </Button>
            )}
          </div>
          {/* Space for about four lines is kept from the click, so the text never makes the panel jump. */}
          <div className="min-h-[5.75rem]">
            {text ? (
              <p className="text-sm leading-relaxed text-pretty" lang={language} aria-live="off" data-testid="atlas-summary-text">
                {/* While words fade in, screen readers get the whole text once; the fading words are hidden from them. */}
                {reveal.active && <span className="sr-only">{text.replace(CITATION, "")}</span>}
                <span aria-hidden={reveal.active || undefined} data-smooth-visible={reveal.active ? "" : undefined}>
                  <CitedSummary text={text.slice(0, reveal.shown)} edgeIds={edgeIds} streaming={busy} animate={reveal.active} onShowChain={onShowChain} />
                </span>
              </p>
            ) : (
              <div className="space-y-2 pt-1" aria-hidden data-testid="atlas-summary-placeholder">
                <Skeleton className="h-3 w-full bg-foreground/10 motion-reduce:animate-none" />
                <Skeleton className="h-3 w-11/12 bg-foreground/10 motion-reduce:animate-none" />
                <Skeleton className="h-3 w-4/5 bg-foreground/10 motion-reduce:animate-none" />
                <Skeleton className="h-3 w-3/5 bg-foreground/10 motion-reduce:animate-none" />
              </div>
            )}
          </div>
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
