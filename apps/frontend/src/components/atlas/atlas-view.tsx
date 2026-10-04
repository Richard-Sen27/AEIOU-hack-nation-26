"use client";

import { Boxes, ChevronDown, ChevronUp, Compass, Minus, Plus, RotateCcw, SlidersHorizontal, TriangleAlert, WifiOff } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { GraphLegend } from "@/components/graph-ui";
import { FamilyChips } from "@/components/node/family-chips";
import { useReducedMotion } from "@/components/node/use-reduced-motion";
import { ViewToggle, type ViewMode } from "@/components/node/view-toggle";
import { useLens } from "@/components/providers/lens-provider";
import { useSession } from "@/components/providers/session-provider";
import { AtlasTour } from "@/components/tour/atlas-tour";
import { Button, buttonVariants } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Spinner } from "@/components/ui/spinner";
import { getAtlasTree, type ApiError } from "@/lib/api";
import { announce } from "@/lib/a11y";
import { nodeTypeMeta } from "@/lib/graph/meta";
import { useGraphTheme } from "@/lib/graph/use-graph-theme";
import { EDGE_FAMILIES, type EdgeFamily } from "@/lib/graph/types";
import { cn } from "@/lib/utils";

import type { AtlasCanvasHandle } from "./atlas-canvas";
import { categoryLabel } from "./atlas-categories";
import { lensStartCategory, treeFacets } from "./atlas-model";
import { AtlasOutline } from "./atlas-outline";
import { AtlasPanel } from "./atlas-panel";
import { takeAtlasHandoff } from "./atlas-handoff";
import type { AtlasSelect, WuFound } from "./atlas-props";
import { resolveRoute } from "./atlas-wu-path";
import { AtlasSearch } from "./atlas-search";
import { AtlasWuDock } from "./atlas-wu-dock";
import { buildTreeIndex, type TreeIndex } from "./tree-model";

export const TOUR_SPOT =
  "data-[tour-active]:ring-2 data-[tour-active]:ring-primary data-[tour-active]:ring-offset-2 data-[tour-active]:ring-offset-background";

const AtlasCanvas = dynamic(() => import("./atlas-canvas"), {
  ssr: false,
  loading: () => <CanvasLoading />,
});

type Load = { kind: "loading" } | { kind: "ready"; index: TreeIndex } | { kind: "error"; code: string };

function CanvasLoading() {
  return (
    <div className="flex size-full items-center justify-center gap-2 text-sm text-muted-foreground" role="status">
      <Spinner className="size-4" /> Drawing the map…
    </div>
  );
}

/** Edit the current URL's query without a navigation (no health data ever goes here). */
function editUrl(edit: (params: URLSearchParams) => void) {
  const url = new URL(window.location.href);
  edit(url.searchParams);
  window.history.replaceState(null, "", url.pathname + url.search);
}

