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

const CATEGORY_ORDER = [
  "researchers",
  "institutions",
  "literature",
  "community",
  "pathways",
  "genes",
  "diseases",
  "symptoms",
  "doctors",
] as const;
const CATEGORY_LABELS: Record<string, string> = {
  researchers: "Researchers",
  institutions: "Hospitals & universities",
  literature: "Literature",
  community: "Community",
  pathways: "Pathways",
  genes: "Genes",
  diseases: "Diseases",
  symptoms: "Symptoms",
  doctors: "Doctors",
};
const TYPE_CATEGORY: Record<string, string> = {
  researcher: "researchers",
  institution: "institutions",
  paper: "literature",
  trial: "literature",
  grant: "literature",
  claim: "literature",
  patient_org: "community",
  registry: "community",
  network: "community",
  pathway: "pathways",
  gene: "genes",
  variant: "genes",
  mechanism: "genes",
  disease: "diseases",
  cluster: "diseases",
  phenotype: "symptoms",
  doctor: "doctors",
};

/**
 * A valid `GET /atlas/tree.json` built from the fixture: root -> 9 categories
 * -> one group per node type -> entities, with simple polar positions
 * (sectors clockwise from 12 o'clock, angle counter-clockwise from +x).
 */
export function atlasTreePayload() {
  type TreeNode = {
    id: string;
    kind: "root" | "category" | "group" | "entity";
    label: string;
    parent_id: string | null;
    category: string | null;
    depth: number;
    x: number;
    y: number;
    angle: number;
    entity_type: string | null;
    group_basis: string | null;
    ref_id: string | null;
    entity_count: number;
    child_count: number;
    cluster_id: string | null;
    centrality: number | null;
    contributed: boolean;
  };
  const byCat = new Map<string, Map<string, FxNode[]>>();
  for (const n of fixture.nodes) {
    const cat = TYPE_CATEGORY[n.type];
    if (!byCat.has(cat)) byCat.set(cat, new Map());
    const groups = byCat.get(cat)!;
    if (!groups.has(n.type)) groups.set(n.type, []);
    groups.get(n.type)!.push(n);
  }
  const total = fixture.nodes.length;
  const gap = (3 * Math.PI) / 180;
  const usable = 2 * Math.PI - gap * CATEGORY_ORDER.length;
  const polar = (r: number, a: number) => ({ x: +(r * Math.cos(a)).toFixed(2), y: +(r * Math.sin(a)).toFixed(2), angle: +a.toFixed(5) });
  const base = (over: Partial<TreeNode> & Pick<TreeNode, "id" | "kind" | "label">): TreeNode => ({
    parent_id: null,
    category: null,
    depth: 0,
    x: 0,
    y: 0,
    angle: 0,
    entity_type: null,
    group_basis: null,
    ref_id: null,
    entity_count: 0,
    child_count: 0,
    cluster_id: null,
    centrality: null,
    contributed: false,
    ...over,
  });
  const nodes: TreeNode[] = [base({ id: "T:root", kind: "root", label: "Atlas", entity_count: total, child_count: 9 })];
  const categories: Array<Record<string, unknown>> = [];
  let start = Math.PI / 2;
  for (const cat of CATEGORY_ORDER) {
    const groups = byCat.get(cat) ?? new Map<string, FxNode[]>();
    const count = [...groups.values()].reduce((s, g) => s + g.length, 0);
    const span = Math.max((usable * count) / total, (14 * Math.PI) / 180);
    const end = start - span;
    const mid = (start + end) / 2;
    const catId = `T:${cat}`;
    nodes.push(
      base({ id: catId, kind: "category", label: CATEGORY_LABELS[cat], parent_id: "T:root", category: cat, depth: 1, ...polar(180, mid), entity_count: count, child_count: groups.size }),
    );
    let gStart = start;
    for (const [type, members] of groups) {
      const gSpan = (span * members.length) / Math.max(count, 1);
      const gMid = gStart - gSpan / 2;
      const gid = `${catId}/${type}`;
      nodes.push(
        base({ id: gid, kind: "group", label: type, parent_id: catId, category: cat, depth: 2, ...polar(320, gMid), group_basis: "subcategory", entity_count: members.length, child_count: members.length }),
      );
      [...members]
        .sort((a, b) => a.label.localeCompare(b.label))
        .forEach((m, i) => {
          const a = gStart - (gSpan * (i + 0.5)) / members.length;
          nodes.push(
            base({ id: m.id, kind: "entity", label: m.label, parent_id: gid, category: cat, depth: 3, ...polar(460 + (i % 3) * 40, a), entity_type: m.type, entity_count: 1, cluster_id: m.cluster_id, centrality: m.centrality }),
          );
        });
      gStart -= gSpan;
    }
    categories.push({ id: cat, node_id: catId, label: CATEGORY_LABELS[cat], entity_count: count, angle_start: start, angle_end: end, ...(() => { const p = polar(660, mid); return { label_x: p.x, label_y: p.y }; })() });
    start = end - gap;
  }
  return {
    data_version: "fixture",
    layout_version: 1,
    root_id: "T:root",
    categories,
    nodes,
    edges: atlasPayload().edges,
    clusters,
  };
}

