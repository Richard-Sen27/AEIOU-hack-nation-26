"use client";

import {
  Boxes,
  ChevronDown,
  Compass,
  Minus,
  Plus,
  RotateCcw,
  SlidersHorizontal,
  TriangleAlert,
  WifiOff,
} from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { GraphLegend } from "@/components/graph-ui";
import { FamilyChips } from "@/components/node/family-chips";
import { useReducedMotion } from "@/components/node/use-reduced-motion";
import { ViewToggle, type ViewMode } from "@/components/node/view-toggle";
import { useLens } from "@/components/providers/lens-provider";
import { AtlasTour } from "@/components/tour/atlas-tour";
import { Button, buttonVariants } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Spinner } from "@/components/ui/spinner";
import { getAtlas, type ApiError } from "@/lib/api";
import { announce } from "@/lib/a11y";
import { nodeTypeMeta } from "@/lib/graph/meta";
import { useGraphTheme } from "@/lib/graph/use-graph-theme";
import { EDGE_FAMILIES, NODE_TYPES, type EdgeFamily, type NodeType } from "@/lib/graph/types";
import { cn } from "@/lib/utils";

import type { AtlasCanvasHandle, ColorBy } from "./atlas-canvas";
import { AtlasFind } from "./atlas-find";
import { AtlasList } from "./atlas-list";
import { buildAtlasIndex, clusterColor, type AtlasIndex, type AtlasPayload } from "./atlas-model";
import { AtlasPanel } from "./atlas-panel";

export const TOUR_SPOT =
  "data-[tour-active]:ring-2 data-[tour-active]:ring-primary data-[tour-active]:ring-offset-2 data-[tour-active]:ring-offset-background";

const AtlasCanvas = dynamic(() => import("./atlas-canvas"), {
  ssr: false,
  loading: () => <CanvasLoading />,
});

type Load =
  | { kind: "loading" }
  | { kind: "ready"; data: AtlasPayload; index: AtlasIndex }
  | { kind: "error"; code: string };

function CanvasLoading() {
  return (
    <div className="flex size-full items-center justify-center gap-2 text-sm text-muted-foreground" role="status">
      <Spinner className="size-4" /> Drawing the map…
    </div>
  );
}

