"use client";

import { memo, useEffect, useId, useMemo, useRef, useState } from "react";

import { CATEGORY_META } from "@/components/atlas/atlas-categories";
import { NODE_TYPE_META } from "@/lib/graph/meta";
import { cn } from "@/lib/utils";

import {
  fitViewBox,
  focusBounds,
  type AtlasPreviewModel,
  type Bounds,
  type PreviewCategory,
  type PreviewLink,
  type PreviewPoint,
} from "./atlas-preview-model";
import { HERO_CYCLE_MS } from "./landing-config";

/*
 * Motion is CSS only, on the few paths of the current node: the links are revealed by a
 * mask whose solid copies draw in (stroke-dashoffset), so dashed links stay dashed; the
 * whole highlight fades in and out on one timeline (lp-cycle) whose end advances the
 * cycle. Pausing sets animation-play-state, so nothing runs while paused.
 */
const ANIMATION = `
@media (prefers-reduced-motion: no-preference) {
  .lp-in { animation: lp-in 700ms ease-out both; }
  .lp-pop { animation: lp-pop 500ms ease-out both; }
}
.lp-cycle { animation: lp-cycle ${HERO_CYCLE_MS}ms linear both; }
.lp-draw { stroke-dasharray: 1 1; stroke-dashoffset: 1; animation: lp-draw 650ms ease-out forwards; }
.lp-paused, .lp-paused * { animation-play-state: paused !important; }
@keyframes lp-in { from { opacity: 0; } to { opacity: 1; } }
@keyframes lp-pop { from { opacity: 0; transform: scale(.6); } to { opacity: 1; transform: scale(1); } }
@keyframes lp-draw { to { stroke-dashoffset: 0; } }
@keyframes lp-cycle {
  0% { opacity: 0; }
  4% { opacity: 1; }
  88.5% { opacity: 1; }
  100% { opacity: 0; }
}
`;

/** Curved link from the focus to an endpoint, bent toward the hub like the Atlas draws them. */
function curve(fx: number, fy: number, ox: number, oy: number): string {
  const mx = (fx + ox) / 2;
  const my = (fy + oy) / 2;
  return `M${fx} ${fy}Q${Math.round(mx * 0.6)} ${Math.round(my * 0.6)} ${ox} ${oy}`;
}

function pct(v: number, min: number, size: number) {
  return `${(((v - min) / size) * 100).toFixed(3)}%`;
}

/** Up to `max` endpoint labels, strongest first, skipping ones that would sit on top of another. */
function pickLabels(links: PreviewLink[], vb: Bounds, max: number, focus?: { x: number; y: number }): PreviewLink[] {
  const w = vb.maxX - vb.minX;
  const h = vb.maxY - vb.minY;
  const placed: PreviewLink[] = [];
  const seen = new Set<string>();
  for (const l of links) {
    if (placed.length >= max) break;
    if (seen.has(l.other.id)) continue;
    seen.add(l.other.id);
    const inside = l.other.x > vb.minX + w * 0.08 && l.other.x < vb.maxX - w * 0.08 && l.other.y > vb.minY + h * 0.08 && l.other.y < vb.maxY - h * 0.04;
    if (!inside) continue;
    if (focus && Math.abs(focus.x - l.other.x) / w < 0.25 && Math.abs(focus.y - l.other.y) / h < 0.08) continue;
    const near = placed.some(
      (p) => Math.abs(p.other.x - l.other.x) / w < 0.22 && Math.abs(p.other.y - l.other.y) / h < 0.07,
    );
    if (!near) placed.push(l);
  }
  return placed;
}

function shortLabel(label: string) {
  const s = label.split(" · ")[0];
  return s.length > 30 ? `${s.slice(0, 29)}…` : s;
}

function focusColor(p: PreviewPoint) {
  return p.category ? `var(${CATEGORY_META[p.category].colorVar})` : "var(--primary)";
}

/** The nine trees: 27 paths, re-rendered only when the model, dimming or scale changes. */
const BaseLayer = memo(function BaseLayer({ categories, opacity, k }: { categories: PreviewCategory[]; opacity: number; k: number }) {
  return (
    <g fill="none" strokeLinecap="round" opacity={opacity}>
      {categories.map((c) => (
        <g key={c.id} style={{ color: `var(${c.colorVar})` }} data-category={c.id}>
          <path d={c.links} stroke="currentColor" strokeOpacity={0.5} strokeWidth={0.7 * Math.max(k, 0.7)} vectorEffect="non-scaling-stroke" />
          <path d={c.groups} stroke="currentColor" strokeWidth={4.5 * k} vectorEffect="non-scaling-stroke" />
          <path d={c.dots} stroke="currentColor" strokeWidth={2.2 * k} vectorEffect="non-scaling-stroke" />
        </g>
      ))}
    </g>
  );
});

