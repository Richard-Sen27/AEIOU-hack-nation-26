"use client";

import {
  Download,
  Info,
  Map as MapIcon,
  Maximize,
  Minus,
  Plus,
  RotateCcw,
  Route,
  SearchX,
  TriangleAlert,
  WifiOff,
} from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { GraphLegend, VusNotice } from "@/components/graph-ui";
import { useGate } from "@/components/providers/gate-provider";
import { useLens } from "@/components/providers/lens-provider";
import { Button, buttonVariants } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverDescription, PopoverHeader, PopoverTitle, PopoverTrigger } from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { buildUrl, getNeighborhood, getNode, type ApiError, type Schemas } from "@/lib/api";
import { announce } from "@/lib/a11y";
import { nodeTypeMeta, relationLabel } from "@/lib/graph/meta";
import { useGraphTheme } from "@/lib/graph/use-graph-theme";
import { EDGE_FAMILIES, isVus, type EdgeFamily, type EdgeStatus } from "@/lib/graph/types";
import { cn } from "@/lib/utils";

import { EdgePanel } from "./edge-panel";
import { FamilyChips } from "./family-chips";
import { FlagDialog } from "./flag-dialog";
import { NeighbourFilter } from "./neighbour-filter";
import { resolveHints } from "./lens-hints";
import type { NodeGraphHandle } from "./node-graph";
import { NodeList } from "./node-list";
import { NodePanel } from "./node-panel";
import { PathPicker } from "./path-picker";
import { useMediaQuery } from "./use-media-query";
import { useReducedMotion } from "./use-reduced-motion";
import { ViewToggle, type ViewMode } from "./view-toggle";

const NodeGraph = dynamic(() => import("./node-graph"), {
  ssr: false,
  loading: () => (
    <div className="flex size-full items-center justify-center gap-2 text-sm text-muted-foreground" role="status">
      <Spinner className="size-4" /> Drawing the graph…
    </div>
  ),
});

type Load<T> = { kind: "loading" } | { kind: "ready"; data: T } | { kind: "error"; code: string };

const errCode = (e: unknown) => (e as ApiError | undefined)?.code ?? "unknown";