const SECTION_BY_TYPE: Record<string, string> = {
  cluster: "clusters",
  disease: "diseases",
  gene: "genes",
  variant: "variants",
  mechanism: "mechanisms",
  pathway: "pathways",
  phenotype: "symptoms",
  researcher: "researchers",
  doctor: "doctors",
  institution: "institutions",
  paper: "papers",
  trial: "trials",
  grant: "grants",
  patient_org: "patient_orgs",
  registry: "registries",
  network: "networks",
  claim: "claims",
};
const SECTION_ORDER = [
  "clusters", "diseases", "similar_diseases", "genes", "variants", "mechanisms", "pathways", "symptoms", "researchers",
  "doctors", "institutions", "papers", "trials", "grants", "patient_orgs", "registries", "networks", "claims",
];

/** `GET /atlas/summary/{id}`: 1-hop sections from the fixture (no extra chains). Null for unknown or `T:` ids. */
export function atlasSummary(id: string) {
  const n = nodeById.get(id);
  if (!n) return null;
  const tree = atlasTreePayload();
  const treeById = new Map(tree.nodes.map((t) => [t.id, t]));
  const path: Array<{ id: string; label: string; kind: string }> = [];
  let parent = treeById.get(id)?.parent_id ?? null;
  while (parent) {
    const t = treeById.get(parent)!;
    path.unshift({ id: t.id, label: t.label, kind: t.kind });
    parent = t.parent_id;
  }
  const sections = new Map<string, { key: string; node_type: string; total: number; items: Array<Record<string, unknown>> }>();
  for (const e of fixture.edges) {
    if (e.source_id !== id && e.target_id !== id) continue;
    const other = nodeById.get(e.source_id === id ? e.target_id : e.source_id);
    if (!other) continue;
    const key = n.type === "disease" && other.type === "disease" ? "similar_diseases" : SECTION_BY_TYPE[other.type];
    if (!sections.has(key)) sections.set(key, { key, node_type: other.type, total: 0, items: [] });
    const s = sections.get(key)!;
    if (s.items.some((i) => i.id === other.id)) continue;
    s.total += 1;
    s.items.push({
      id: other.id,
      label: other.label,
      type: other.type,
      hops: 1,
      score: 1,
      best_confidence: e.confidence,
      inferred: e.origin !== "observed",
      under_review: e.status !== "active",
      via: [e.id],
      via_label: null,
    });
  }
  const ordered = SECTION_ORDER.filter((k) => sections.has(k)).map((k) => {
    const s = sections.get(k)!;
    return { ...s, items: s.items.slice(0, 10) };
  });
  const classification = (n.attrs.classification as string | undefined) ?? null;
  return {
    node: apiNode(n),
    tree_path: path,
    headline: n.description ?? n.label,
    sections: ordered,
    explain_edge_ids: ordered.flatMap((s) => s.items.map((i) => (i.via as string[])[0])).slice(0, 20),
    vus_notice:
      classification === "uncertain_significance"
        ? "This result is uncertain. Discuss it with a genetic counselor before acting on it."
        : null,
    data_version: "fixture",
  };
}

/** Mock table for every graph read endpoint. Role is read from `?role=`. */
export function graphMocks(extra: Record<string, unknown> = {}) {
  const lastSegment = (url: string) => decodeURIComponent(new URL(url).pathname.split("/").pop()!);
  return {
    "GET /auth/session": { user: null, gpc: false, demo_mode: false, data_version: "fixture" },
    "GET /atlas.json": atlasPayload(),
    "GET /atlas/tree.json": atlasTreePayload(),
    "GET /atlas/summary/*": ({ url }: { url: string }) => {
      const d = atlasSummary(lastSegment(url));
      return d ? { json: d } : { status: 404, json: { error: { code: "not_found", message: "Not found" } } };
    },
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
