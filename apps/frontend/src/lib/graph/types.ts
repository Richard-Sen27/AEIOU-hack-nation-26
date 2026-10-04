/**
 * Graph enums and shapes shared by every view (system spec, "Graph data
 * model"). These mirror the API; once the generated client exists, prefer its
 * response types for payloads and use these enums for presentation logic.
 */

export const NODE_TYPES = [
  "disease",
  "gene",
  "variant",
  "mechanism",
  "pathway",
  "phenotype",
  "paper",
  "claim",
  "researcher",
  "doctor",
  "institution",
  "network",
  "grant",
  "trial",
  "patient_org",
  "registry",
  "cluster",
] as const;
export type NodeType = (typeof NODE_TYPES)[number];

export const EDGE_FAMILIES = ["dna", "symptoms", "research", "community"] as const;
export type EdgeFamily = (typeof EDGE_FAMILIES)[number];

export const RELATIONS = [
  "caused_by_variant_in",
  "acts_via",
  "participates_in",
  "has_phenotype",
  "same_gene_same_mechanism",
  "same_gene_different_mechanism",
  "shared_pathway",
  "similar_symptoms",
  "shared_researcher",
  "shared_gene",
  "near_on_chromosome",
  "candidate_phenotype",
  "suggested_by_neighbour",
  "asserts",
  "authored",
  "pi_of",
  "funds_research_on",
  "serves",
  "runs",
  "studies",
  "investigator_of",
  "affiliated_with",
  "variant_of",
  "observed_in",
  "member_of",
  "about",
] as const;
export type Relation = (typeof RELATIONS)[number];

export const ORIGINS = [
  "observed",
  "inferred",
  "patient_reported",
  "user_contributed",
] as const;
export type Origin = (typeof ORIGINS)[number];

export const EDGE_STATUSES = ["active", "pending_review", "under_review"] as const;
export type EdgeStatus = (typeof EDGE_STATUSES)[number];

export const EVIDENCE_TIERS = [
  "curated_db",
  "peer_reviewed",
  "review",
  "preprint",
  "llm_inferred",
  "patient_reported",
  "computed",
] as const;
export type EvidenceTier = (typeof EVIDENCE_TIERS)[number];

/** Stage 4 tier weights. */
export const TIER_WEIGHTS: Record<EvidenceTier, number> = {
  curated_db: 0.9,
  peer_reviewed: 0.7,
  review: 0.5,
  preprint: 0.4,
  llm_inferred: 0.3,
  patient_reported: 0.2,
  /** Ceiling only: each computed row is weighted by its link's own score (tier_weight). */
  computed: 0.79,
};

export type Polarity = "supports" | "contradicts";

export type Evidence = {
  id?: string | number;
  edge_id?: string;
  tier: EvidenceTier;
  tier_weight?: number;
  source_type: string;
  source_id?: string | null;
  url?: string | null;
  quote?: string | null;
  retrieved_at?: string | null;
  polarity: Polarity;
};

export type GraphNode = {
  id: string;
  type: NodeType;
  label: string;
  description?: string | null;
  cluster_id?: string | null;
  x?: number | null;
  y?: number | null;
  centrality?: number | null;
  /** Variants: ClinVar-style classification, e.g. "uncertain_significance". */
  classification?: string | null;
};

export type GraphEdge = {
  id: string;
  source_id: string;
  target_id: string;
  relation: Relation;
  family: EdgeFamily;
  confidence: number;
  origin: Origin;
  status: EdgeStatus;
  features?: Record<string, unknown> | null;
  data_version?: string | null;
  evidence?: Evidence[];
};

export type Role = "guest" | "patient" | "doctor" | "researcher";
export const ROLES: Role[] = ["guest", "patient", "doctor", "researcher"];

export function isNodeType(v: string): v is NodeType {
  return (NODE_TYPES as readonly string[]).includes(v);
}

/** VUS check across the spellings the sources use. */
export function isVus(classification?: string | null): boolean {
  if (!classification) return false;
  const c = classification.toLowerCase().replace(/[\s-]+/g, "_");
  return c === "vus" || c === "uncertain_significance" || c.includes("uncertain");
}