export function NodeView({ nodeId }: { nodeId: string }) {
  const router = useRouter();
  const { role, labelStyle } = useLens();
  const { requireSignIn } = useGate();
  const theme = useGraphTheme();
  const reducedMotion = useReducedMotion();
  /** From 1024 px the page is fixed to the viewport and each column scrolls on its own. */
  const fitViewport = useMediaQuery("(min-width: 1024px)");
  const graph = useRef<NodeGraphHandle>(null);

  const [detail, setDetail] = useState<Load<Schemas.NodeDetail>>({ kind: "loading" });
  const [hood, setHood] = useState<Load<Schemas.Neighborhood>>({ kind: "loading" });
  /** Hubs are capped at their strongest neighbours; the full count comes in a response header. */
  const [hoodTotal, setHoodTotal] = useState<number | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [view, setView] = useState<ViewMode>("graph");
  const [hiddenFamilies, setHiddenFamilies] = useState<Set<EdgeFamily>>(new Set());
  const [edgeId, setEdgeId] = useState<string | null>(null);
  const [statusOverride, setStatusOverride] = useState<Record<string, EdgeStatus>>({});
  const [flagOpen, setFlagOpen] = useState(false);
  const [pathOpen, setPathOpen] = useState(false);
  /** Filter over the loaded neighbourhood; shared by graph and list, client-side only. */
  const [query, setQuery] = useState("");

  // Node details: once per node.
  useEffect(() => {
    let alive = true;
    getNode({ path: { node_id: nodeId }, query: { role }, meta: { quiet: true } })
      .then(({ data, error }) => {
        if (!alive) return;
        setDetail(data ? { kind: "ready", data } : { kind: "error", code: errCode(error) });
      })
      .catch((e) => alive && setDetail({ kind: "error", code: errCode(e) }));
    return () => {
      alive = false;
    };
    // The summary does not depend on the lens enough to refetch on every switch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodeId, attempt]);

  // Neighbourhood: re-fetched when the lens changes (new hints, same elements).
  useEffect(() => {
    let alive = true;
    getNeighborhood({ path: { node_id: nodeId }, query: { role }, meta: { quiet: true } })
      .then(({ data, error, response }) => {
        if (!alive) return;
        const total = Number(response?.headers.get("X-Neighborhood-Total"));
        const truncated = response?.headers.get("X-Neighborhood-Truncated") === "true";
        setHoodTotal(truncated && Number.isFinite(total) && total > 0 ? total : null);
        if (data) {
          setHood((prev) => {
            // Keep the element arrays stable across lens switches when the set is unchanged,
            // so the graph re-styles instead of being rebuilt.
            if (
              prev.kind === "ready" &&
              prev.data.center.id === data.center.id &&
              prev.data.nodes.length === data.nodes.length &&
              prev.data.edges.length === data.edges.length &&
              prev.data.edges.every((e, i) => e.id === data.edges[i]?.id && e.status === data.edges[i]?.status)
            ) {
              return { kind: "ready", data: { ...prev.data, hints: data.hints, cluster: data.cluster } };
            }
            return { kind: "ready", data };
          });
        } else setHood({ kind: "error", code: errCode(error) });
      })
      .catch((e) => alive && setHood({ kind: "error", code: errCode(e) }));
    return () => {
      alive = false;
    };
  }, [nodeId, role, attempt]);

  const hoodData = hood.kind === "ready" ? hood.data : null;
  const detailData = detail.kind === "ready" ? detail.data : null;
  const hints = useMemo(() => resolveHints(hoodData?.hints, role), [hoodData?.hints, role]);

  const edges = useMemo(() => {
    if (!hoodData) return [];
    if (Object.keys(statusOverride).length === 0) return hoodData.edges;
    return hoodData.edges.map((e) =>
      statusOverride[e.id] ? { ...e, status: statusOverride[e.id], flagged: true } : e,
    );
  }, [hoodData, statusOverride]);

  const nodeMap = useMemo(() => new Map((hoodData?.nodes ?? []).map((n) => [n.id, n])), [hoodData]);
  const familyCounts = useMemo(() => {
    const c: Partial<Record<EdgeFamily, number>> = {};
    edges.forEach((e) => (c[e.family] = (c[e.family] ?? 0) + 1));
    return c;
  }, [edges]);
  const presentFamilies = EDGE_FAMILIES.filter((f) => familyCounts[f]);
  const nodeTypes = useMemo(
    () => [...new Set((hoodData?.nodes ?? []).map((n) => n.type))],
    [hoodData],
  );

  const center = hoodData?.center ?? detailData?.node ?? null;
  const selectedEdge = edgeId ? edges.find((e) => e.id === edgeId) ?? null : null;

  // Matches: a neighbour's name, id or kind, or the relation wording shown in the list.
  // The centre itself is left out, or every connection would match its name.
  const filter = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q || !hoodData) return null;
    const centerId = hoodData.center.id;
    const nodeHit = (id: string) => {
      if (id === centerId) return false;
      const n = nodeMap.get(id);
      if (!n) return false;
      return `${n.label}\n${n.id}\n${nodeTypeMeta(n.type).label[labelStyle]}`.toLowerCase().includes(q);
    };
    const nodes = new Set<string>();
    const edgeIds = new Set<string>();
    for (const e of edges) {
      const s = nodeHit(e.source_id);
      const t = nodeHit(e.target_id);
      const rel = relationLabel(e.relation, labelStyle).toLowerCase().includes(q);
      if (s) nodes.add(e.source_id);
      if (t) nodes.add(e.target_id);
      if (s || t || rel) {
        edgeIds.add(e.id);
        if (rel) {
          if (e.source_id !== centerId) nodes.add(e.source_id);
          if (e.target_id !== centerId) nodes.add(e.target_id);
        }
      }
    }
    return { nodes, edges: edgeIds };
  }, [query, hoodData, nodeMap, edges, labelStyle]);
  const visibleEdges = edges.filter((e) => !hiddenFamilies.has(e.family));
  const filterMatches = filter ? visibleEdges.filter((e) => filter.edges.has(e.id)).length : visibleEdges.length;

  useEffect(() => {
    if (hoodData) {
      announce(`Showing ${hoodData.center.label} with ${hoodData.nodes.length - 1} linked items and ${hoodData.edges.length} connections.`);
    }
  }, [hoodData]);

  const openEdge = useCallback(
    (id: string) => {
      setEdgeId(id);
      const e = edges.find((x) => x.id === id);
      if (e) {
        const s = nodeMap.get(e.source_id)?.label ?? e.source_id;
        const t = nodeMap.get(e.target_id)?.label ?? e.target_id;
        announce(`Connection selected: ${s} to ${t}. Sources shown in the side panel.`);
      }
      document.getElementById("node-side")?.scrollTo({ top: 0 });
    },
    [edges, nodeMap],
  );

  const goTo = useCallback(
    (id: string) => {
      const n = nodeMap.get(id);
      if (n) announce(`Opening ${n.label}.`);
      router.push(`/node/${encodeURIComponent(id)}`);
    },
    [nodeMap, router],
  );

  const flag = async () => {
    if (!selectedEdge) return;
    const ok = await requireSignIn(
      "Sign in to flag a connection for review. Flags are checked by a person.",
      `/node/${encodeURIComponent(nodeId)}`,
    );
    if (ok) setFlagOpen(true);
  };

  const markUnderReview = (id: string) => setStatusOverride((s) => ({ ...s, [id]: "under_review" }));

  // ---------- Not found / errors before anything is known ----------
  if (!center) {
    const code = detail.kind === "error" ? detail.code : hood.kind === "error" ? hood.code : null;
    const bothFailed = detail.kind === "error" && hood.kind === "error";
    if (!bothFailed && (detail.kind === "loading" || hood.kind === "loading")) {
      return (
        <div className="mx-auto w-full max-w-[1440px] space-y-4 px-4 py-6 sm:px-6" role="status" aria-label="Loading">
          <h1 className="sr-only">Loading {nodeId}</h1>
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-8 w-80" />
          <div className="grid gap-4 lg:grid-cols-[1fr_400px]">
            <Skeleton className="h-[560px] w-full rounded-xl" />
            <Skeleton className="h-[560px] w-full rounded-xl" />
          </div>
        </div>
      );
    }
    const notFound = code === "not_found";
    const offline = code === "network_error";
    const Icon = notFound ? SearchX : offline ? WifiOff : TriangleAlert;
    return (
      <div className="mx-auto flex w-full max-w-lg flex-1 flex-col items-center justify-center gap-3 px-4 py-20 text-center" data-testid="node-error">
        <span className="flex size-11 items-center justify-center rounded-full bg-muted">
          <Icon className="size-5 text-muted-foreground" aria-hidden />
        </span>
        <h1 className="text-xl font-semibold tracking-tight">
          {notFound ? "This item is not in the atlas" : offline ? "Amber's server can't be reached" : code === "not_implemented" ? "This view is not available yet" : "This item could not be loaded"}
        </h1>
        <p className="text-sm text-muted-foreground">
          {notFound ? (
            <>
              Nothing has the ID <span className="font-mono text-foreground">{nodeId}</span>. Try searching by name.
            </>
          ) : (
            "Please try again in a moment."
          )}
        </p>
        <div className="flex gap-2">
          {!notFound && (
            <Button
              onClick={() => {
                setDetail({ kind: "loading" });
                setHood({ kind: "loading" });
                setAttempt((a) => a + 1);
              }}
            >
              <RotateCcw data-icon="inline-start" aria-hidden /> Try again
            </Button>
          )}
          <Link href="/atlas" className={buttonVariants({ variant: "outline" })}>
            Go to the Atlas
          </Link>
        </div>
      </div>
    );
  }

  const meta = nodeTypeMeta(center.type);
  const Icon = meta.icon;
  const classification = detailData?.classification ?? (center.attrs?.classification as string | undefined);
  const exportUrl = (format: "csv" | "graphml") => buildUrl("/export/graph", { node: center.id, depth: 1, format });

  return (
    <div
      className="mx-auto w-full max-w-[1440px] px-4 py-5 sm:px-6 lg:flex lg:min-h-0 lg:flex-1 lg:flex-col"
      data-fit-viewport={fitViewport || undefined}
      data-testid="node-view"
    >
      {/* Header */}
      <header className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0 space-y-1">
          <nav aria-label="Breadcrumb" className="text-xs text-muted-foreground">
            <Link href="/atlas" className="hover:text-foreground hover:underline">Atlas</Link>
            <span aria-hidden> / </span>
            <span>{meta.label[labelStyle]}</span>
          </nav>
          <h1 className="flex items-center gap-2.5 text-2xl font-semibold tracking-tight text-balance">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border bg-card" style={{ color: `var(${meta.colorVar})` }}>
              <Icon className="size-4.5" aria-hidden />
            </span>
            {center.label}
          </h1>
          <p className="font-mono text-xs text-muted-foreground" data-testid="node-id">
            {center.id}
            {hoodData && (
              <span className="font-sans" data-testid="node-counts">
                {" "}· {hoodData.nodes.length} items · {hoodData.edges.length} connections
              </span>
            )}
          </p>
          {hoodData && hoodTotal != null && hoodTotal > hoodData.nodes.length - 1 && (
            <p className="text-xs text-muted-foreground" data-testid="node-truncated">
              Showing the {(hoodData.nodes.length - 1).toLocaleString("en")} strongest of {hoodTotal.toLocaleString("en")} links
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => setPathOpen(true)} data-testid="find-path">
            <Route data-icon="inline-start" aria-hidden /> Find a path to…
          </Button>
          <Link href={`/atlas?focus=${encodeURIComponent(center.id)}`} className={buttonVariants({ variant: "outline", size: "sm" })} data-testid="open-in-atlas">
            <MapIcon data-icon="inline-start" aria-hidden /> Open in Atlas
          </Link>
          <Popover>
            <PopoverTrigger render={<Button variant="outline" size="sm" data-testid="export" />}>
              <Download data-icon="inline-start" aria-hidden /> Export
            </PopoverTrigger>
            <PopoverContent align="end" className="w-72">
              <PopoverHeader>
                <PopoverTitle>Download this neighbourhood</PopoverTitle>
                <PopoverDescription className="text-xs">
                  {center.label} and everything directly connected, with sources and confidence.
                </PopoverDescription>
              </PopoverHeader>
              <div className="grid gap-1.5">
                <a href={exportUrl("csv")} download className={cn(buttonVariants({ variant: "outline", size: "sm" }), "justify-start")} data-testid="export-csv">
                  CSV <span className="text-muted-foreground">· spreadsheets</span>
                </a>
                <a href={exportUrl("graphml")} download className={cn(buttonVariants({ variant: "outline", size: "sm" }), "justify-start")} data-testid="export-graphml">
                  GraphML <span className="text-muted-foreground">· Gephi, Cytoscape</span>
                </a>
              </div>
            </PopoverContent>
          </Popover>
        </div>
      </header>

      {isVus(classification) && <VusNotice className="mb-4" />}

      <div className="grid gap-4 lg:min-h-0 lg:flex-1 lg:grid-cols-[minmax(0,1fr)_400px] lg:grid-rows-[minmax(0,1fr)]">
        {/* Graph / list */}
        <section aria-label="Neighbourhood" className="flex min-w-0 flex-col overflow-hidden rounded-xl border bg-card lg:min-h-0">
          <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2">
            {presentFamilies.length > 0 && (
              <FamilyChips
                families={presentFamilies}
                counts={familyCounts}
                active={new Set(EDGE_FAMILIES.filter((f) => !hiddenFamilies.has(f)))}
                highlighted={hints.highlight_family}
                onToggle={(f) =>
                  setHiddenFamilies((s) => {
                    const n = new Set(s);
                    if (n.has(f)) n.delete(f);
                    else n.add(f);
                    return n;
                  })
                }
              />
            )}
            <div className="flex w-full items-center gap-2 sm:ml-auto sm:w-auto">
              <NeighbourFilter
                value={query}
                onChange={setQuery}
                matches={filterMatches}
                total={visibleEdges.length}
                className="min-w-0 flex-1 sm:w-56 sm:flex-none"
              />
              <ViewToggle value={view} onChange={setView} graphLabel="Graph" className="shrink-0" />
            </div>
          </div>
          <div
            className={cn(
              "relative lg:min-h-0 lg:flex-1",
              view === "graph" ? "bg-atlas-grid h-[min(62vh,620px)] min-h-[380px] lg:h-auto" : "min-h-[380px] lg:overflow-hidden",
            )}
          >
            {hood.kind === "error" ? (
              <div className="flex h-full items-center justify-center p-6 text-center text-sm text-muted-foreground" role="status" data-testid="hood-error">
                {hood.code === "not_implemented"
                  ? "The connections view is not available yet. The summary is on the right."
                  : "The connections could not be loaded. Please try again in a moment."}
              </div>
            ) : !hoodData || !theme ? (
              <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground" role="status">
                <Spinner className="size-4" /> Loading connections…
              </div>
            ) : view === "graph" ? (
              <>
                <p id="node-graph-label" className="sr-only">
                  Graph of {center.label} and {hoodData.nodes.length - 1} linked items. Select one to open it. The list view
                  shows the same connections as a table.
                </p>
                <NodeGraph
                  ref={graph}
                  centerId={center.id}
                  nodes={hoodData.nodes}
                  edges={edges}
                  hints={hints}
                  labelStyle={labelStyle}
                  theme={theme}
                  hiddenFamilies={hiddenFamilies}
                  filter={filter}
                  selectedEdgeId={edgeId}
                  onNodeTap={goTo}
                  onEdgeTap={openEdge}
                  reducedMotion={reducedMotion}
                  labelledBy="node-graph-label"
                />
                <div className="absolute top-3 left-3 flex flex-col overflow-hidden rounded-lg border bg-card/90 shadow-xs backdrop-blur">
                  <Button variant="ghost" size="icon-sm" className="rounded-none" aria-label="Zoom in" onClick={() => graph.current?.zoomIn()}>
                    <Plus aria-hidden />
                  </Button>
                  <Button variant="ghost" size="icon-sm" className="rounded-none border-y" aria-label="Zoom out" onClick={() => graph.current?.zoomOut()}>
                    <Minus aria-hidden />
                  </Button>
                  <Button variant="ghost" size="icon-sm" className="rounded-none" aria-label="Fit to view" onClick={() => graph.current?.fit()}>
                    <Maximize aria-hidden />
                  </Button>
                </div>
                <Popover>
                  <PopoverTrigger
                    render={
                      <Button
                        variant="outline"
                        size="sm"
                        className="absolute bottom-3 left-3 bg-card/90 shadow-xs backdrop-blur"
                        aria-label="Key: what the lines, colours and icons mean"
                        data-testid="legend-toggle"
                      />
                    }
                  >
                    <Info data-icon="inline-start" aria-hidden /> Key
                  </PopoverTrigger>
                  <PopoverContent side="top" align="start" className="w-auto max-w-[min(22rem,calc(100vw-2rem))]">
                    <PopoverHeader className="sr-only">
                      <PopoverTitle>Key</PopoverTitle>
                    </PopoverHeader>
                    <GraphLegend
                      nodeTypes={nodeTypes}
                      families={presentFamilies.length ? presentFamilies : undefined}
                      className="border-0 bg-transparent p-0 backdrop-blur-none"
                    />
                  </PopoverContent>
                </Popover>
              </>
            ) : (
              <NodeList
                centerId={center.id}
                edges={edges}
                nodes={nodeMap}
                hiddenFamilies={hiddenFamilies}
                matchingEdges={filter?.edges ?? null}
                query={query.trim()}
                onClearQuery={() => setQuery("")}
                selectedEdgeId={edgeId}
                onEdge={openEdge}
              />
            )}
          </div>
        </section>

        {/* Side panel */}
        <aside
          id="node-side"
          aria-label={selectedEdge ? "Connection details" : "Summary and connections"}
          className="relative min-w-0 rounded-xl border bg-card lg:min-h-0 lg:overflow-y-auto"
        >
          {selectedEdge ? (
            <EdgePanel
              key={selectedEdge.id}
              edge={selectedEdge}
              nodes={nodeMap}
              onBack={() => setEdgeId(null)}
              onFlag={flag}
            />
          ) : (
            <NodePanel
              detail={detailData}
              center={center}
              edges={edges}
              nodes={nodeMap}
              highlightFamilies={hints.highlight_family ?? []}
              hiddenFamilies={hiddenFamilies}
              onEdge={openEdge}
            />
          )}
        </aside>
      </div>

      <PathPicker fromId={center.id} fromLabel={center.label} open={pathOpen} onOpenChange={setPathOpen} />
      {selectedEdge && (
        <FlagDialog
          edgeId={selectedEdge.id}
          open={flagOpen}
          onOpenChange={setFlagOpen}
          onFlagged={(r) => {
            markUnderReview(r.edge_id);
            toast("Thanks, this connection is now under review", {
              description: "It stays visible, marked as under review, until someone checks it.",
            });
            announce("Flag sent. The connection is now under review.");
          }}
          onAlreadyFlagged={() => {
            markUnderReview(selectedEdge.id);
            toast("You already flagged this connection", { description: "It is under review." });
          }}
        />
      )}
    </div>
  );
}