export function AtlasView() {
  const params = useSearchParams();
  const focusParam = params.get("focus");
  const tourParam = params.get("tour") === "1";
  const { role, labelStyle } = useLens();
  const theme = useGraphTheme();
  const reducedMotion = useReducedMotion();
  const canvas = useRef<AtlasCanvasHandle>(null);

  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [view, setView] = useState<ViewMode>("graph");
  const [colorByChoice, setColorBy] = useState<ColorBy | null>(null);
  const colorBy: ColorBy = colorByChoice ?? (role === "researcher" ? "cluster" : "type");
  const [hiddenTypes, setHiddenTypes] = useState<Set<NodeType>>(new Set());
  const [hiddenFamilies, setHiddenFamilies] = useState<Set<EdgeFamily>>(new Set());
  const [selected, setSelected] = useState<string | null>(focusParam);
  const [canvasFailed, setCanvasFailed] = useState(false);
  const [tourOpen, setTourOpen] = useState(tourParam);

  useEffect(() => {
    let alive = true;
    getAtlas({ meta: { quiet: true } })
      .then(({ data, error }) => {
        if (!alive) return;
        if (error || !data) {
          setLoad({ kind: "error", code: (error as unknown as ApiError | undefined)?.code ?? "unknown" });
          return;
        }
        const index = buildAtlasIndex(data);
        setLoad({ kind: "ready", data, index });
        announce(`Atlas loaded: ${index.nodes.size} items and ${index.edges.size} connections.`);
      })
      .catch((e: ApiError) => alive && setLoad({ kind: "error", code: e?.code ?? "unknown" }));
    return () => {
      alive = false;
    };
  }, [attempt]);

  const index = load.kind === "ready" ? load.index : null;

  // `?focus=<id>`: select it (also when the URL changes later) and centre the camera.
  const [prevFocus, setPrevFocus] = useState(focusParam);
  if (focusParam !== prevFocus) {
    setPrevFocus(focusParam);
    if (focusParam) setSelected(focusParam);
  }
  const missingFocus = index && selected && !index.nodes.has(selected) ? selected : null;
  useEffect(() => {
    if (!index || !focusParam || !index.nodes.has(focusParam)) return;
    const id = requestAnimationFrame(() => canvas.current?.focusNode(focusParam));
    return () => cancelAnimationFrame(id);
  }, [index, focusParam]);

  const select = useCallback(
    (id: string | null, { center = false } = {}) => {
      setSelected(id);
      const url = new URL(window.location.href);
      if (id) url.searchParams.set("focus", id);
      else url.searchParams.delete("focus");
      url.searchParams.delete("tour");
      window.history.replaceState(null, "", url.pathname + url.search);
      if (id && index) {
        const n = index.nodes.get(id);
        const deg = index.incident.get(id)?.length ?? 0;
        if (n) announce(`Selected ${n.label}, ${nodeTypeMeta(n.type).label[labelStyle]}, ${deg} connections.`);
        if (center) canvas.current?.focusNode(id);
      } else if (!id) {
        announce("Selection cleared.");
      }
    },
    [index, labelStyle],
  );

  const visibleTypes = useMemo(
    () => new Set(NODE_TYPES.filter((t) => !hiddenTypes.has(t))),
    [hiddenTypes],
  );
  const visibleFamilies = useMemo(
    () => new Set(EDGE_FAMILIES.filter((f) => !hiddenFamilies.has(f))),
    [hiddenFamilies],
  );
  const toggle = <T,>(set: Set<T>, v: T) => {
    const next = new Set(set);
    if (next.has(v)) next.delete(v);
    else next.add(v);
    return next;
  };
  const filtersActive = hiddenTypes.size + hiddenFamilies.size;

  const header = (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b bg-background/80 px-4 py-2.5 backdrop-blur sm:px-6">
      <div className="mr-auto min-w-0">
        <h1 className="text-base font-semibold tracking-tight">Atlas</h1>
        <p className="text-xs text-muted-foreground" id="atlas-desc">
          {index ? (
            <span data-testid="atlas-counts">
              {index.nodes.size.toLocaleString("en")} items · {index.edges.size.toLocaleString("en")} connections
              {index.clusters.size > 0 && <> · {index.clusters.size} groups</>}
            </span>
          ) : (
            "The whole map, grouped by shared mechanism and symptoms."
          )}
        </p>
      </div>
      {index && (
        <div className="flex flex-wrap items-center gap-2">
          <ViewToggle value={view} onChange={setView} />
          <AtlasFind index={index} onPick={(id) => select(id, { center: true })} />
          <Popover>
            <PopoverTrigger
              render={<Button variant="outline" size="sm" data-testid="atlas-filters" data-tour="filters" />}
            >
              <SlidersHorizontal data-icon="inline-start" aria-hidden />
              Filters
              {filtersActive > 0 && (
                <span className="rounded-full bg-primary px-1.5 text-[10px] text-primary-foreground">{filtersActive}</span>
              )}
            </PopoverTrigger>
            <PopoverContent align="end" className="w-[22rem] max-w-[calc(100vw-2rem)] gap-4 p-4">
              <fieldset>
                <legend className="mb-2 text-xs font-medium text-muted-foreground">Colour by</legend>
                <div className="flex gap-1.5" role="radiogroup" aria-label="Colour by">
                  {(["type", "cluster"] as const).map((c) => (
                    <button
                      key={c}
                      type="button"
                      role="radio"
                      aria-checked={colorBy === c}
                      onClick={() => setColorBy(c)}
                      className={cn(
                        "h-7 rounded-md border px-2.5 text-xs font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        colorBy === c ? "border-primary bg-primary/10" : "text-muted-foreground hover:text-foreground",
                      )}
                    >
                      {c === "type" ? "Kind of item" : "Group"}
                    </button>
                  ))}
                </div>
              </fieldset>
              <fieldset>
                <legend className="mb-2 text-xs font-medium text-muted-foreground">Connections</legend>
                <FamilyChips
                  families={index.presentFamilies}
                  counts={Object.fromEntries(index.familyCounts)}
                  active={visibleFamilies}
                  onToggle={(f) => setHiddenFamilies((s) => toggle(s, f))}
                />
              </fieldset>
              <fieldset>
                <legend className="mb-2 text-xs font-medium text-muted-foreground">Items</legend>
                <ul className="grid grid-cols-2 gap-x-3 gap-y-1.5">
                  {index.presentTypes.map((t) => {
                    const meta = nodeTypeMeta(t);
                    const Icon = meta.icon;
                    const id = `atlas-type-${t}`;
                    return (
                      <li key={t} className="flex items-center gap-2">
                        <Checkbox
                          id={id}
                          checked={visibleTypes.has(t)}
                          onCheckedChange={() => setHiddenTypes((s) => toggle(s, t))}
                        />
                        <label htmlFor={id} className="flex min-w-0 flex-1 items-center gap-1.5 text-xs">
                          <Icon className="size-3.5 shrink-0" style={{ color: `var(${meta.colorVar})` }} aria-hidden />
                          <span className="truncate">{meta.plural[labelStyle]}</span>
                          <span className="ml-auto font-mono text-[10.5px] tabular text-muted-foreground">
                            {index.typeCounts.get(t)}
                          </span>
                        </label>
                      </li>
                    );
                  })}
                </ul>
              </fieldset>
              {filtersActive > 0 && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="self-start"
                  onClick={() => {
                    setHiddenTypes(new Set());
                    setHiddenFamilies(new Set());
                  }}
                >
                  Show everything
                </Button>
              )}
            </PopoverContent>
          </Popover>
          <Button
            variant={role === "guest" ? "secondary" : "ghost"}
            size="sm"
            onClick={() => setTourOpen(true)}
            data-testid="tour-start"
          >
            <Compass data-icon="inline-start" aria-hidden />
            Tour
          </Button>
        </div>
      )}
    </div>
  );

  let body: React.ReactNode;
  if (load.kind === "loading" || !theme) {
    body = (
      <div className="bg-atlas-grid flex flex-1 items-center justify-center" role="status" data-testid="atlas-loading">
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
          <Button onClick={() => { setLoad({ kind: "loading" }); setAttempt((a) => a + 1); }}>
            <RotateCcw data-icon="inline-start" aria-hidden /> Try again
          </Button>
        }
      />
    );
  } else if (load.index.nodes.size === 0) {
    body = (
      <StateMessage
        testId="atlas-empty"
        icon={Boxes}
        title="The atlas is empty for now"
        description="No diseases, genes or other items have been loaded yet. Once the data pipeline has run, the map appears here."
        action={<Link href="/" className={buttonVariants({ variant: "outline" })}>Back to the start</Link>}
      />
    );
  } else {
    const idx = load.index;
    body = (
      <div className="relative flex min-h-0 flex-1">
        {view === "graph" && !canvasFailed ? (
          <div className={cn("bg-atlas-grid relative min-w-0 flex-1", TOUR_SPOT, "data-[tour-active]:ring-inset data-[tour-active]:ring-offset-0")} data-tour="canvas">
            <p id="atlas-canvas-label" className="sr-only">
              Map of {idx.nodes.size} items and {idx.edges.size} connections. Arrow keys pan, plus and minus zoom.
              The list view shows the same items in a table.
            </p>
            <AtlasCanvas
              ref={canvas}
              index={idx}
              theme={theme}
              colorBy={colorBy}
              visibleTypes={visibleTypes}
              visibleFamilies={visibleFamilies}
              selectedId={selected}
              onSelect={(id) => select(id)}
              onError={() => setCanvasFailed(true)}
              reducedMotion={reducedMotion}
              labelledBy="atlas-canvas-label"
            />
            <div className="absolute top-3 left-3 flex flex-col overflow-hidden rounded-lg border bg-card/90 shadow-xs backdrop-blur">
              <Button variant="ghost" size="icon-sm" className="rounded-none" aria-label="Zoom in" onClick={() => canvas.current?.zoomIn()}>
                <Plus aria-hidden />
              </Button>
              <Button variant="ghost" size="icon-sm" className="rounded-none border-y" aria-label="Zoom out" onClick={() => canvas.current?.zoomOut()}>
                <Minus aria-hidden />
              </Button>
              <Button variant="ghost" size="icon-sm" className="rounded-none" aria-label="Show the whole map" onClick={() => canvas.current?.reset()}>
                <RotateCcw aria-hidden />
              </Button>
            </div>
            <div className="pointer-events-none absolute bottom-3 left-3 hidden max-h-[calc(100%-7rem)] flex-col gap-2 sm:flex">
              <AtlasKey index={idx} colorBy={colorBy} dark={theme.dark} />
            </div>
          </div>
        ) : (
          <div className="min-w-0 flex-1">
            {canvasFailed && view === "graph" && (
              <p className="border-b bg-status-flag/10 px-4 py-2 text-sm" role="status">
                The map can&apos;t be drawn on this device, so the list is shown instead.
              </p>
            )}
            <AtlasList index={idx} visibleTypes={visibleTypes} selectedId={selected} onSelect={(id) => select(id)} />
          </div>
        )}

        {missingFocus && (
          <div className="absolute top-3 left-1/2 z-10 w-[min(28rem,calc(100%-2rem))] -translate-x-1/2 rounded-lg border bg-card px-3 py-2 text-sm shadow-md" role="status" data-testid="atlas-missing-focus">
            <span className="font-mono text-xs">{missingFocus}</span> is not on the map.{" "}
            <Link className="underline underline-offset-2" href={`/node/${encodeURIComponent(missingFocus)}`}>Open it directly</Link>
          </div>
        )}

        {selected && idx.nodes.has(selected) && (
          <AtlasPanel
            key={selected}
            index={idx}
            nodeId={selected}
            onSelect={(id) => select(id, { center: true })}
            onClose={() => select(null)}
            className="absolute inset-x-3 bottom-3 z-20 max-h-[58%] sm:inset-x-auto sm:top-3 sm:right-3 sm:bottom-3 sm:max-h-none sm:w-[22rem]"
          />
        )}
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100dvh-3.5rem)] min-h-[520px] flex-col" data-testid="atlas-view">
      {header}
      {body}
      {index && (
        <AtlasTour
          open={tourOpen}
          onOpenChange={(o) => {
            setTourOpen(o);
            if (!o && tourParam) {
              const url = new URL(window.location.href);
              url.searchParams.delete("tour");
              window.history.replaceState(null, "", url.pathname + url.search);
            }
          }}
          onBeforeStep={(target) => {
            if (target === "canvas" || target === "legend") setView("graph");
          }}
        />
      )}
    </div>
  );
}

