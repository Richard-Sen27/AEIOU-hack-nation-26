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

/** The chromosome group under Genes that holds the fixture's six genes. */
export const GENE_GROUP = "T:genes/chr2";
/** Symptoms drawn as kinds of "Seizure" (a graph phenotype that is also a branch). */
const SEIZURE_KINDS = new Set(["HP:0002373", "HP:0012469", "HP:0002133"]);

export type FxTreeNode = {
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

/**
 * A valid `GET /atlas/tree.json` built from the fixture: root -> 9 categories
 * -> entities, with the branches the specs need: diseases under their
 * cluster, genes under a chromosome group ("Chromosome 2") with their
 * variants below them, and three kinds of seizure under "Seizure". Simple
 * polar positions: each category its own sector clockwise from 12 o'clock
 * (angle counter-clockwise from +x), 180 units to the categories, 140 per
 * level after that; parents before children (pre-order).
 */
export function atlasTreePayload() {
  type Draft = Pick<FxTreeNode, "id" | "kind" | "label" | "parent_id" | "category" | "entity_type" | "group_basis" | "ref_id" | "cluster_id" | "centrality">;
  const drafts: Draft[] = [];
  const add = (n: Partial<Draft> & Pick<Draft, "id" | "kind" | "label" | "parent_id">) =>
    drafts.push({ category: null, entity_type: null, group_basis: null, ref_id: null, cluster_id: null, centrality: null, ...n });
  add({ id: "T:root", kind: "root", label: "Atlas", parent_id: null });
  for (const c of CATEGORY_ORDER) add({ id: `T:${c}`, kind: "category", label: CATEGORY_LABELS[c], parent_id: "T:root", category: c });
  add({ id: GENE_GROUP, kind: "group", label: "Chromosome 2", parent_id: "T:genes", category: "genes", group_basis: "chromosome", ref_id: "2" });
  const variantGene = new Map(fixture.edges.filter((e) => e.relation === "variant_of").map((e) => [e.source_id, e.target_id]));
  // Clusters first, so they lead their category and their diseases hang below them.
  const ordered = [...fixture.nodes].sort((a, b) => Number(b.type === "cluster") - Number(a.type === "cluster"));
  for (const n of ordered) {
    const category = TYPE_CATEGORY[n.type];
    let parent = `T:${category}`;
    if (n.type === "disease" && n.cluster_id) parent = n.cluster_id;
    if (n.type === "gene") parent = GENE_GROUP;
    if (n.type === "variant" && variantGene.has(n.id)) parent = variantGene.get(n.id)!;
    if (SEIZURE_KINDS.has(n.id)) parent = "HP:0001250";
    add({ id: n.id, kind: "entity", label: n.label, parent_id: parent, category, entity_type: n.type, cluster_id: n.cluster_id, centrality: n.centrality });
  }

  const byId = new Map(drafts.map((n) => [n.id, n]));
  const kids = new Map<string, Draft[]>();
  for (const n of drafts) if (n.parent_id) kids.set(n.parent_id, [...(kids.get(n.parent_id) ?? []), n]);
  const count = (id: string): number =>
    (kids.get(id) ?? []).reduce((s, k) => s + count(k.id), byId.get(id)!.kind === "entity" ? 1 : 0);

  const round = (v: number) => +v.toFixed(2);
  const nodes: FxTreeNode[] = [];
  let maxR = 0;
  const walk = (n: Draft, depth: number, a0: number, a1: number) => {
    const angle = (a0 + a1) / 2;
    const r = depth === 0 ? 0 : 180 + (depth - 1) * 140;
    maxR = Math.max(maxR, r);
    const children = kids.get(n.id) ?? [];
    nodes.push({
      ...n,
      depth,
      x: round(r * Math.cos(angle)),
      y: round(r * Math.sin(angle)),
      angle: +angle.toFixed(5),
      entity_count: count(n.id),
      child_count: children.length,
      contributed: false,
    });
    // Children share the parent's span in proportion to their subtree size.
    const total = children.reduce((s, c) => s + Math.max(1, count(c.id)), 0);
    let at = a0;
    for (const c of children) {
      const span = ((a1 - a0) * Math.max(1, count(c.id))) / Math.max(total, 1);
      walk(c, depth + 1, at, at + span);
      at += span;
    }
  };

  const total = count("T:root");
  const gap = (3 * Math.PI) / 180;
  const minSpan = (14 * Math.PI) / 180;
  const raw = CATEGORY_ORDER.map((c) => Math.max(minSpan, ((2 * Math.PI - gap * CATEGORY_ORDER.length) * count(`T:${c}`)) / total));
  const scale = (2 * Math.PI - gap * CATEGORY_ORDER.length) / raw.reduce((s, v) => s + v, 0);
  const spans = raw.map((v) => v * scale);
  nodes.push({ ...byId.get("T:root")!, depth: 0, x: 0, y: 0, angle: 0, entity_count: total, child_count: CATEGORY_ORDER.length, contributed: false });
  const sectors: Array<{ start: number; end: number }> = [];
  let start = Math.PI / 2;
  CATEGORY_ORDER.forEach((c, i) => {
    const end = start - spans[i];
    // From the sector's counter-clockwise edge, so children run clockwise like the categories.
    walk(byId.get(`T:${c}`)!, 1, start, end);
    sectors.push({ start, end });
    start = end - gap;
  });

  return {
    data_version: "fixture",
    layout_version: 4,
    root_id: "T:root",
    categories: CATEGORY_ORDER.map((c, i) => {
      const { start: s, end: e } = sectors[i];
      const mid = (s + e) / 2;
      return {
        id: c,
        node_id: `T:${c}`,
        label: CATEGORY_LABELS[c],
        entity_count: count(`T:${c}`),
        angle_start: +s.toFixed(5),
        angle_end: +e.toFixed(5),
        label_x: round((maxR + 120) * Math.cos(mid)),
        label_y: round((maxR + 120) * Math.sin(mid)),
      };
    }),
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
    coverage: "focus",
    focus_disease_count: FOCUS_DISEASE_COUNT,
  };
}

function summaryItem(id: string, via: string[], extra: Record<string, unknown> = {}) {
  const n = nodeById.get(id)!;
  return {
    id,
    label: n.label,
    type: n.type,
    hops: Math.max(1, via.length),
    score: 1,
    best_confidence: 0.9,
    inferred: false,
    under_review: false,
    via,
    via_label: null,
    ...extra,
  };
}

/** Summary for STXBP1 encephalopathy, with each kind of item the panel must present. */
export function stxbp1Summary() {
  return {
    node: apiNode(nodeById.get("MONDO:9900007")!),
    tree_path: [
      { id: "T:root", label: "Atlas", kind: "root" },
      { id: "T:diseases", label: "Diseases", kind: "category" },
      { id: "CLUSTER:3", label: "Synaptic and potassium channel encephalopathies", kind: "entity" },
    ],
    headline: "A rare genetic condition with early seizures. Linked to 2 genes and 4 researchers in the atlas.",
    sections: [
      {
        key: "clusters",
        node_type: "cluster",
        total: 1,
        items: [summaryItem("CLUSTER:3", [], { inferred: true, best_confidence: 0, via_label: "Member by analysis (hypothesis)" })],
      },
      {
        key: "similar_diseases",
        node_type: "disease",
        total: 14,
        items: [
          summaryItem("MONDO:9900003", ["e_3b8845b635b8"], { inferred: true, under_review: true, best_confidence: 0.55 }),
          summaryItem("MONDO:9900010", ["e_275854103db5"], { inferred: true, best_confidence: 0.4 }),
        ],
      },
      { key: "genes", node_type: "gene", total: 1, items: [summaryItem("HGNC:11444", ["e_e5f778ac8a21"], { best_confidence: 0.97 })] },
      {
        key: "researchers",
        node_type: "researcher",
        total: 2,
        items: [
          summaryItem("RES:fx-alpha", ["e_e5f778ac8a21", "e_0af807385728"], { score: 4, via_label: "via 4 papers" }),
          summaryItem("RES:fx-beta", ["e_e5f778ac8a21", "e_558f7d2a940d"], { score: 1, via_label: "via gene STXBP1" }),
        ],
      },
    ],
    explain_edge_ids: ["e_e5f778ac8a21", "e_3b8845b635b8"],
    vus_notice: null,
    data_version: "fixture",
    coverage: "focus",
    focus_disease_count: FOCUS_DISEASE_COUNT,
  };
}

/**
 * `GET /atlas/summary/*` handler: the hand-written STXBP1 encephalopathy
 * summary, 1-hop summaries for every other fixture entity, 404 otherwise.
 * `overrides` maps an id to a ready mock result.
 */
export function summaryMock(overrides: Record<string, unknown> = {}) {
  return ({ url }: { url: string }) => {
    const id = decodeURIComponent(new URL(url).pathname.split("/").pop()!);
    if (id in overrides) return overrides[id] as Record<string, unknown>;
    const s = id === "MONDO:9900007" ? stxbp1Summary() : atlasSummary(id);
    return s ? { json: s } : { status: 404, json: { error: { code: "not_found", message: "Not found" } } };
  };
}

// ---------------------------------------------------------------------------
// Wide scope, stage A: nodes that exist in the atlas but are not on the map
// (core diseases with their genes and symptoms). None of these ids is in the tree.

/** Diseases with literature, trials and people collected (the map's set). */
export const FOCUS_DISEASE_COUNT = 169;

export const CORE = {
  fop: "MONDO:0007606",
  pcd: "MONDO:0014203",
  acvr1: "HGNC:171",
  fopGeneEdge: "e_core_fop_acvr1",
} as const;

type CoreNode = { id: string; type: string; label: string; attrs: Record<string, unknown> };
const CORE_NODES: CoreNode[] = [
  {
    id: CORE.fop,
    type: "disease",
    label: "fibrodysplasia ossificans progressiva",
    attrs: { tier: "core", orpha_ids: ["ORPHA:337"], omim_ids: ["OMIM:135100"] },
  },
  {
    id: CORE.pcd,
    type: "disease",
    label: "primary ciliary dyskinesia 25",
    attrs: { tier: "core", orpha_ids: [], omim_ids: ["OMIM:615482"] },
  },
  { id: "MONDO:0011989", type: "disease", label: "progressive osseous heteroplasia", attrs: { tier: "core", orpha_ids: ["ORPHA:2762"], omim_ids: ["OMIM:166350"] } },
  { id: CORE.acvr1, type: "gene", label: "ACVR1", attrs: { tier: "core", symbol: "ACVR1" } },
  { id: "HP:0011987", type: "phenotype", label: "Ectopic ossification in muscle tissue", attrs: { tier: "core" } },
  { id: "HP:0001788", type: "phenotype", label: "Hallux valgus", attrs: { tier: "core" } },
  { id: "HP:0000365", type: "phenotype", label: "Hearing impairment", attrs: { tier: "core" } },
  { id: "HP:0034315", type: "phenotype", label: "Chronic cough", attrs: { tier: "core" } },
];
const coreById = new Map(CORE_NODES.map((n) => [n.id, n]));

function coreApiNode(n: CoreNode) {
  return { id: n.id, type: n.type, label: n.label, description: null, url: null, attrs: n.attrs, cluster_id: null, x: 0, y: 0, centrality: 0 };
}

function coreItem(id: string, via: string[], extra: Record<string, unknown> = {}) {
  const n = coreById.get(id) ?? nodeById.get(id)!;
  return { id, label: n.label, type: n.type, hops: 1, score: 1, best_confidence: 0.9, inferred: false, under_review: false, via, via_label: null, explanation: null, ...extra };
}

/** Symptom edges of FOP: edge id, HPO id, frequency (0-1), the source's label. */
const FOP_SYMPTOMS: Array<[string, string, number, string]> = [
  ["e_core_fop_hv", "HP:0001788", 0.55, "Frequent"],
  ["e_core_fop_hear", "HP:0000365", 0.17, "Occasional"],
  ["e_core_fop_ossif", "HP:0011987", 0.9, "Very frequent"],
];

/** `GET /atlas/summary/MONDO:0007606`: a core disease (FOP), no tree path, coverage "core". */
export function coreDiseaseSummary() {
  return {
    node: coreApiNode(coreById.get(CORE.fop)!),
    tree_path: [],
    headline: "A rare genetic condition. Linked to 1 gene and 52 symptoms in the atlas.",
    sections: [
      {
        key: "similar_diseases",
        node_type: "disease",
        total: 2,
        items: [
          coreItem("MONDO:0011989", ["e_core_fop_poh"], {
            inferred: true,
            best_confidence: 0.62,
            explanation: "Similar symptom profile: both list Ectopic ossification in muscle tissue. Similar experience, possibly different cause.",
          }),
          // On the map, but the link to an off-map disease is not: nothing to draw.
          coreItem("MONDO:9900003", ["e_core_fop_scn2a"], { inferred: true, best_confidence: 0.46, explanation: "Both list Hearing impairment." }),
        ],
      },
      { key: "genes", node_type: "gene", total: 1, items: [coreItem(CORE.acvr1, [CORE.fopGeneEdge], { best_confidence: 0.99 })] },
      {
        key: "symptoms",
        node_type: "phenotype",
        total: 52,
        // The summary's own order (not by frequency); the panel sorts by frequency.
        items: FOP_SYMPTOMS.map(([edge, hp]) => coreItem(hp, [edge], { best_confidence: 0.99 })),
      },
    ],
    explain_edge_ids: [CORE.fopGeneEdge, "e_core_fop_ossif"],
    vus_notice: null,
    data_version: "fixture",
    coverage: "core",
    focus_disease_count: FOCUS_DISEASE_COUNT,
  };
}

/** `GET /neighborhood/MONDO:0007606`: the direct edges, with frequencies on the symptom links. */
export function coreNeighborhood() {
  const center = coreApiNode(coreById.get(CORE.fop)!);
  const edge = (id: string, target: string, relation: string, family: string, features: Record<string, unknown> | null) => ({
    id, source_id: CORE.fop, target_id: target, relation, family, confidence: 0.99, confidence_level: "high", origin: "observed",
    status: "active", features, data_version: "fixture", evidence_count: 2, contradiction_count: 0, flagged: false, explanation: null,
  });
  return {
    center,
    nodes: [center, ...[CORE.acvr1, ...FOP_SYMPTOMS.map((s) => s[1])].map((id) => coreApiNode(coreById.get(id)!))],
    edges: [
      edge(CORE.fopGeneEdge, CORE.acvr1, "caused_by_variant_in", "dna", null),
      ...FOP_SYMPTOMS.map(([id, hp, frequency, label]) =>
        edge(id, hp, "has_phenotype", "symptoms", { frequency, frequency_label: label, frequency_by_source: { hpo: frequency } }),
      ),
    ],
    cluster: null,
    hints: HINTS.guest,
    data_version: "fixture",
  };
}

/** `GET /edge/e_core_fop_acvr1/evidence`: the gene link, from Orphanet and HPO. */
export function coreGeneEvidence() {
  const ev = (id: number, source_type: string, source_id: string, url: string) => ({
    id, edge_id: CORE.fopGeneEdge, tier: "curated_db", tier_weight: 0.9, source_type, source_id, url,
    quote: null, retrieved_at: "2026-10-04T00:00:00Z", polarity: "supports", claim_type: null,
  });
  return {
    edge: coreNeighborhood().edges[0],
    source: coreApiNode(coreById.get(CORE.fop)!),
    target: coreApiNode(coreById.get(CORE.acvr1)!),
    supporting: [
      ev(1, "orphanet", "ORPHA:337", "https://www.orpha.net/en/disease/detail/337"),
      ev(2, "hpo", "OMIM:135100", "https://omim.org/entry/135100"),
      ev(3, "orphanet", "ORPHA:337", "https://www.orpha.net/en/disease/detail/337"),
    ],
    contradicting: [],
    confidence_breakdown: { supporting: [], support_score: 0.99, n_contradicting: 0, penalty_per_contradiction: 0.1, penalty: 0, result: 0.99, level: "high", formula: "" },
    open_flags: 0,
  };
}

/** `GET /node/{id}` for a core node (the dock labels off-map finds with it). */
export function coreNodeDetail(id: string) {
  const n = coreById.get(id);
  if (!n) return null;
  return { node: coreApiNode(n), synonyms: [], summary: null, relation_counts: [], degree: 0, cluster: null, classification: null, vus_notice: null };
}

/**
 * `graphMocks` plus the core nodes: their summaries, node details, FOP's
 * neighbourhood and gene evidence, and `GET /search` hits for "FOP".
 */
export function wideMocks(extra: Record<string, unknown> = {}) {
  const base = graphMocks();
  const lastSegment = (url: string) => decodeURIComponent(new URL(url).pathname.split("/").pop()!);
  const delegate = (key: keyof typeof base) => base[key] as (req: { url: string }) => unknown;
  return {
    ...base,
    "GET /search": ({ url }: { url: string }) => {
      const q = (new URL(url).searchParams.get("q") ?? "").toLowerCase();
      const results =
        q === "fop" || q.startsWith("fibro")
          ? [
              { id: CORE.fop, type: "disease", label: coreById.get(CORE.fop)!.label, matched_synonym: q === "fop" ? "FOP" : null, score: 3, match_kind: "exact", cluster_id: null },
              { id: CORE.acvr1, type: "gene", label: "ACVR1", matched_synonym: null, score: 1, match_kind: "trigram", cluster_id: null },
            ]
          : [];
      return { json: { results } };
    },
    "GET /atlas/summary/*": summaryMock({
      [CORE.fop]: { json: coreDiseaseSummary() },
      "MONDO:0011989": {
        json: {
          ...coreDiseaseSummary(),
          node: coreApiNode(coreById.get("MONDO:0011989")!),
          headline: "A rare genetic condition. Linked to 1 similar condition in the atlas.",
          sections: [{ key: "similar_diseases", node_type: "disease", total: 1, items: [coreItem(CORE.fop, ["e_core_fop_poh"], { inferred: true, best_confidence: 0.62 })] }],
          explain_edge_ids: [],
        },
      },
      [CORE.pcd]: {
        json: {
          ...coreDiseaseSummary(),
          node: coreApiNode(coreById.get(CORE.pcd)!),
          headline: "A rare genetic condition. Linked to 1 gene in the atlas.",
          sections: [{ key: "symptoms", node_type: "phenotype", total: 1, items: [coreItem("HP:0034315", ["e_core_pcd_cough"])] }],
          explain_edge_ids: [],
        },
      },
    }),
    "GET /node/*": ({ url }: { url: string }) => {
      const d = coreNodeDetail(lastSegment(url));
      return d ? { json: d } : delegate("GET /node/*")({ url });
    },
    "GET /neighborhood/*": ({ url }: { url: string }) =>
      lastSegment(url) === CORE.fop ? { json: coreNeighborhood() } : delegate("GET /neighborhood/*")({ url }),
    "GET /edge/*/evidence": ({ url }: { url: string }) =>
      url.includes(CORE.fopGeneEdge) ? { json: coreGeneEvidence() } : delegate("GET /edge/*/evidence")({ url }),
    ...extra,
  };
}

/** `POST /explain` SSE events: two deltas, then the final event. */
export function explainEvents(text: string, cached: boolean) {
  const mid = Math.floor(text.length / 2);
  return [
    { type: "delta", text: text.slice(0, mid) },
    { type: "delta", text: text.slice(mid) },
    { type: "final", path_id: "p_fixture", text, citations: ["e_e5f778ac8a21"], cached, role: "patient", language: "en", data_version: "fixture" },
  ];
}

/** Mock table for every graph read endpoint. Role is read from `?role=`. */
export function graphMocks(extra: Record<string, unknown> = {}) {
  const lastSegment = (url: string) => decodeURIComponent(new URL(url).pathname.split("/").pop()!);
  return {
    "GET /auth/session": { user: null, gpc: false, demo_mode: false, data_version: "fixture" },
    "GET /atlas.json": atlasPayload(),
    "GET /atlas/tree.json": atlasTreePayload(),
    "GET /atlas/summary/*": summaryMock(),
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

/**
 * Synthetic large `GET /atlas/tree.json`: `entities` entities spread over the
 * nine categories, each category split into fields and then into
 * alphabetical ranges of at most 10 (about 7,000 tree nodes for the
 * default), and `edges` random real edges between entities. Plus a
 * `/atlas/summary/*` handler for its ids.
 */
export function largeAtlasTree(entities = 6343, edges = 17000) {
  let seed = 42;
  const rand = () => (seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296;
  const typesOf: Record<string, string[]> = {
    researchers: ["researcher"],
    institutions: ["institution"],
    literature: ["paper", "trial", "grant"],
    community: ["patient_org", "registry"],
    pathways: ["pathway"],
    genes: ["gene", "variant"],
    diseases: ["disease"],
    symptoms: ["phenotype"],
    doctors: ["doctor"],
  };
  const share = [1333, 1294, 1241, 36, 660, 805, 177, 642, 155];
  const shareTotal = share.reduce((s, v) => s + v, 0);
  const perCat = share.map((v) => Math.max(10, Math.round((v / shareTotal) * entities)));
  perCat[0] += entities - perCat.reduce((s, v) => s + v, 0);

  const nodes: FxTreeNode[] = [];
  const base = (o: Partial<FxTreeNode> & Pick<FxTreeNode, "id" | "kind" | "label" | "x" | "y" | "angle">): FxTreeNode => ({
    parent_id: null, category: null, depth: 0, entity_type: null, group_basis: null, ref_id: null,
    entity_count: 0, child_count: 0, cluster_id: null, centrality: null, contributed: false, ...o,
  });
  const polar = (r: number, a: number) => ({ x: +(r * Math.cos(a)).toFixed(2), y: +(r * Math.sin(a)).toFixed(2), angle: +a.toFixed(5) });
  nodes.push(base({ id: "T:root", kind: "root", label: "Atlas", x: 0, y: 0, angle: 0, entity_count: entities, child_count: 9 }));
  const gap = (3 * Math.PI) / 180;
  const usable = 2 * Math.PI - gap * 9;
  const spans = perCat.map((n) => Math.max((14 * Math.PI) / 180, (usable * n) / entities));
  const k = usable / spans.reduce((s, v) => s + v, 0);
  const categories: Array<Record<string, unknown>> = [];
  const entityIds: string[] = [];
  let start = Math.PI / 2;
  let serial = 0;
  CATEGORY_ORDER.forEach((cat, ci) => {
    const span = spans[ci] * k;
    const end = start - span;
    const n = perCat[ci];
    const catId = `T:${cat}`;
    const fields = Math.max(1, Math.min(12, Math.round(n / 60)));
    nodes.push(base({ id: catId, kind: "category", label: CATEGORY_LABELS[cat], parent_id: "T:root", category: cat, depth: 1, ...polar(180, (start + end) / 2), entity_count: n, child_count: fields }));
    let done = 0;
    for (let f = 0; f < fields; f++) {
      const inField = Math.floor(n / fields) + (f < n % fields ? 1 : 0);
      const f0 = start - (span * done) / n;
      const f1 = start - (span * (done + inField)) / n;
      const fieldId = `${catId}/f${f}`;
      const ranges = Math.ceil(inField / 10);
      nodes.push(base({ id: fieldId, kind: "group", label: `Field ${f + 1}`, parent_id: catId, category: cat, depth: 2, ...polar(320, (f0 + f1) / 2), group_basis: "research_field", entity_count: inField, child_count: ranges }));
      for (let r = 0; r < ranges; r++) {
        const inRange = Math.min(10, inField - r * 10);
        const r0 = f0 + ((f1 - f0) * r * 10) / inField;
        const r1 = f0 + ((f1 - f0) * (r * 10 + inRange)) / inField;
        const rangeId = `${fieldId}/r${r}`;
        nodes.push(base({ id: rangeId, kind: "group", label: `Range ${r + 1}`, parent_id: fieldId, category: cat, depth: 3, ...polar(460, (r0 + r1) / 2), group_basis: "alpha_range", entity_count: inRange, child_count: inRange }));
        for (let e = 0; e < inRange; e++) {
          const id = `SYN:${serial}`;
          const types = typesOf[cat];
          nodes.push(base({ id, kind: "entity", label: `Synthetic item ${serial}`, parent_id: rangeId, category: cat, depth: 4, ...polar(600 + (e % 3) * 40, r0 + ((r1 - r0) * (e + 0.5)) / inRange), entity_type: types[serial % types.length], entity_count: 1, centrality: rand() ** 3 }));
          entityIds.push(id);
          serial++;
        }
      }
      done += inField;
    }
    const mid = (start + end) / 2;
    categories.push({ id: cat, node_id: catId, label: CATEGORY_LABELS[cat], entity_count: n, angle_start: start, angle_end: end, label_x: +(820 * Math.cos(mid)).toFixed(2), label_y: +(820 * Math.sin(mid)).toFixed(2) });
    start = end - gap;
  });

  const families = ["dna", "symptoms", "research", "community"];
  const origins = ["observed", "observed", "observed", "inferred", "patient_reported"];
  const realEdges = Array.from({ length: edges }, (_, i) => {
    const s = Math.floor(rand() * entityIds.length);
    let t = Math.floor(rand() * entityIds.length);
    if (t === s) t = (s + 1) % entityIds.length;
    return {
      id: `e_syn${i}`,
      source: entityIds[s],
      target: entityIds[t],
      relation: "similar_symptoms",
      family: families[i % 4],
      confidence: rand(),
      origin: origins[i % origins.length],
      status: i % 997 === 0 ? "under_review" : "active",
    };
  });
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const summary = ({ url }: { url: string }) => {
    const id = decodeURIComponent(new URL(url).pathname.split("/").pop()!);
    const n = byId.get(id);
    if (!n || n.kind !== "entity") return { status: 404, json: { error: { code: "not_found", message: "Not found" } } };
    return {
      json: {
        node: { id, type: n.entity_type, label: n.label, description: null, url: null, attrs: {}, cluster_id: null, x: n.x, y: n.y, centrality: n.centrality },
        tree_path: [],
        headline: `${n.label} in the atlas.`,
        sections: [],
        explain_edge_ids: [],
        vus_notice: null,
        data_version: "synthetic",
      },
    };
  };
  return {
    tree: { data_version: "synthetic", layout_version: 4, root_id: "T:root", categories, nodes, edges: realEdges, clusters: [] },
    summary,
  };
}

/** `GET /stats`: headline counts (the landing page's counts line). */
export function statsPayload() {
  return { data_version: "fixture", diseases: 168, genes: 125, symptoms: 769, links_cited: 15553, links_computed: 2176 };
}
