/**
 * API payloads for the graph specs, derived from the backend's hand-written
 * demo graph (apps/backend/src/backend/fixtures/demo_graph.json) so the
 * mocks have the shape and texture of the real read path.
 */
import { readFileSync } from "node:fs";
import path from "node:path";

type FxEvidence = {
  tier: string;
  source_type: string;
  source_id: string | null;
  url: string | null;
  quote: string | null;
  retrieved_at: string | null;
  polarity: "supports" | "contradicts";
  claim_type: string | null;
};
type FxNode = {
  id: string;
  type: string;
  label: string;
  description: string | null;
  url: string | null;
  attrs: Record<string, unknown>;
  cluster_id: string | null;
  synonyms: Array<{ synonym: string }>;
  x: number;
  y: number;
  centrality: number;
};
type FxEdge = {
  id: string;
  source_id: string;
  target_id: string;
  relation: string;
  family: string;
  confidence: number;
  origin: string;
  status: string;
  features: Record<string, unknown> | null;
  evidence: FxEvidence[];
};
type FxCluster = { id: string; label: string; mechanism_summary: string; attrs: Record<string, unknown>; member_count: number };

export const fixture = JSON.parse(
  readFileSync(path.resolve(__dirname, "../../../backend/src/backend/fixtures/demo_graph.json"), "utf8"),
) as { nodes: FxNode[]; edges: FxEdge[]; clusters: FxCluster[]; demo: Record<string, unknown> };

export const DEMO = fixture.demo as {
  counterexample_edge_id: string;
  contradicted_edge_id: string;
  pending_review_edge_id: string;
  vus_variant_id: string;
};

const nodeById = new Map(fixture.nodes.map((n) => [n.id, n]));
const level = (c: number) => (c >= 0.8 ? "high" : c >= 0.5 ? "medium" : "low");

export function apiNode(n: FxNode) {
  const { synonyms: _s, ...rest } = n;
  void _s;
  return rest;
}

export function apiEdge(e: FxEdge) {
  const { evidence, ...rest } = e;
  return {
    ...rest,
    confidence_level: level(e.confidence),
    data_version: "fixture",
    evidence_count: evidence.length,
    contradiction_count: evidence.filter((x) => x.polarity === "contradicts").length,
    flagged: e.status === "under_review",
  };
}

export const clusters = fixture.clusters.map((c) => ({ ...c, origin: "inferred" }));

export function atlasPayload() {
  return {
    nodes: fixture.nodes.map((n) => ({
      id: n.id,
      type: n.type,
      label: n.label,
      x: n.x,
      y: n.y,
      cluster_id: n.cluster_id,
      centrality: n.centrality,
    })),
    edges: fixture.edges.map((e) => ({
      id: e.id,
      source: e.source_id,
      target: e.target_id,
      relation: e.relation,
      family: e.family,
      confidence: e.confidence,
      origin: e.origin,
      status: e.status,
    })),
    clusters,
    data_version: "fixture",
  };
}

export const HINTS = {
  guest: { start_layout: "ring", label_style: "plain", highlight_family: ["symptoms", "community"], highlight_node_types: ["disease", "patient_org"], show_ids: false },
  patient: { start_layout: "ring", label_style: "plain", highlight_family: ["symptoms", "community"], highlight_node_types: ["disease", "patient_org", "registry"], show_ids: false },
  doctor: { start_layout: "ring", label_style: "clinical", highlight_family: ["symptoms", "community"], highlight_node_types: ["phenotype", "institution", "trial", "variant"], show_ids: false },
  researcher: { start_layout: "force", label_style: "technical", highlight_family: ["dna", "research"], highlight_node_types: ["variant", "pathway", "paper", "grant"], show_ids: true },
} as const;

export function neighborhood(id: string, role: keyof typeof HINTS = "guest") {
  const center = nodeById.get(id);
  if (!center) return null;
  const edges = fixture.edges.filter((e) => e.source_id === id || e.target_id === id);
  const ids = new Set<string>([id]);
  edges.forEach((e) => {
    ids.add(e.source_id);
    ids.add(e.target_id);
  });
  // Cluster nodes: their neighbourhood is their members.
  if (center.type === "cluster") fixture.nodes.filter((n) => n.cluster_id === id).forEach((n) => ids.add(n.id));
  const all = fixture.edges.filter((e) => ids.has(e.source_id) && ids.has(e.target_id));
  const cluster = clusters.find((c) => c.id === center.cluster_id) ?? null;
  return {
    center: apiNode(center),
    nodes: [...ids].map((n) => apiNode(nodeById.get(n)!)),
    edges: all.map(apiEdge),
    cluster,
    hints: HINTS[role],
    data_version: "fixture",
  };
}

export function nodeDetail(id: string) {
  const n = nodeById.get(id);
  if (!n) return null;
  const edges = fixture.edges.filter((e) => e.source_id === id || e.target_id === id);
  const counts = new Map<string, { relation: string; family: string; count: number }>();
  edges.forEach((e) => {
    const c = counts.get(e.relation) ?? { relation: e.relation, family: e.family, count: 0 };
    c.count++;
    counts.set(e.relation, c);
  });
  const classification = (n.attrs.classification as string | undefined) ?? null;
  return {
    node: apiNode(n),
    synonyms: n.synonyms.map((s) => s.synonym),
    summary: n.description,
    relation_counts: [...counts.values()],
    degree: edges.length,
    cluster: clusters.find((c) => c.id === n.cluster_id) ?? null,
    classification,
    vus_notice:
      classification === "uncertain_significance"
        ? "This result is uncertain. Discuss it with a genetic counselor before acting on it."
        : null,
  };
}

