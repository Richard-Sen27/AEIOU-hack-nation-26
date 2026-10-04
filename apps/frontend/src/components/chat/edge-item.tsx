"use client";

import { Lightbulb } from "lucide-react";
import Link from "next/link";

import { VusNotice } from "@/components/graph-ui";
import { Skeleton } from "@/components/ui/skeleton";
import { relationLabel } from "@/lib/graph/meta";
import { isVus } from "@/lib/graph/types";
import { cn } from "@/lib/utils";

import { useNodes } from "./graph-data";
import { collectSources, paperIdsToLoad, SourceRow } from "./sources";
import type { EdgeEvidence } from "./types";

type Node = EdgeEvidence["source"];

export function nodeIsVus(node: Node | undefined | null): boolean {
  return isVus((node?.attrs?.classification as string | undefined) ?? null);
}

/**
 * One cited link in plain words: "A can cause B", a hypothesis marked with its reason, and the
 * sources by what they are (papers by title, trials by registry number, databases by name).
 * The full trust breakdown stays on the node and edge pages.
 */
export function EdgeItem({
  id,
  data,
  tone = "default",
}: {
  id: string;
  /** `undefined` while loading, `null` if unavailable. */
  data: EdgeEvidence | null | undefined;
  /** Kept for callers; the sources are always shown now. */
  defaultOpen?: boolean;
  tone?: "default" | "contradiction";
}) {
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
        The sources for this link could not be loaded right now.
      </p>
    );
  }
  const vus = nodeIsVus(data.source) || nodeIsVus(data.target);
  const inferred = data.edge.origin === "inferred";
  const nodeLink = (n: Node) => (
    <Link href={`/node/${encodeURIComponent(n.id)}`} className="font-medium underline-offset-2 hover:underline">
      {n.label}
    </Link>
  );
  return (
    <div
      className={cn("rounded-lg border bg-card px-3 py-2", tone === "contradiction" && "border-confidence-low/40")}
      data-testid="edge-item"
      data-edge-id={id}
    >
      {/* The link as a plain sentence, never an internal relation name. */}
      <p className="text-[13px] leading-snug" dir="auto">
        {nodeLink(data.source)} <span className="text-muted-foreground">{relationLabel(data.edge.relation, "plain")}</span>{" "}
        {nodeLink(data.target)}
        {data.edge.status !== "active" && <span className="ml-1.5 text-xs text-status-flag">(under review)</span>}
      </p>
      {inferred && (
        <p className="mt-1 flex items-start gap-1.5 text-xs text-muted-foreground">
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-dashed border-foreground/40 px-1.5 leading-4 font-medium text-foreground">
            <Lightbulb className="size-3" aria-hidden /> Hypothesis
          </span>
          <span dir="auto">{data.edge.explanation ?? "Worked out from the data, not confirmed by a study."}</span>
        </p>
      )}
      {vus && <VusNotice compact className="mt-2" />}
      <EdgeSources data={data} />
    </div>
  );
}

/** The link's own sources, by what they are (papers by title, databases by name). */
function EdgeSources({ data }: { data: EdgeEvidence }) {
  const papers = useNodes(paperIdsToLoad([data]).slice(0, 6));
  const docs = collectSources([{ edgeIds: [data.edge.id] }], { [data.edge.id]: data }, papers);
  if (docs.length === 0) return <p className="mt-1 text-xs text-muted-foreground">No sources listed for this link.</p>;
  return (
    <ul className="mt-1 divide-y">
      {docs.map((d) => (
        <SourceRow key={d.key} doc={d} />
      ))}
    </ul>
  );
}
