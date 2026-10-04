"use client";

import {
  Archive,
  ArrowRight,
  Bot,
  ChevronRight,
  FolderTree,
  MousePointerClick,
  RefreshCw,
  Route,
  Search,
  Sparkles,
  TriangleAlert,
  X,
} from "lucide-react";
import Link from "next/link";
import { Fragment, useEffect, useState } from "react";

import { ConfidenceBadge, OriginBadge, StatusFlag, VusNotice } from "@/components/graph-ui";
import { useGate } from "@/components/providers/gate-provider";
import { useLens } from "@/components/providers/lens-provider";
import { useSession } from "@/components/providers/session-provider";
import { AiDisclosure } from "@/components/shell/ai-disclosure";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { announce } from "@/lib/a11y";
import { getAtlasSummary, streamSSE, type Schemas } from "@/lib/api";
import type { ApiError } from "@/lib/api/errors";
import { nodeTypeMeta, type LabelStyle } from "@/lib/graph/meta";
import { cn } from "@/lib/utils";

import { categoryLabel } from "./atlas-categories";
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
  index,
  nodeId,
  onSelect,
  onClose,
}: {
  kicker: string;
  title: string;
  id?: string;
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
        {id && <p className="font-mono text-[10.5px] break-all text-muted-foreground">{id}</p>}
        <Breadcrumb index={index} nodeId={nodeId} onSelect={onSelect} />
      </div>
      <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close summary">
        <X aria-hidden />
      </Button>
    </div>
  );
}

/** Summary panel for the node selected on the Atlas: entity summary, local group panel, or an invitation. */
export function AtlasPanel({ index, nodeId, onSelect, onShowChain, onClose, className }: AtlasPanelProps) {
  if (!nodeId) {
    return (
      <Shell className={className}>
        <div className="flex h-full flex-col items-center justify-center gap-3 px-6 py-10 text-center" data-testid="atlas-panel-empty">
          <span className="flex size-10 items-center justify-center rounded-full bg-primary/15 text-primary">
            <MousePointerClick className="size-5" aria-hidden />
          </span>
          <p className="text-[15px] font-semibold">Search or click a dot</p>
          <p className="max-w-[18rem] text-sm text-pretty text-muted-foreground">
            Pick a condition, gene, person or group to see who and what it is connected to, and have a summary
            written.
          </p>
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Search className="size-3.5" aria-hidden /> Press <kbd className="rounded border bg-muted px-1 font-mono text-[10px]">/</kbd> to search
          </p>
        </div>
      </Shell>
    );
  }
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
      className={className}
    />
  );
}

// ---------------------------------------------------------------------------
// Groups (local, no request)

