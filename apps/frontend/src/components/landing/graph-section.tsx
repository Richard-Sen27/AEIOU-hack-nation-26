"use client";

import Link from "next/link";
import { useMemo, useRef, useState } from "react";

import { ConfidenceBadge, OriginBadge } from "@/components/graph-ui";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { relationLabel } from "@/lib/graph/meta";
import type { Origin } from "@/lib/graph/types";

import { AtlasPreview } from "./atlas-preview";
import type { AtlasPreviewModel, PreviewLink } from "./atlas-preview-model";
import { GENE_FOCUS_ID, HERO_FOCUS_ID } from "./landing-config";
import { SectionHead } from "./section-head";
import { useAtlasPreview, useInView } from "./use-atlas-preview";

const nodeHref = (id: string) => `/node/${encodeURIComponent(id)}`;
const plain = (label: string) => label.split(" · ")[0];

function LinkCard({ model, link }: { model: AtlasPreviewModel; link: PreviewLink }) {
  const { edge } = link;
  const source = model.points.get(edge.source);
  const target = model.points.get(edge.target);
  if (!source || !target) return null;
  return (
    <article className="rounded-xl border bg-card p-4" data-testid={`link-card-${edge.origin}`}>
      <div className="flex flex-wrap items-center gap-1.5">
        <OriginBadge origin={edge.origin as Origin} />
        <ConfidenceBadge confidence={edge.confidence} />
      </div>
      <p className="mt-3 text-[15px] leading-snug">
        <Link href={nodeHref(source.id)} className="font-medium underline-offset-2 hover:underline">
          {plain(source.label)}
        </Link>{" "}
        <span className="text-muted-foreground">{relationLabel(edge.relation, "plain")}</span>{" "}
        <Link href={nodeHref(target.id)} className="font-medium underline-offset-2 hover:underline">
          {plain(target.label)}
        </Link>
      </p>
      {edge.explanation && (
        <p className="mt-2 line-clamp-3 text-sm leading-relaxed text-muted-foreground">{edge.explanation}</p>
      )}
    </article>
  );
}

/** S2: click one thing and its real links appear, cited (solid) and computed (dashed). */
export function GraphSection() {
  const frame = useRef<HTMLDivElement>(null);
  const inView = useInView(frame);
  const preview = useAtlasPreview();
  const model = preview.status === "ready" ? preview.data : null;

  // Chips from live ids only: a chip whose id is not in the tree is hidden.
  const chips = useMemo(() => {
    if (!model) return [];
    const ids = [HERO_FOCUS_ID, GENE_FOCUS_ID, model.topCommunityId];
    return [...new Set(ids)]
      .filter((id): id is string => !!id && model.points.has(id))
      .map((id) => ({ id, label: plain(model.points.get(id)!.label) }));
  }, [model]);

  const [picked, setPicked] = useState<string | null>(null);
  const focusId = picked && chips.some((c) => c.id === picked) ? picked : (chips[0]?.id ?? null);
  const links = model && focusId ? model.linksOf(focusId) : [];
  const observed = links.find((l) => l.edge.origin === "observed");
  const inferred = links.find((l) => l.edge.origin === "inferred");
  const nCited = links.filter((l) => l.edge.origin === "observed").length;
  const focusLabel = model && focusId ? plain(model.points.get(focusId)!.label) : "";
  const aria = focusId
    ? `${focusLabel}: ${links.length} links, ${nCited} cited, ${links.length - nCited} computed`
    : undefined;

  return (
    <section aria-labelledby="graph-heading" className="mx-auto w-full max-w-5xl px-4 py-12 sm:px-6 sm:py-14" data-testid="graph-section">
      <SectionHead id="graph-heading" title="Click one thing. See everything linked." sub="Solid lines are cited facts. Dashed lines are computed hypotheses." />
      <div className="mt-6 flex min-h-8 justify-center">
        {chips.length > 0 && (
          <ToggleGroup
            aria-label="Focus"
            variant="outline"
            size="sm"
            value={focusId ? [focusId] : []}
            onValueChange={(v: unknown[]) => {
              const next = v[0];
              if (typeof next === "string") setPicked(next);
            }}
            className="flex-wrap justify-center"
          >
            {chips.map((c) => (
              <ToggleGroupItem key={c.id} value={c.id} title={c.label} className="max-w-[16rem] rounded-full px-3 data-[pressed]:bg-primary/10 data-[pressed]:text-foreground">
                <span className="truncate">{c.label}</span>
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        )}
      </div>
      <div className="mt-6 grid gap-4 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] lg:items-start">
        <div ref={frame} className="relative aspect-[4/3] overflow-hidden rounded-2xl border bg-card/70">
          {inView && model && focusId && (
            <AtlasPreview model={model} focusId={focusId} zoom="focus" endpointLabels={8} label={aria} />
          )}
        </div>
        <div className="grid min-h-48 content-start gap-3" aria-live="polite">
          {model && observed && <LinkCard model={model} link={observed} />}
          {model && inferred && <LinkCard model={model} link={inferred} />}
        </div>
      </div>
    </section>
  );
}
