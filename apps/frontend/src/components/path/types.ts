import type { Schemas } from "@/lib/api";
import type { NodeType } from "@/lib/graph/types";

export type PathResponse = Schemas.PathResponse;
export type PathT = Schemas.Path;
export type PathStep = Schemas.PathStep;
export type ApiNode = Schemas.Node;
export type ApiEdge = Schemas.Edge;
export type CoverageReport = Schemas.CoverageReport;
export type EdgeEvidence = Schemas.EdgeEvidence;
export type ExplainEvent = Schemas.ExplainEvent;
export type ExplainFinal = Schemas.ExplainFinalEvent;
export type GapSearchEvent = Schemas.GapSearchEvent;
export type CandidateEdge = Schemas.CandidateEdge;
export type GapStopReason = Schemas.GapStopReason;

export const FAMILIES = ["all", "dna", "symptoms", "research"] as const;
export type Family = (typeof FAMILIES)[number];

export function parseFamily(v: string | null | undefined): Family {
  return (FAMILIES as readonly string[]).includes(v ?? "") ? (v as Family) : "all";
}

/** A node the user picked (or that arrived prefilled from another page). */
export type Endpoint = { id: string; label: string; type: NodeType | string };

export type CandidateEdgeContributionCreate = Schemas.CandidateEdgeContributionCreate;

/** Builds the `/path` URL. Only public graph ids go in it (docs/compliance.md). */
export function pathHref({ from, to, family }: { from?: string | null; to?: string | null; family?: Family }) {
  const q = new URLSearchParams();
  if (from) q.set("from", from);
  if (to) q.set("to", to);
  if (family && family !== "all") q.set("family", family);
  const s = q.toString();
  return s ? `/path?${s}` : "/path";
}