export type PreviewCycle = {
  /** Restarts the animations when it changes (the position in the cycle). */
  step: number;
  paused: boolean;
  /** Called when the current node's timeline ends. */
  onDone: () => void;
};

/**
 * The live Atlas drawn as SVG from the tree payload: nine coloured trees
 * around the logo, labels at the outer edge, and the focus node's real links
 * (solid = cited, dashed = computed). `zoom="focus"` frames the focus node
 * and its endpoints instead of the whole map. With `cycle`, the focus node's
 * links draw in, hold and fade on one CSS timeline, and a small label names
 * the node. Colours come only from the theme tokens. Pass `label` to expose
 * the drawing as an image; without it the drawing is decorative (aria-hidden).
 */
export function AtlasPreview({
  model,
  focusId,
  zoom = "whole",
  endpointLabels = 0,
  maxLinks,
  cycle,
  showFocusLabel = false,
  label,
  className,
}: {
  model: AtlasPreviewModel;
  focusId?: string | null;
  zoom?: "whole" | "focus";
  /** How many endpoint labels to show (focus zoom). */
  endpointLabels?: number;
  /** Draw only the strongest links of the focus node. */
  maxLinks?: number;
  /** Animate the focus node's links (hero cycle); omit for a static drawing. */
  cycle?: PreviewCycle;
  /** Name the focus node (with its kind) next to it, in the whole-map view too. */
  showFocusLabel?: boolean;
  /** Accessible description; makes the SVG `role="img"`. */
  label?: string;
  className?: string;
}) {
  const frame = useRef<HTMLDivElement>(null);
  const maskId = useId();
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const aspect = size ? size.w / size.h : null;

  useEffect(() => {
    const el = frame.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0) setSize({ w: width, h: height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const focus = focusId ? model.points.get(focusId) : undefined;
  const links = useMemo(() => {
    const all = focus ? model.linksOf(focus.id) : [];
    return maxLinks ? all.slice(0, maxLinks) : all;
  }, [model, focus, maxLinks]);

  // Dots and lines are in screen pixels; a small frame gets thinner ones so the trees stay legible.
  const narrow = (size?.w ?? 1000) < 640;
  const k = Math.max(0.45, Math.min(1, (size?.w ?? 1000) / 960));

  const vb = useMemo(() => {
    const a = aspect ?? 16 / 10;
    if (zoom === "focus" && focus) {
      const box = focusBounds(model, focus.id);
      if (box) return fitViewBox(box, a, 0.12);
    }
    return fitViewBox(model.bounds, a, narrow ? 0.1 : 0.05);
  }, [aspect, zoom, focus, model, narrow]);

  const w = vb.maxX - vb.minX;
  const h = vb.maxY - vb.minY;
  // Mask strokes are in user units (no non-scaling-stroke, so the dash offset is a fraction of the path).
  const maskWidth = size ? (10 * w) / size.w : 40;
  const dim = zoom === "focus" && !!focus;
  const labelled = zoom === "focus" ? pickLabels(links, vb, endpointLabels, focus) : [];
  const root = model.points.get("T:root") ?? { x: 0, y: 0 };
  const rootInView = root.x >= vb.minX && root.x <= vb.maxX && root.y >= vb.minY && root.y <= vb.maxY;
  const timeline = cycle ? cn("lp-cycle", cycle.paused && "lp-paused") : undefined;
  const typeLabel = focus?.type ? (NODE_TYPE_META[focus.type as keyof typeof NODE_TYPE_META]?.label.plain ?? null) : null;

  return (
    <div ref={frame} className={cn("relative size-full overflow-hidden", className)}>
      {aspect !== null && (
        <>
          <svg
            viewBox={`${vb.minX.toFixed(1)} ${vb.minY.toFixed(1)} ${w.toFixed(1)} ${h.toFixed(1)}`}
            preserveAspectRatio="xMidYMid meet"
            className="absolute inset-0 size-full"
            {...(label ? { role: "img", "aria-label": label } : { "aria-hidden": true })}
            data-testid="atlas-preview-svg"
          >
            <style>{ANIMATION}</style>
            {/* The cycle dims the trees once (not per node), so the drawn links stand out. */}
            <BaseLayer categories={model.categories} opacity={dim ? 0.35 : cycle ? 0.55 : 1} k={k} />
            {focus && (
              <g
                key={`${focus.id}-${cycle?.step ?? 0}`}
                fill="none"
                strokeLinecap="round"
                className={timeline}
                data-testid="atlas-preview-highlight"
                data-focus={focus.id}
                onAnimationEnd={
                  cycle
                    ? (e) => {
                        if (e.target === e.currentTarget && e.animationName === "lp-cycle") cycle.onDone();
                      }
                    : undefined
                }
              >
                {cycle && (
                  <mask id={maskId} maskUnits="userSpaceOnUse" x={vb.minX} y={vb.minY} width={w} height={h}>
                    {links.map(({ edge, other }, i) => (
                      <path
                        key={edge.id}
                        className="lp-draw"
                        style={{ animationDelay: `${Math.round((i / Math.max(links.length, 1)) * 350)}ms` }}
                        d={curve(focus.x, focus.y, other.x, other.y)}
                        pathLength={1}
                        stroke="white"
                        strokeWidth={maskWidth}
                      />
                    ))}
                  </mask>
                )}
                <g mask={cycle ? `url(#${CSS.escape(maskId)})` : undefined}>
                  {links.map(({ edge, other }, i) => (
                    <path
                      key={edge.id}
                      className={cycle ? undefined : "lp-in"}
                      style={cycle ? undefined : { animationDelay: `${Math.min(i, 60) * 18}ms` }}
                      d={curve(focus.x, focus.y, other.x, other.y)}
                      stroke={`var(--edge-${edge.family})`}
                      strokeOpacity={edge.origin === "inferred" ? 0.95 : cycle ? 0.8 : 0.55}
                      strokeWidth={(edge.origin === "inferred" ? 1.4 : cycle ? 1.2 : 0.9) * Math.max(k, 0.7)}
                      strokeDasharray={edge.origin === "inferred" ? "4 3" : undefined}
                      vectorEffect="non-scaling-stroke"
                      data-origin={edge.origin}
                    />
                  ))}
                </g>
                {dim &&
                  links.map(({ edge, other }) => (
                    <path
                      key={`d${edge.id}`}
                      d={`M${other.x} ${other.y}h0`}
                      stroke="var(--foreground)"
                      strokeOpacity={0.7}
                      strokeWidth={3}
                      vectorEffect="non-scaling-stroke"
                    />
                  ))}
                <path d={`M${focus.x} ${focus.y}h0`} stroke="var(--background)" strokeWidth={16} vectorEffect="non-scaling-stroke" />
                <path
                  d={`M${focus.x} ${focus.y}h0`}
                  stroke={focusColor(focus)}
                  strokeWidth={11}
                  vectorEffect="non-scaling-stroke"
                  data-testid="atlas-preview-focus"
                />
              </g>
            )}
          </svg>

          <div aria-hidden className="pointer-events-none absolute inset-0 select-none">
            {zoom === "whole" &&
              model.labels.map((l) => (
                <span
                  key={l.id}
                  className="absolute text-[9px] font-medium whitespace-nowrap sm:text-xs"
                  style={{
                    left: pct(l.x, vb.minX, w),
                    top: pct(l.y, vb.minY, h),
                    color: `var(${l.colorVar})`,
                    transform: `translate(-50%, -50%) rotate(${l.rotate}deg)`,
                  }}
                >
                  {l.text}
                </span>
              ))}
            {labelled.map(({ other }) => (
              <span
                key={other.id}
                className="absolute max-w-[40%] truncate rounded-md border bg-card/90 px-1.5 py-0.5 text-[11px] leading-tight text-foreground shadow-xs"
                style={{ left: pct(other.x, vb.minX, w), top: pct(other.y, vb.minY, h), transform: "translate(-50%, -130%)" }}
              >
                {shortLabel(other.label)}
              </span>
            ))}
            {focus && (zoom === "focus" || showFocusLabel) && (
              <span
                key={`${focus.id}-${cycle?.step ?? 0}`}
                className={cn(
                  "absolute flex max-w-[45%] items-center gap-1.5 truncate rounded-md bg-foreground px-2 py-0.5 text-xs font-semibold text-background shadow-sm",
                  timeline,
                )}
                style={{ left: pct(focus.x, vb.minX, w), top: pct(focus.y, vb.minY, h), transform: "translate(-50%, 45%)" }}
                data-testid="atlas-preview-label"
              >
                {showFocusLabel && typeLabel && <span className="font-normal opacity-70">{typeLabel}</span>}
                <span className="truncate">{shortLabel(focus.label)}</span>
              </span>
            )}
            {rootInView && (
              <span
                className="lp-pop absolute flex size-7 items-center justify-center rounded-full border-2 border-primary/70 bg-card shadow-sm sm:size-10"
                style={{ left: pct(root.x, vb.minX, w), top: pct(root.y, vb.minY, h), translate: "-50% -50%" }}
              >
                {/* eslint-disable-next-line @next/next/no-img-element -- 128 px static logo, no optimisation needed */}
                <img src="/amber-logo-128.png" alt="" width={28} height={28} className="size-4 sm:size-6" />
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
}
