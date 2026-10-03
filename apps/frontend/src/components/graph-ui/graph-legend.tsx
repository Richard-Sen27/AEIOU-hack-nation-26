"use client";

import { useLens } from "@/components/providers/lens-provider";
import { EDGE_FAMILY_META, NODE_TYPE_META, ORIGIN_META } from "@/lib/graph/meta";
import { svgDashArray } from "@/lib/graph/style";
import { EDGE_FAMILIES, ORIGINS, type EdgeFamily, type NodeType } from "@/lib/graph/types";
import { cn } from "@/lib/utils";

function LineSample({ color, dash }: { color: string; dash?: string }) {
  return (
    <svg width="28" height="8" viewBox="0 0 28 8" aria-hidden className="shrink-0">
      <line x1="1" y1="4" x2="27" y2="4" stroke={color} strokeWidth="2" strokeDasharray={dash} strokeLinecap="round" />
    </svg>
  );
}

/**
 * Legend for line styles (origin), edge colours (family) and optionally the
 * node types present in a view. Colour is always paired with text and icons.
 */
export function GraphLegend({
  nodeTypes,
  families = [...EDGE_FAMILIES],
  className,
  orientation = "vertical",
}: {
  /** Node types to list; omit to hide the node section. */
  nodeTypes?: NodeType[];
  families?: EdgeFamily[];
  className?: string;
  orientation?: "vertical" | "horizontal";
}) {
  const { labelStyle } = useLens();
  const horizontal = orientation === "horizontal";
  const list = cn("text-xs", horizontal ? "flex flex-wrap gap-x-4 gap-y-1.5" : "space-y-1.5");
  return (
    <div
      className={cn("space-y-3 rounded-lg border bg-card/90 p-3 backdrop-blur", horizontal && "flex flex-wrap gap-6 space-y-0", className)}
      data-testid="graph-legend"
    >
      <section>
        <h4 className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Line style</h4>
        <ul className={list}>
          {ORIGINS.map((o) => (
            <li key={o} className="flex items-center gap-2">
              <LineSample color="currentColor" dash={svgDashArray(ORIGIN_META[o].line)} />
              <span>
                {ORIGIN_META[o].label.plain}
                <span className="sr-only">: {ORIGIN_META[o].line} line. {ORIGIN_META[o].description}</span>
              </span>
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h4 className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Connection</h4>
        <ul className={list}>
          {families.map((f) => (
            <li key={f} className="flex items-center gap-2" title={EDGE_FAMILY_META[f].description[labelStyle]}>
              <LineSample color={`var(${EDGE_FAMILY_META[f].colorVar})`} />
              <span>{EDGE_FAMILY_META[f].label[labelStyle]}</span>
            </li>
          ))}
        </ul>
      </section>
      {nodeTypes && nodeTypes.length > 0 && (
        <section>
          <h4 className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Nodes</h4>
          <ul className={list}>
            {nodeTypes.map((t) => {
              const meta = NODE_TYPE_META[t];
              const Icon = meta.icon;
              return (
                <li key={t} className="flex items-center gap-2">
                  <Icon className="size-3.5 shrink-0" style={{ color: `var(${meta.colorVar})` }} aria-hidden />
                  <span>{meta.plural[labelStyle]}</span>
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </div>
  );
}