export function AtlasView() {
  const params = useSearchParams();
  const focusParam = params.get("focus");
  const tourParam = params.get("tour") === "1";
  const pathParam = params.get("path");
  const { role, labelStyle } = useLens();
  // A signed-in user's role (the lens default) is known only once the session has loaded.
  const lensKnown = useSession().status !== "loading";
  const theme = useGraphTheme();
  const reducedMotion = useReducedMotion();
  const canvas = useRef<AtlasCanvasHandle>(null);

  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [view, setView] = useState<ViewMode>("graph");
  const [hiddenFamilies, setHiddenFamilies] = useState<Set<EdgeFamily>>(new Set());
  const [selected, setSelected] = useState<string | null>(focusParam);
  /** The last id selected inside the view (search, panel, map, Dr. Wu), as opposed to a `?focus=` link. */
  const [pickedId, setPickedId] = useState<string | null>(null);
  /** Chain drawn from the panel (a summary item's `via`). */
  const [panelChain, setPanelChain] = useState<string[]>([]);
  /** Dr. Wu's finds and the question handed over from search: React state only, never the URL. */
  const [found, setFound] = useState<WuFound | null>(null);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [canvasFailed, setCanvasFailed] = useState(false);
  const [tourOpen, setTourOpen] = useState(tourParam);
  // Read by the canvas once, when it mounts (after the tree and the lens are known), so a
  // role change in settings does not move the camera until the Atlas is opened again.
  const startCategory = lensStartCategory(role);
  // The panel floats over the right of the canvas from lg up; framing keeps clear of it.
  // Read synchronously on the client so the panel mounts in its final place (the loading
  // state rendered during hydration does not depend on it).
  const [wide, setWide] = useState(
    () => typeof window !== "undefined" && window.matchMedia("(min-width: 1024px)").matches,
  );
  /** Phone: the summary sheet starts short and can be expanded. */
  const [sheetExpanded, setSheetExpanded] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const sync = () => setWide(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    let alive = true;
    getAtlasTree({ meta: { quiet: true } })
      .then(({ data, error }) => {
        if (!alive) return;
        if (error || !data) {
          setLoad({ kind: "error", code: (error as unknown as ApiError | undefined)?.code ?? "unknown" });
          return;
        }
        const index = buildTreeIndex(data);
        setLoad({ kind: "ready", index });
        announce(`Atlas loaded: ${index.entityCount} items and ${index.connectionCount} connections.`);
        // Dr. Wu's finds handed over from /chat in memory (never the URL): treat them as the dock's finds.
        // Ids that are not in the tree exist but are not on the map: listed, not ringed.
        const handed = takeAtlasHandoff();
        const allIds =
          handed?.nodeIds.filter((id, i, all) => all.indexOf(id) === i && (index.nodes.get(id)?.kind ?? "entity") === "entity") ?? [];
        const nodeIds = allIds.filter((id) => index.nodes.has(id));
        if (handed && allIds.length > 0) {
          setFound({ nodeIds, edgeIds: handed.edgeIds.filter((id) => index.edges.has(id)), allIds, names: handed.names });
          announce(foundMessage(allIds.length, nodeIds.length));
        }
        if (handed && handed.edgeIds.length > 0) {
          // A found connection: draw the whole route, also links outside the tree (atlas-wu-path).
          void resolveRoute(index, handed.edgeIds).then((route) => {
            if (!alive) return;
            setFound((f) => {
              const all = [...(f?.allIds ?? allIds)];
              const names = { ...(f?.names ?? handed.names) };
              for (const n of route.nodes) {
                if (!all.includes(n.id)) all.push(n.id);
                if (!names[n.id]) names[n.id] = { label: n.label, type: n.type };
              }
              return { nodeIds: all.filter((id) => index.nodes.get(id)?.kind === "entity"), edgeIds: route.edgeIds, allIds: all, names };
            });
          });
        }
        if (handed && nodeIds.length > 0) {
          // Frame them once the (lazily loaded) canvas is up. Nothing is selected, so no panel
          // link carries a found id until the user picks one.
          let tries = 0;
          const tick = () => {
            if (!alive) return;
            if (canvas.current) requestAnimationFrame(() => canvas.current?.frameNodes(nodeIds));
            else if (tries++ < 600) requestAnimationFrame(tick);
          };
          requestAnimationFrame(tick);
        }
      })
      .catch((e: ApiError) => alive && setLoad({ kind: "error", code: e?.code ?? "unknown" }));
    return () => {
      alive = false;
    };
  }, [attempt]);

  const index = load.kind === "ready" ? load.index : null;
  const facets = useMemo(() => (index ? treeFacets(index) : null), [index]);

  const [pathCleared, setPathCleared] = useState(false);
  const pathEdgeIds = useMemo(() => {
    if (!index || !pathParam || pathCleared) return [];
    return pathParam
      .split(",")
      .map((s) => s.trim())
      .filter((id) => id && index.edges.has(id))
      .slice(0, 50);
  }, [index, pathParam, pathCleared]);
  const chainEdgeIds = useMemo(
    () => (panelChain.length > 0 ? panelChain : pathEdgeIds),
    [panelChain, pathEdgeIds],
  );

  // `?focus=<id>` changing later (back/forward, a link): select it and frame it.
  const [prevFocus, setPrevFocus] = useState(focusParam);
  if (focusParam !== prevFocus) {
    setPrevFocus(focusParam);
    if (focusParam) {
      setSelected(focusParam);
      // A link (back/forward, another page), not the URL the view wrote for its own pick.
      if (focusParam !== pickedId) setPickedId(null);
    }
  }
  /**
   * A selected id that is not in the tree: either a node that exists but is not on the map (its
   * summary opens in the panel) or an id that does not exist at all (the summary says 404).
   */
  const [missingIds, setMissingIds] = useState<ReadonlySet<string>>(() => new Set());
  const offMap = index && selected && !index.nodes.has(selected) ? selected : null;
  const missingFocus = offMap && missingIds.has(offMap) ? offMap : null;
  // The reworded notice is for `?focus=` links only, not for a pick from search or Dr. Wu.
  const offMapNotice = offMap && !missingFocus && offMap === focusParam && offMap !== pickedId ? offMap : null;
  const mounted = useRef(false);
  useEffect(() => {
    // The canvas frames the initial focus/path itself; this handles later URL changes.
    if (!index) return;
    if (!mounted.current) {
      mounted.current = true;
      return;
    }
    const id = requestAnimationFrame(() => {
      if (pathEdgeIds.length > 0) canvas.current?.focusEdges(pathEdgeIds);
      else if (focusParam && index.nodes.has(focusParam)) canvas.current?.focusNode(focusParam);
    });
    return () => cancelAnimationFrame(id);
  }, [index, focusParam, pathEdgeIds]);

  const select: AtlasSelect = useCallback(
    (id, { center = false, persist = true } = {}) => {
      setSelected(id);
      setPickedId(id);
      setSheetExpanded(false);
      if (!id) setPanelChain([]);
      editUrl((p) => {
        // Anything Dr. Wu found stays out of the URL (docs/compliance.md): drop a stale focus too.
        if (id && persist) p.set("focus", id);
        else p.delete("focus");
        p.delete("tour");
      });
      if (id && index) {
        const n = index.nodes.get(id);
        if (n) {
          const what =
            n.kind === "entity" && n.entity_type
              ? `${nodeTypeMeta(n.entity_type).label[labelStyle]}, ${index.incident.get(id)?.length ?? 0} connections`
              : n.kind === "category" && n.category
                ? `${categoryLabel(n.category, labelStyle)}, ${n.entity_count} items`
                : `group of ${n.entity_count} items`;
          announce(`Selected ${n.label}, ${what}.`);
        }
        // A node that is not on the map has nothing to frame: the camera stays where it is.
        if (center && n) canvas.current?.focusNode(id);
      } else if (!id) {
        announce("Selection cleared.");
      }
    },
    [index, labelStyle],
  );

  // `/` focuses the map search from anywhere in the view (not while typing). Capture phase,
  // so the site-wide search palette (also on `/`) does not open over the Atlas.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName))) return;
      const input = document.querySelector<HTMLInputElement>('[data-testid="atlas-search"] input');
      if (!input) return;
      e.preventDefault();
      e.stopPropagation();
      input.focus();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, []);

  const visibleFamilies = useMemo(
    () => new Set(EDGE_FAMILIES.filter((f) => !hiddenFamilies.has(f))),
    [hiddenFamilies],
  );
  const toggleFamily = (f: EdgeFamily) =>
    setHiddenFamilies((s) => {
      const next = new Set(s);
      if (next.has(f)) next.delete(f);
      else next.add(f);
      return next;
    });

  const onFound = useCallback(
    (next: WuFound) => {
      setFound(next);
      const total = next.allIds?.length ?? next.nodeIds.length;
      if (total > 0) announce(foundMessage(total, next.nodeIds.length));
      if (next.nodeIds.length > 0) requestAnimationFrame(() => canvas.current?.frameNodes(next.nodeIds));
    },
    [],
  );

  const header = (
    <div className="flex shrink-0 items-center gap-x-3 border-b bg-background/80 px-3 py-2 backdrop-blur sm:gap-x-4 sm:px-6">
      <div className="mr-auto min-w-0">
        <h1 className="text-base font-semibold tracking-tight">Atlas</h1>
        <p className="truncate text-xs text-muted-foreground" id="atlas-desc">
          {index ? (
            <span data-testid="atlas-counts">
              {index.entityCount.toLocaleString("en")} items · {index.connectionCount.toLocaleString("en")} connections
            </span>
          ) : (
            "The whole map, one tree per kind of item."
          )}
        </p>
      </div>
      {index && facets && (
        <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
          <ViewToggle value={view} onChange={setView} graphLabel="Map" />
          <Popover>
            <PopoverTrigger
              render={
                <Button
                  variant="outline"
                  size="sm"
                  aria-label="Filters"
                  data-testid="atlas-filters"
                  data-tour="filters"
                  className={TOUR_SPOT}
                />
              }
            >
              <SlidersHorizontal data-icon="inline-start" aria-hidden />
              <span className="max-sm:sr-only">Filters</span>
              {hiddenFamilies.size > 0 && (
                <span className="rounded-full bg-primary px-1.5 text-[10px] text-primary-foreground">{hiddenFamilies.size}</span>
              )}
            </PopoverTrigger>
            <PopoverContent
              align="end"
              className="max-h-[min(36rem,calc(100dvh-8rem))] w-[22rem] max-w-[calc(100vw-2rem)] gap-4 overflow-y-auto p-4"
            >
              <fieldset>
                <legend className="mb-1 text-xs font-medium text-muted-foreground">Connections drawn on click</legend>
                <p className="mb-2 text-[11px] text-muted-foreground">
                  Click a dot to draw its connections. Only these kinds are drawn.
                </p>
                <FamilyChips
                  families={facets.presentFamilies}
                  counts={Object.fromEntries(facets.familyCounts)}
                  active={visibleFamilies}
                  onToggle={toggleFamily}
                />
              </fieldset>
              {hiddenFamilies.size > 0 && (
                <Button variant="ghost" size="sm" className="self-start" onClick={() => setHiddenFamilies(new Set())}>
                  Draw every kind
                </Button>
              )}
              <section data-tour="legend">
                <h3 className="mb-2 text-xs font-medium text-muted-foreground">Key</h3>
                <GraphLegend
                  families={facets.presentFamilies}
                  nodeTypes={facets.presentTypes}
                  className="border-0 bg-transparent p-0 backdrop-blur-none"
                />
              </section>
            </PopoverContent>
          </Popover>
          <Button
            variant={role === "guest" ? "secondary" : "ghost"}
            size="sm"
            onClick={() => setTourOpen(true)}
            aria-label="Tour"
            data-testid="tour-start"
          >
            <Compass data-icon="inline-start" aria-hidden />
            <span className="max-sm:sr-only">Tour</span>
          </Button>
        </div>
      )}
    </div>
  );

  let body: React.ReactNode;
  if (load.kind === "loading" || !theme || !lensKnown) {
    body = (
      <div className="bg-atlas-grid flex min-h-0 flex-1 items-center justify-center" role="status" data-testid="atlas-loading">
        <span className="flex items-center gap-2 rounded-full border bg-card px-3 py-1.5 text-sm text-muted-foreground shadow-xs">
          <Spinner className="size-4" /> Loading the atlas…
        </span>
      </div>
    );
  } else if (load.kind === "error") {
    const offline = load.code === "network_error";
    const notYet = load.code === "not_implemented";
    body = (
      <StateMessage
        testId="atlas-error"
        icon={offline ? WifiOff : TriangleAlert}
        title={offline ? "Amber's server can't be reached" : notYet ? "The atlas is not available yet" : "The atlas could not be loaded"}
        description={
          offline
            ? "The map needs the server to load. Check your connection and try again."
            : notYet
              ? "The whole-graph map is still being prepared. You can already search for a disease, gene or symptom."
              : "Something went wrong on our side. Trying again usually helps."
        }
        action={
          <Button
            onClick={() => {
              setLoad({ kind: "loading" });
              setAttempt((a) => a + 1);
            }}
          >
            <RotateCcw data-icon="inline-start" aria-hidden /> Try again
          </Button>
        }
      />
    );
  } else if (load.index.entityCount === 0) {
    body = (
      <StateMessage
        testId="atlas-empty"
        icon={Boxes}
        title="The atlas is empty for now"
        description="No diseases, genes or other items have been loaded yet. Once the data pipeline has run, the map appears here."
        action={
          <Link href="/" className={buttonVariants({ variant: "outline" })}>
            Back to the start
          </Link>
        }
      />
    );
  } else {
    const idx = load.index;
    const showGraph = view === "graph" && !canvasFailed;
    const panelOpen = !!selected && (idx.nodes.has(selected) || !missingIds.has(selected));
    const panel = (className: string) => (
      <AtlasPanel
        index={idx}
        nodeId={selected}
        onSelect={(id) => select(id, { center: true })}
        onShowChain={setPanelChain}
        onClose={() => select(null)}
        onMissing={(id) => setMissingIds((s) => new Set(s).add(id))}
        className={className}
      />
    );
    const sheet = (className: string, inOutline: boolean) => (
      <div
        className={cn(
          "flex flex-col",
          sheetExpanded ? (inOutline ? "max-h-[70dvh]" : "max-h-[78dvh]") : "max-h-[40dvh]",
          className,
        )}
        data-testid="atlas-sheet"
      >
        <button
          type="button"
          aria-expanded={sheetExpanded}
          onClick={() => setSheetExpanded((e) => !e)}
          className="z-10 mx-auto -mb-2.5 flex h-6 shrink-0 items-center gap-1 rounded-full border bg-card px-3 text-xs font-medium text-muted-foreground shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {sheetExpanded ? <ChevronDown className="size-3.5" aria-hidden /> : <ChevronUp className="size-3.5" aria-hidden />}
          {sheetExpanded ? "Show less" : "Show more"}
        </button>
        {panel("min-h-0 shrink")}
      </div>
    );
    body = (
      <div className="relative flex min-h-0 flex-1">
        {showGraph ? (
          <div
            className={cn(
              "bg-atlas-grid relative min-w-0 flex-1",
              TOUR_SPOT,
              "data-[tour-active]:ring-inset data-[tour-active]:ring-offset-0",
            )}
            data-tour="canvas"
          >
            <p id="atlas-canvas-label" className="sr-only">
              Map of {idx.entityCount} items in {idx.categories.size} trees around the Amber logo. Click a dot to draw its
              connections. Arrow keys pan, plus and minus zoom, 0 shows the whole map, Escape clears the selection, slash
              searches. The outline view lists the same items as a tree.
            </p>
            <AtlasCanvas
              ref={canvas}
              index={idx}
              theme={theme}
              labelStyle={labelStyle}
              visibleFamilies={visibleFamilies}
              selectedId={selected && idx.nodes.has(selected) ? selected : null}
              chainEdgeIds={chainEdgeIds}
              found={found}
              startCategory={startCategory}
              insetRight={wide && panelOpen ? 376 : 0}
              insetBottomShare={!wide && panelOpen ? (sheetExpanded ? 0.7 : 0.55) : 0}
              onSelect={(id) => {
                setPanelChain([]);
                select(id);
              }}
              onError={() => setCanvasFailed(true)}
              reducedMotion={reducedMotion}
              labelledBy="atlas-canvas-label"
            />
            <div className="absolute top-3 left-3 z-10 flex flex-col max-sm:top-16 overflow-hidden rounded-lg border bg-card/90 shadow-xs backdrop-blur">
              <Button variant="ghost" size="icon-sm" className="rounded-none" aria-label="Zoom in" onClick={() => canvas.current?.zoomIn()}>
                <Plus aria-hidden />
              </Button>
              <Button
                variant="ghost"
                size="icon-sm"
                className="rounded-none border-y"
                aria-label="Zoom out"
                onClick={() => canvas.current?.zoomOut()}
              >
                <Minus aria-hidden />
              </Button>
              <Button
                variant="ghost"
                size="icon-sm"
                className="rounded-none"
                aria-label="Show the whole map"
                onClick={() => canvas.current?.reset()}
              >
                <RotateCcw aria-hidden />
              </Button>
            </div>
          </div>
        ) : (
          <div className={cn("flex min-h-0 min-w-0 flex-1 flex-col", panelOpen && "lg:pr-[23.5rem]")}>
            {canvasFailed && view === "graph" && (
              <p className="shrink-0 border-b bg-status-flag/10 px-4 py-2 text-sm" role="status">
                The map can&apos;t be drawn on this device, so the outline is shown instead.
              </p>
            )}
            <AtlasOutline
              index={idx}
              selectedId={selected}
              onSelect={(id) => select(id)}
              className="min-h-0 flex-1"
            />
            {/* Phone: the sheet sits below the outline instead of over it. */}
            {panelOpen && !wide && sheet("shrink-0 border-t px-2 pt-1 pb-2", true)}
          </div>
        )}

        {/* Over the canvas: search centred on the page, notices below it. With the panel open it
            narrows symmetrically so it stays centred and clear of the panel. */}
        <div className="pointer-events-none absolute inset-x-3 top-3 z-20 flex flex-col items-center gap-2">
          {showGraph && (
            <AtlasSearch
              index={idx}
              onPick={(id) => {
                setPanelChain([]);
                select(id, { center: true });
              }}
              onAskWu={(text) => setPendingQuestion(text)}
              className={cn("pointer-events-auto", panelOpen && "lg:max-w-[min(28rem,calc(100%-46.5rem))]")}
            />
          )}
          {pathEdgeIds.length > 0 && panelChain.length === 0 && showGraph && (
            <div
              className="pointer-events-auto flex items-center gap-3 rounded-full border bg-card py-1 pr-1 pl-3 text-sm shadow-md"
              role="status"
              data-testid="atlas-path-banner"
            >
              <span>
                Showing a path of {pathEdgeIds.length} connection{pathEdgeIds.length === 1 ? "" : "s"}
              </span>
              <Button
                variant="ghost"
                size="xs"
                onClick={() => {
                  setPathCleared(true);
                  editUrl((p) => p.delete("path"));
                }}
              >
                Show everything
              </Button>
            </div>
          )}
          {offMapNotice && (
            <div
              className="pointer-events-auto w-[min(28rem,100%)] rounded-lg border bg-card px-3 py-2 text-sm shadow-md"
              role="status"
              data-testid="atlas-missing-focus"
              data-reason="off-map"
            >
              <span className="font-mono text-xs">{offMapNotice}</span> isn&apos;t on the map yet. Its summary is open.
            </div>
          )}
          {missingFocus && (
            <div
              className="pointer-events-auto w-[min(28rem,100%)] rounded-lg border bg-card px-3 py-2 text-sm shadow-md"
              role="status"
              data-testid="atlas-missing-focus"
              data-reason="unknown"
            >
              <span className="font-mono text-xs">{missingFocus}</span> is not on the map.{" "}
              <Link className="underline underline-offset-2" href={`/node/${encodeURIComponent(missingFocus)}`}>
                Open it directly
              </Link>
            </div>
          )}
        </div>

        <AtlasWuDock
          index={idx}
          pendingQuestion={pendingQuestion}
          onPendingConsumed={() => setPendingQuestion(null)}
          found={found}
          onFound={onFound}
          onClear={() => setFound(null)}
          onSelect={select}
          className={cn(
            "absolute bottom-3 left-3 z-30 max-w-[calc(100%-1.5rem)] lg:max-w-[22rem]",
            panelOpen && "max-lg:hidden",
          )}
        />

        {/* The panel exists only while something is selected: no card, no reserved space otherwise.
            Desktop: floating on the right. Phone: a short sheet over the map that can be expanded. */}
        {panelOpen && wide && panel("absolute top-3 right-3 bottom-3 z-30 w-[22rem]")}
        {panelOpen && !wide && showGraph && sheet("absolute inset-x-2 bottom-2 z-30", false)}
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-fit-viewport data-testid="atlas-view">
      {header}
      {body}
      {index && (
        <AtlasTour
          open={tourOpen}
          onOpenChange={(o) => {
            setTourOpen(o);
            if (!o && tourParam) editUrl((p) => p.delete("tour"));
          }}
          onBeforeStep={(target) => {
            if (target && target !== "filters") setView("graph");
          }}
        />
      )}
    </div>
  );
}

/** "Dr. Wu found 3 items, 2 on the map." */
function foundMessage(total: number, onMap: number): string {
  const items = `${total} item${total === 1 ? "" : "s"}`;
  return onMap === total ? `Dr. Wu found ${items} on the map.` : `Dr. Wu found ${items}, ${onMap} on the map.`;
}

function StateMessage({
  icon: Icon,
  title,
  description,
  action,
  testId,
}: {
  icon: typeof Boxes;
  title: string;
  description: string;
  action?: React.ReactNode;
  testId?: string;
}) {
  return (
    <div className="bg-atlas-grid flex min-h-0 flex-1 items-center justify-center p-6" data-testid={testId}>
      <div className="flex max-w-md flex-col items-center gap-3 rounded-xl border bg-card px-6 py-8 text-center shadow-xs">
        <span className="flex size-10 items-center justify-center rounded-full bg-muted">
          <Icon className="size-5 text-muted-foreground" aria-hidden />
        </span>
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="text-sm text-pretty text-muted-foreground">{description}</p>
        {action}
      </div>
    </div>
  );
}