/** What a group is grouped by, in plain words. */
function basisText(node: AtlasTreeNode, parent: AtlasTreeNode | undefined, labelStyle: LabelStyle): string {
  const basis = node.group_basis as GroupBasis | null;
  const ref = node.ref_id;
  const under = parent ? (parent.kind === "category" && parent.category ? categoryLabel(parent.category, labelStyle) : parent.label) : "this tree";
  switch (basis) {
    case "subcategory":
      return `A part of ${under}, sorted by what kind of record each entry is.`;
    case "mechanism_cluster":
      return `Entries linked to one mechanism group${ref ? ` (${ref})` : ""}. Mechanism groups come from an analysis of shared genes, pathways and symptoms, so the grouping is a hypothesis.`;
    case "research_field":
      return `People grouped by the mechanism group that most of their work is about${ref ? ` (${ref})` : ""}, counted from the papers or trials linked to them in the atlas.`;
    case "focus_gene":
      return `Researchers in this field grouped by the gene that most of their papers are about${ref ? ` (${ref})` : ""}.`;
    case "hpo_class":
      return `Symptoms filed under this class of the Human Phenotype Ontology${ref ? ` (${ref})` : ""}. Each symptom sits under one parent class only.`;
    case "chromosome":
      return `Genes on chromosome ${ref ?? node.label}, read from the location recorded for each gene.`;
    case "pathway_source":
      return `Body processes from one source database (${node.label}).`;
    case "institution_kind":
      return `Hospitals, universities and other institutions, split by keywords in their stored name (for example "hospital" or "clinic", "university" or "institute"). The records do not say what kind of place each one is, so this split is approximate.`;
    case "country":
      return `Entries in ${ref ?? node.label}, as recorded on each entry. Different spellings of the same country are merged.`;
    case "year_band":
      return `Papers published in ${node.label}.`;
    case "trial_status":
      return `Trials whose registry status is "${node.label}".`;
    case "agency":
      return `Research funding from ${ref ?? node.label}.`;
    case "activity_code":
      return `Grants with the funding activity code ${ref ?? node.label}.`;
    case "registry_kind":
      return `Registries and studies of the kind "${node.label}".`;
    case "alpha_range":
      return `An alphabetical slice (${node.label}) of ${under}. Large groups are split into slices of at most 30 entries.`;
    case "not_recorded":
      return `Entries where the source does not record what this level sorts by. Nothing is left out of the atlas because of it.`;
    case "contributed":
      return `Records contributed by users that are pending review. No person has checked them yet.`;
    default:
      return `A group in ${under}.`;
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
  const parent = node.parent_id ? index.nodes.get(node.parent_id) : undefined;
  const children = (index.children.get(node.id) ?? []).map((id) => index.nodes.get(id)).filter((n): n is AtlasTreeNode => !!n);
  const groups = children.filter((c) => c.kind !== "entity").length;
  const isCategory = node.kind === "category" && node.category;
  const title = isCategory ? categoryLabel(node.category!, labelStyle) : node.kind === "root" ? "The whole atlas" : node.label;
  const description =
    node.kind === "root"
      ? "Every entry of the atlas, in nine trees by category."
      : isCategory
        ? `One of the nine trees of the atlas: every entry of this category has exactly one place in it. The branches sort entries by stored data only.`
        : basisText(node, parent, labelStyle);

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
      <div className="space-y-4 px-4 py-3" data-testid="atlas-group-panel">
        <p className="text-sm leading-relaxed text-pretty text-muted-foreground" data-testid="atlas-group-basis">
          {description}
        </p>
        <dl className="grid grid-cols-2 gap-2 text-xs" data-testid="atlas-group-counts">
          <div className="rounded-lg border bg-background/60 px-2.5 py-2">
            <dt className="text-muted-foreground">Entries</dt>
            <dd className="font-mono text-sm font-semibold tabular">{node.entity_count.toLocaleString("en")}</dd>
          </div>
          <div className="rounded-lg border bg-background/60 px-2.5 py-2">
            <dt className="text-muted-foreground">{groups > 0 ? "Branches" : "Directly here"}</dt>
            <dd className="font-mono text-sm font-semibold tabular">{node.child_count.toLocaleString("en")}</dd>
          </div>
        </dl>
        <section aria-labelledby="atlas-group-children">
          <h3 id="atlas-group-children" className="mb-2 text-xs font-medium text-muted-foreground">
            In this {isCategory ? "category" : "group"}
          </h3>
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
  className,
}: {
  index: TreeIndex;
  nodeId: string;
  onSelect: (id: string) => void;
  onShowChain: (edgeIds: string[]) => void;
  onClose: () => void;
  className?: string;
}) {
  const { labelStyle, role } = useLens();
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const treeNode = index.nodes.get(nodeId);

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

  const data = load.kind === "ready" ? load.data : null;
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
          {[0, 1, 2].map((i) => (
            <div key={i} className="space-y-1.5">
              <Skeleton className="h-3 w-1/3" />
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-full" />
            </div>
          ))}
        </div>
      )}

      {load.kind === "not_found" && (
        <div className="space-y-2 px-4 py-6 text-sm" role="alert" data-testid="atlas-summary-not-found">
          <p className="font-medium">This entry is no longer in the atlas.</p>
          <p className="text-muted-foreground">It may have been removed or renamed in the latest data update.</p>
        </div>
      )}

      {load.kind === "error" && (
        <div className="flex items-start gap-3 px-4 py-6 text-sm" role="alert" data-testid="atlas-summary-error">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-status-flag" aria-hidden />
          <div className="space-y-2">
            <p>The summary could not be loaded. Amber&apos;s server may be unreachable.</p>
            <Button variant="outline" size="sm" onClick={() => setAttempt((a) => a + 1)}>
              <RefreshCw aria-hidden /> Try again
            </Button>
          </div>
        </div>
      )}

      {data && (
        <div className="divide-y">
          <section aria-label="Overview" className="space-y-3 px-4 py-3">
            {data.vus_notice && <VusNotice compact />}
            {data.headline && <p className="text-sm leading-relaxed text-pretty text-muted-foreground" data-testid="atlas-summary-headline">{data.headline}</p>}
            {PEOPLE.has(data.node.type) && (
              <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
                <span>Public professional information only.</span>
                <Link
                  href={`/about-data?entry=${encodeURIComponent(data.node.id)}#claim`}
                  className="font-medium text-foreground underline underline-offset-2"
                  data-testid="claim-entry-link"
                >
                  Claim or remove this entry
                </Link>
              </p>
            )}
            <WrittenSummary
              nodeId={nodeId}
              edgeIds={data.explain_edge_ids}
              label={label}
              onShowChain={onShowChain}
            />
          </section>

          {data.sections.length === 0 && (
            <p className="px-4 py-4 text-sm text-muted-foreground">No connections recorded for this entry yet.</p>
          )}
          {data.sections.map((s) => (
            <SummarySectionView key={s.key} section={s} onSelect={onSelect} onShowChain={onShowChain} />
          ))}
        </div>
      )}
    </Shell>
  );
}

