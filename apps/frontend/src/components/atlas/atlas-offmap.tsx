/**
 * Nodes that exist in the atlas but are not drawn on the map (stage A of the
 * wide scope: every qualifying rare disease is findable, the map keeps the
 * focus set). One marker and one set of public id links, shared by the
 * search, the panel and the Dr. Wu dock.
 */
import { MapPinOff } from "lucide-react";

import { cn } from "@/lib/utils";

export const OFF_MAP_LABEL = "Not on the map yet";

/** Small marker for a node that exists but is not on the map. */
export function OffMapMark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full border border-dashed px-1.5 text-[10.5px] leading-4 font-medium text-muted-foreground",
        className,
      )}
      data-testid="atlas-offmap"
    >
      <MapPinOff className="size-3" aria-hidden />
      {OFF_MAP_LABEL}
    </span>
  );
}

export type IdLink = { id: string; href: string };

const strings = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);

/**
 * Public pages for a node's standard ids, linked by id only (never by name):
 * MONDO, Orphanet and OMIM for diseases, HGNC for genes, HPO for symptoms.
 */
export function idLinks(node: { id: string; attrs?: Record<string, unknown> | null }): IdLink[] {
  const ids = [node.id, ...strings(node.attrs?.orpha_ids), ...strings(node.attrs?.omim_ids)];
  const out: IdLink[] = [];
  for (const id of ids) {
    if (out.some((l) => l.id === id)) continue;
    const [prefix, local] = id.split(":", 2);
    if (!local || !/^[A-Za-z0-9_.-]+$/.test(local)) continue;
    const href =
      prefix === "MONDO"
        ? `https://purl.obolibrary.org/obo/MONDO_${local}`
        : prefix === "ORPHA"
          ? `https://www.orpha.net/en/disease/detail/${local}`
          : prefix === "OMIM"
            ? `https://omim.org/entry/${local}`
            : prefix === "HGNC"
              ? `https://www.genenames.org/data/gene-symbol-report/#!/hgnc_id/HGNC:${local}`
              : prefix === "HP"
                ? `https://hpo.jax.org/browse/term/HP:${local}`
                : null;
    if (href) out.push({ id, href });
  }
  return out;
}
