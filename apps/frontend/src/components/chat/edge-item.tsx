"use client";

import { ArrowRight, ChevronDown } from "lucide-react";
import { useState } from "react";

import { EdgeTrustRow, EvidenceList, NodeChip, VusNotice } from "@/components/graph-ui";
import { Skeleton } from "@/components/ui/skeleton";
import { isVus } from "@/lib/graph/types";
import { cn } from "@/lib/utils";

import type { EdgeEvidence } from "./types";

type Node = EdgeEvidence["source"];

export function nodeIsVus(node: Node | undefined | null): boolean {
  return isVus((node?.attrs?.classification as string | undefined) ?? null);
}

/**
 * One cited link: source → target, its trust row (relation, confidence,
 * origin, status) and, on click, every supporting and contradicting source.
 */
export function EdgeItem({
  id,
  data,
  defaultOpen = false,
  tone = "default",
}: {
  id: string;
  /** `undefined` while loading, `null` if unavailable. */
  data: EdgeEvidence | null | undefined;
  defaultOpen?: boolean;
  tone?: "default" | "contradiction";
}) {
  const [open, setOpen] = useState(defaultOpen);
  if (data === undefined) {
    return (
      <div className="space-y-2 rounded-lg border bg-card p-3" aria-busy="true">
        <Skeleton className="h-5 w-2/3" />
        <Skeleton className="h-4 w-1/2" />
      </div>
    );
  }
  if (data === null) {
    return (
      <p className="rounded-lg border border-dashed bg-card/60 px-3 py-2 text-xs text-muted-foreground">
        The sources for link <span className="font-mono">{id}</span> could not be loaded right now.
      </p>
    );
  }
  const evidence = [...data.supporting, ...data.contradicting];
  const vus = nodeIsVus(data.source) || nodeIsVus(data.target);
  return (
    <div
      className={cn(
        "rounded-lg border bg-card p-3",
        tone === "contradiction" && "border-confidence-low/40",
      )}
      data-testid="edge-item"
      data-edge-id={id}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <NodeChip id={data.source.id} type={data.source.type} label={data.source.label} size="sm" />
        <ArrowRight className="size-3.5 text-muted-foreground" aria-label="to" />
        <NodeChip id={data.target.id} type={data.target.type} label={data.target.label} size="sm" />
      </div>
      <EdgeTrustRow className="mt-2" edge={{ ...data.edge, evidence }} />
      {vus && <VusNotice compact className="mt-2" />}
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="mt-2 inline-flex items-center gap-1 rounded text-xs font-medium text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ChevronDown className={cn("size-3.5 transition-transform motion-reduce:transition-none", open && "rotate-180")} aria-hidden />
        {open ? "Hide sources" : `Show ${evidence.length} source${evidence.length === 1 ? "" : "s"}`}
        {data.contradicting.length > 0 && (
          <span className="text-confidence-low">· {data.contradicting.length} contradicting</span>
        )}
      </button>
      {open && <EvidenceList className="mt-2" evidence={evidence} />}
    </div>
  );
}
