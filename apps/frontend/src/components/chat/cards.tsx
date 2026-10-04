"use client";

import { ArrowUpRight, FileSearch, HeartHandshake, Map as MapIcon, Share2 } from "lucide-react";
import Link from "next/link";

import { atlasHandoffClick } from "@/components/atlas/atlas-handoff";
import { NodeChip, VusNotice } from "@/components/graph-ui";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useLens } from "@/components/providers/lens-provider";
import { nodeTypeMeta } from "@/lib/graph/meta";
import { isVus } from "@/lib/graph/types";
import { cn } from "@/lib/utils";

import { EdgeItem } from "./edge-item";
import { useEdges, useNodes } from "./graph-data";
import { MiniGraph } from "./mini-graph";
import type { Card, NodeDetail } from "./types";

const CARD_META = {
  mini_graph: { icon: Share2, title: "How these connect" },
  patient_group: { icon: HeartHandshake, title: "Patient groups" },
  evidence: { icon: FileSearch, title: "Where this comes from" },
  open_in_atlas: { icon: MapIcon, title: "Open in Atlas" },
} as const;

function detailIsVus(d: NodeDetail | null | undefined) {
  return !!d && (!!d.vus_notice || isVus(d.classification ?? (d.node.attrs?.classification as string | undefined)));
}

function CardFrame({ card, children }: { card: Card; children: React.ReactNode }) {
  const meta = CARD_META[card.type] ?? CARD_META.evidence;
  const Icon = meta.icon;
  return (
    <article className="rounded-xl border bg-card p-3.5" data-testid={`card-${card.type}`}>
      <h3 className="mb-2.5 flex items-center gap-2 text-sm font-medium">
        <Icon className="size-4 text-primary" aria-hidden />
        {meta.title}
      </h3>
      {children}
    </article>
  );
}

function MiniGraphCard({ card }: { card: Card }) {
  const edges = useEdges(card.edge_ids);
  const nodes = useNodes(card.node_ids);
  const vus = card.node_ids.some((id) => detailIsVus(nodes[id]));
  return (
    <CardFrame card={card}>
      <MiniGraph nodeIds={card.node_ids} edgeIds={card.edge_ids} edges={edges} nodes={nodes} />
      {vus && <VusNotice compact className="mt-2" />}
    </CardFrame>
  );
}

function PatientGroupCard({ card }: { card: Card }) {
  const nodes = useNodes(card.node_ids);
  const edges = useEdges(card.edge_ids);
  return (
    <CardFrame card={card}>
      <ul className="space-y-2">
        {card.node_ids.map((id) => {
          const d = nodes[id];
          if (d === undefined) return <Skeleton key={id} className="h-14 w-full" />;
          if (d === null) {
            return (
              <li key={id}>
                <NodeChip id={id} type="patient_org" label={id} size="sm" />
              </li>
            );
          }
          const n = d.node;
          return (
            <li key={id} className="rounded-lg border bg-background/50 p-2.5">
              <div className="flex flex-wrap items-center gap-2">
                <NodeChip id={n.id} type={n.type} label={n.label} />
                {n.url && (
                  <a
                    href={n.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    referrerPolicy="no-referrer"
                    className="inline-flex items-center gap-0.5 text-xs font-medium underline-offset-2 hover:underline"
                  >
                    Website <ArrowUpRight className="size-3" aria-hidden />
                    <span className="sr-only">(opens in a new tab)</span>
                  </a>
                )}
              </div>
              {(d.summary || n.description) && (
                <p className="mt-1.5 text-sm text-muted-foreground" dir="auto">
                  {d.summary || n.description}
                </p>
              )}
            </li>
          );
        })}
      </ul>
      {card.edge_ids.length > 0 && (
        <div className="mt-2.5 space-y-2">
          <p className="text-xs text-muted-foreground">Why they are listed</p>
          {card.edge_ids.map((id) => (
            <EdgeItem key={id} id={id} data={edges[id]} />
          ))}
        </div>
      )}
    </CardFrame>
  );
}

function EvidenceCard({ card }: { card: Card }) {
  const edges = useEdges(card.edge_ids);
  return (
    <CardFrame card={card}>
      <div className="space-y-2">
        {card.edge_ids.map((id) => (
          <EdgeItem key={id} id={id} data={edges[id]} />
        ))}
        {card.edge_ids.length === 0 && <p className="text-sm text-muted-foreground">No links cited.</p>}
      </div>
    </CardFrame>
  );
}

function OpenInAtlasCard({ card }: { card: Card }) {
  const nodes = useNodes(card.node_ids);
  const { labelStyle } = useLens();
  return (
    <CardFrame card={card}>
      <ul className="space-y-2">
        {card.node_ids.map((id) => {
          const n = nodes[id]?.node;
          const label = n?.label ?? id;
          return (
            <li key={id} className="flex flex-wrap items-center gap-2">
              <span className="min-w-0 flex-1 truncate text-sm font-medium">
                {label}
                {n && <span className="ml-1.5 text-xs font-normal text-muted-foreground">{nodeTypeMeta(n.type).label[labelStyle]}</span>}
              </span>
              <Link
                // Ids from a health conversation stay out of the URL: in-memory handoff.
                href="/atlas"
                onClick={atlasHandoffClick({ nodeIds: [id], edgeIds: card.edge_ids })}
                className={cn(buttonVariants({ variant: "default", size: "sm" }))}
              >
                <MapIcon aria-hidden /> Open in Atlas<span className="sr-only">: {label}</span>
              </Link>
              <Link href={`/node/${encodeURIComponent(id)}`} className={cn(buttonVariants({ variant: "outline", size: "sm" }))}>
                Details<span className="sr-only">: {label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </CardFrame>
  );
}

/** Cards from the reply: mini graph, patient groups, evidence, open in Atlas. */
export function Cards({ cards }: { cards: Card[] }) {
  if (cards.length === 0) return null;
  return (
    <div className="grid gap-3" data-testid="cards">
      {cards.map((card, i) => {
        const body =
          card.type === "mini_graph" ? (
            <MiniGraphCard card={card} />
          ) : card.type === "patient_group" ? (
            <PatientGroupCard card={card} />
          ) : card.type === "open_in_atlas" ? (
            <OpenInAtlasCard card={card} />
          ) : (
            <EvidenceCard card={card} />
          );
        return (
          <div key={i}>{body}</div>
        );
      })}
    </div>
  );
}