export function edgeEvidence(id: string) {
  const e = fixture.edges.find((x) => x.id === id);
  if (!e) return null;
  const ev = e.evidence.map((x, i) => ({
    ...x,
    id: i + 1,
    edge_id: e.id,
    tier_weight: { curated_db: 0.9, peer_reviewed: 0.7, review: 0.5, preprint: 0.4, llm_inferred: 0.3, patient_reported: 0.2 }[x.tier] ?? 0.3,
  }));
  const supporting = ev.filter((x) => x.polarity === "supports");
  const contradicting = ev.filter((x) => x.polarity === "contradicts");
  const support = 1 - supporting.reduce((p, x) => p * (1 - x.tier_weight), 1);
  const penalty = 0.15 * contradicting.length;
  const result = Math.max(0, Math.min(1, support - penalty));
  return {
    edge: apiEdge(e),
    source: apiNode(nodeById.get(e.source_id)!),
    target: apiNode(nodeById.get(e.target_id)!),
    supporting,
    contradicting,
    confidence_breakdown: {
      supporting: supporting.map((x) => ({ evidence_id: x.id, tier: x.tier, weight: x.tier_weight })),
      support_score: support,
      n_contradicting: contradicting.length,
      penalty_per_contradiction: 0.15,
      penalty,
      result,
      level: level(result),
      formula: `1 - ${supporting.map((x) => `(1 - ${x.tier_weight})`).join(" × ")} - 0.15 × ${contradicting.length} = ${result.toFixed(2)}`,
    },
    open_flags: e.status === "under_review" ? 1 : 0,
  };
}

/** Mock table for every graph read endpoint. Role is read from `?role=`. */
export function graphMocks(extra: Record<string, unknown> = {}) {
  const lastSegment = (url: string) => decodeURIComponent(new URL(url).pathname.split("/").pop()!);
  return {
    "GET /auth/session": { user: null, gpc: false, demo_mode: false, data_version: "fixture" },
    "GET /atlas.json": atlasPayload(),
    "GET /clusters": clusters,
    "GET /node/*": ({ url }: { url: string }) => {
      const d = nodeDetail(lastSegment(url));
      return d ? { json: d } : { status: 404, json: { error: { code: "not_found", message: "Not found" } } };
    },
    "GET /neighborhood/*": ({ url }: { url: string }) => {
      const role = (new URL(url).searchParams.get("role") ?? "guest") as keyof typeof HINTS;
      const d = neighborhood(lastSegment(url), role);
      return d ? { json: d } : { status: 404, json: { error: { code: "not_found", message: "Not found" } } };
    },
    "GET /edge/*/evidence": ({ url }: { url: string }) => {
      const parts = new URL(url).pathname.split("/");
      const d = edgeEvidence(decodeURIComponent(parts[parts.length - 2]));
      return d ? { json: d } : { status: 404, json: { error: { code: "not_found", message: "Not found" } } };
    },
    ...extra,
  };
}

/** Synthetic large Atlas: `n` nodes in clustered blobs, `m` edges. */
export function largeAtlas(n = 3000, m = 20000) {
  let seed = 42;
  const rand = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296);
  const types = ["disease", "gene", "phenotype", "variant", "paper", "researcher", "patient_org", "trial", "pathway"];
  const families = ["dna", "symptoms", "research", "community"];
  const origins = ["observed", "observed", "observed", "inferred", "patient_reported"];
  const k = 40;
  const centers = Array.from({ length: k }, () => ({ x: (rand() - 0.5) * 4000, y: (rand() - 0.5) * 4000 }));
  const nodes = Array.from({ length: n }, (_, i) => {
    const c = i % k;
    const r = rand() * 300;
    const a = rand() * Math.PI * 2;
    return {
      id: `SYN:${i}`,
      type: types[Math.floor(rand() * types.length)],
      label: `Synthetic item ${i}`,
      x: centers[c].x + Math.cos(a) * r,
      y: centers[c].y + Math.sin(a) * r,
      cluster_id: `CLUSTER:${c + 1}`,
      centrality: rand() ** 3,
    };
  });
  const edges = Array.from({ length: m }, (_, i) => {
    const s = Math.floor(rand() * n);
    let t = rand() < 0.8 ? s - (s % k) + Math.floor(rand() * k) : Math.floor(rand() * n);
    if (t === s || t >= n) t = (s + 1) % n;
    return {
      id: `e_syn${i}`,
      source: `SYN:${s}`,
      target: `SYN:${t}`,
      relation: "similar_symptoms",
      family: families[i % 4],
      confidence: rand(),
      origin: origins[i % origins.length],
      status: i % 997 === 0 ? "under_review" : "active",
    };
  });
  const cl = centers.map((_, c) => ({
    id: `CLUSTER:${c + 1}`,
    label: `Synthetic group ${c + 1}`,
    mechanism_summary: null,
    member_count: Math.ceil(n / k),
    origin: "inferred",
  }));
  return { nodes, edges, clusters: cl, data_version: "synthetic" };
}