function AtlasKey({ index, colorBy, dark }: { index: AtlasIndex; colorBy: ColorBy; dark: boolean }) {
  const { labelStyle } = useLens();
  const [open, setOpen] = useState(true);
  return (
    <div
      className={cn("pointer-events-auto flex min-h-0 w-60 flex-col overflow-hidden rounded-lg border bg-card/90 backdrop-blur", TOUR_SPOT)}
      data-tour="legend"
    >
      <button
        type="button"
        aria-expanded={open}
        aria-controls="atlas-key"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center justify-between px-3 py-2 text-xs font-medium outline-none hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
      >
        Key
        <ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      {open && (
        <div id="atlas-key" className="min-h-0 space-y-3 overflow-y-auto border-t px-0 pb-1">
          <GraphLegend families={index.presentFamilies} className="rounded-none border-0 bg-transparent backdrop-blur-none" />
          {colorBy === "type" ? (
            <section className="px-3 pb-2">
              <h4 className="mb-1.5 font-mono text-[10px] tracking-[0.14em] text-muted-foreground uppercase">Dots</h4>
              <ul className="grid grid-cols-2 gap-x-2 gap-y-1 text-[11px]">
                {index.presentTypes.map((t) => {
                  const meta = nodeTypeMeta(t);
                  const Icon = meta.icon;
                  return (
                    <li key={t} className="flex min-w-0 items-center gap-1.5">
                      <Icon className="size-3 shrink-0" style={{ color: `var(${meta.colorVar})` }} aria-hidden />
                      <span className="truncate">{meta.plural[labelStyle]}</span>
                    </li>
                  );
                })}
              </ul>
            </section>
          ) : (
            <ClusterKey index={index} dark={dark} />
          )}
        </div>
      )}
    </div>
  );
}

function ClusterKey({ index, dark }: { index: AtlasIndex; dark: boolean }) {
  const list = [...index.clusters.values()].filter((c) => c.members > 0).slice(0, 12);
  return (
    <div className="px-3 pb-2">
      <h4 className="mb-1.5 font-mono text-[10px] tracking-[0.14em] text-muted-foreground uppercase">Groups · hypothesis</h4>
      <ul className="space-y-1 text-xs">
        {list.map((c) => (
          <li key={c.id}>
            <Link href={`/node/${encodeURIComponent(c.id)}`} className="flex items-center gap-2 hover:underline">
              <span className="size-2.5 shrink-0 rounded-full" style={{ background: clusterColor(c.order, dark) }} aria-hidden />
              <span className="truncate">{c.label}</span>
            </Link>
          </li>
        ))}
      </ul>
      {index.clusters.size > list.length && (
        <Link href="/clusters" className="mt-2 block text-xs text-muted-foreground underline underline-offset-2">
          All {index.clusters.size} groups
        </Link>
      )}
    </div>
  );
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
    <div className="bg-atlas-grid flex flex-1 items-center justify-center p-6" data-testid={testId}>
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
