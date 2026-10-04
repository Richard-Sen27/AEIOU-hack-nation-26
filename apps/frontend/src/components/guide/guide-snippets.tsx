/**
 * Small illustrations for the guide, built from the app's own components and
 * tokens (like the landing page's mocks). Decorative: the steps say the same.
 */
import { Check } from "lucide-react";

import { ATLAS_CATEGORIES, CATEGORY_META } from "@/components/atlas/atlas-categories";
import { OffMapMark } from "@/components/atlas/atlas-offmap";
import { ConfidenceBadge, OriginBadge } from "@/components/graph-ui";
import { NODE_TYPE_META } from "@/lib/graph/meta";
import { cn } from "@/lib/utils";

import type { SnippetKey } from "./guide-content";

function Categories() {
  return (
    <ul className="flex flex-wrap gap-1.5" aria-label="The nine trees">
      {ATLAS_CATEGORIES.map((c) => {
        const meta = CATEGORY_META[c];
        const Icon = NODE_TYPE_META[meta.colorType].icon;
        return (
          <li
            key={c}
            className="inline-flex h-6 items-center gap-1 rounded-full border bg-background px-2 text-[11px] font-medium"
          >
            <Icon className="size-3" style={{ color: `var(${meta.colorVar})` }} aria-hidden />
            {meta.label.plain}
          </li>
        );
      })}
    </ul>
  );
}

function Line({ dashed }: { dashed?: boolean }) {
  return (
    <svg width="28" height="8" viewBox="0 0 28 8" aria-hidden className="shrink-0 text-foreground/70">
      <line x1="1" y1="4" x2="27" y2="4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeDasharray={dashed ? "5 4" : undefined} />
    </svg>
  );
}

function Links() {
  return (
    <div className="space-y-2" aria-hidden>
      <p className="flex flex-wrap items-center gap-2">
        <Line /> <OriginBadge origin="observed" /> <ConfidenceBadge confidence={0.92} />
      </p>
      <p className="flex flex-wrap items-center gap-2">
        <Line dashed /> <OriginBadge origin="inferred" /> <ConfidenceBadge confidence={0.62} />
      </p>
    </div>
  );
}

function Symptoms() {
  const rows: Array<[string, number]> = [
    ["Condition A", 3],
    ["Condition B", 2],
  ];
  return (
    <div className="space-y-1.5" aria-hidden>
      {rows.map(([label, n]) => (
        <p key={label} className="flex items-center justify-between gap-3 text-xs">
          <span className="font-medium">{label}</span>
          <span className="flex items-center gap-1.5 text-muted-foreground">
            <span className="inline-flex gap-[3px]">
              {[0, 1, 2, 3].map((i) => (
                <span key={i} className={cn("size-1.5 rounded-full", i < n ? "bg-primary" : "bg-muted-foreground/25")} />
              ))}
            </span>
            {n} of 4 symptoms
          </span>
        </p>
      ))}
      <p className="text-[11px] text-muted-foreground italic">Symptom overlap in the atlas data, not a diagnosis.</p>
    </div>
  );
}

function Share() {
  const items: Array<[string, boolean]> = [
    ["Diagnosis", true],
    ["Symptoms", true],
    ["Country", false],
  ];
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1.5" aria-hidden>
      {items.map(([label, on]) => (
        <li key={label} className="flex items-center gap-1.5 text-xs">
          <span
            className={cn(
              "flex size-3.5 items-center justify-center rounded-[4px] border",
              on ? "border-primary bg-primary text-primary-foreground" : "border-input bg-background",
            )}
          >
            {on && <Check className="size-2.5" strokeWidth={3} />}
          </span>
          <span className={cn(!on && "text-muted-foreground")}>{label}</span>
        </li>
      ))}
    </ul>
  );
}

export function GuideSnippet({ name }: { name: SnippetKey }) {
  switch (name) {
    case "categories":
      return <Categories />;
    case "links":
      return <Links />;
    case "hypothesis":
      return (
        <p className="flex items-center gap-2" aria-hidden>
          <OriginBadge origin="inferred" />
          <span className="text-xs text-muted-foreground">grouped by the atlas</span>
        </p>
      );
    case "offmap":
      return <OffMapMark />;
    case "symptoms":
      return <Symptoms />;
    case "share":
      return <Share />;
  }
}