function SummarySectionView({
  section,
  onSelect,
  onShowChain,
}: {
  section: Schemas.SummarySection;
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
          <SummaryItemRow key={item.id} item={item} onSelect={onSelect} onShowChain={onShowChain} />
        ))}
      </ul>
      {(section.total > section.items.length || people) && (
        <p className="mt-2 text-[11px] text-muted-foreground">
          {section.total > section.items.length && <>Showing the {section.items.length} strongest of {section.total.toLocaleString("en")}. </>}
          {people && (
            <>
              Public professional information only.{" "}
              <Link href="/about-data" className="underline underline-offset-2 hover:text-foreground">
                About this data
              </Link>
            </>
          )}
        </p>
      )}
    </section>
  );
}

function SummaryItemRow({
  item,
  onSelect,
  onShowChain,
}: {
  item: SummaryItem;
  onSelect: (id: string) => void;
  onShowChain: (edgeIds: string[]) => void;
}) {
  const { labelStyle } = useLens();
  const meta = nodeTypeMeta(item.type);
  const Icon = meta.icon;
  // Cluster membership is a stored attribute, not an edge: no chain, no confidence.
  const membership = item.via.length === 0;
  const via = item.via_label ?? (membership ? "Member of the same mechanism group" : item.hops <= 1 ? "Direct link" : `${item.hops} steps away`);
  return (
    <li className="rounded-lg border bg-background/50 px-2.5 py-2" data-testid="atlas-summary-item" data-membership={membership || undefined}>
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
        {!membership && (
          <button
            type="button"
            onClick={() => onShowChain(item.via)}
            className="inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
            data-testid="atlas-summary-chain"
          >
            <Route className="size-3" aria-hidden />
            Show link
            <span className="sr-only"> to {item.label} on the map</span>
          </button>
        )}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-1.5 pl-5">
        <span className="text-xs text-muted-foreground" data-testid="atlas-summary-via">
          {via}
        </span>
        {!membership && <ConfidenceBadge confidence={item.best_confidence} showScore={labelStyle === "technical"} />}
        <OriginBadge origin={item.inferred ? "inferred" : "observed"} />
        {item.under_review && <StatusFlag status="under_review" />}
      </div>
    </li>
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
      return "Amber's server can't be reached, so the summary can't be written right now.";
    case "rate_limited":
      return "You've reached the usage limit for now. Please try again later.";
    case "upstream_error":
      return "The AI service did not respond. Please try again in a moment.";
    case "not_found":
      return "This entry is no longer in the atlas, so it can't be summarised.";
    default:
      return "The summary could not be written. Please try again.";
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
  label,
  onShowChain,
}: {
  nodeId: string;
  edgeIds: string[];
  label: string;
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
    <div className="rounded-lg border bg-background/60 p-3" data-testid="atlas-summary-written" aria-live="off">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-1.5 text-xs font-semibold">
          <Bot className="size-3.5 text-primary" aria-hidden />
          Summary of {label.length > 40 ? "this entry" : label}
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
                  <Archive className="size-3" aria-hidden /> Prepared in advance (cached)
                </span>
              ) : (
                <span className="inline-flex items-center gap-1" data-testid="atlas-summary-fresh">
                  <Sparkles className="size-3" aria-hidden /> Written just now
                </span>
              )}
              <span>Numbers show the link each sentence relies on.</span>
              <span>Not medical advice.</span>
            </p>
          )}
        </>
      )}

      {state.kind === "sign_in" && (
        <div className="space-y-2" data-testid="atlas-summary-sign-in">
          <p className="text-sm text-muted-foreground">
            No summary has been prepared for this entry yet. Dr. Wu can write one for you from the links listed here,
            on your own ChatGPT plan.
          </p>
          <Button variant="outline" size="sm" onClick={signIn}>
            <Bot className="text-primary" aria-hidden />
            Sign in to have Dr. Wu write it
          </Button>
        </div>
      )}

      {state.kind === "unavailable" && (
        <p className="text-sm text-muted-foreground" data-testid="atlas-summary-unavailable">
          Written summaries aren&apos;t available on this server yet. The lists below are complete without one.
        </p>
      )}

      {state.kind === "error" && (
        <div className="flex items-start gap-2 text-sm" role="alert" data-testid="atlas-summary-write-error">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-status-flag" aria-hidden />
          <div className="space-y-2">
            <p>{state.message}</p>
            <Button variant="ghost" size="sm" onClick={write}>
              <RefreshCw aria-hidden /> Try again
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
