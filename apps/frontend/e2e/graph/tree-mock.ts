/**
 * A small Atlas tree over the backend demo graph for the search and outline
 * specs, until the shared tree fixtures land in fixtures.ts: categories →
 * (diseases: clusters → diseases; symptoms: "Seizure" → its kinds; genes: a
 * chromosome group → genes → variants) → entities.
 */
import { fixture, graphMocks } from "./fixtures";

const CATEGORY_OF: Record<string, string> = {
  researcher: "researchers", institution: "institutions", paper: "literature", trial: "literature",
  grant: "literature", claim: "literature", patient_org: "community", registry: "community",
  network: "community", pathway: "pathways", gene: "genes", variant: "genes", mechanism: "genes",
  disease: "diseases", cluster: "diseases", phenotype: "symptoms", doctor: "doctors",
};
const ORDER = ["researchers", "institutions", "literature", "community", "pathways", "genes", "diseases", "symptoms", "doctors"];
const SEIZURE_KINDS = new Set(["HP:0002373", "HP:0012469", "HP:0002133"]);

type N = {
  id: string;
  kind: string;
  label: string;
  parent_id: string | null;
  category: string | null;
  entity_type: string | null;
  group_basis: string | null;
  cluster_id: string | null;
  centrality: number | null;
};

export function miniTree() {
  const nodes: N[] = [];
  const node = (n: Partial<N> & Pick<N, "id" | "kind" | "label" | "parent_id">) =>
    nodes.push({ category: null, entity_type: null, group_basis: null, cluster_id: null, centrality: null, ...n });
  node({ id: "T:root", kind: "root", label: "Amber", parent_id: null });
  for (const c of ORDER) node({ id: `T:${c}`, kind: "category", label: c, parent_id: "T:root", category: c });
  node({ id: "T:genes/chr2", kind: "group", label: "Chromosome 2", parent_id: "T:genes", category: "genes", group_basis: "chromosome" });
  const variantGene = new Map(fixture.edges.filter((e) => e.relation === "variant_of").map((e) => [e.source_id, e.target_id]));
  for (const n of fixture.nodes) {
    const category = CATEGORY_OF[n.type];
    let parent = `T:${category}`;
    if (n.type === "disease" && n.cluster_id) parent = n.cluster_id;
    if (n.type === "gene") parent = "T:genes/chr2";
    if (n.type === "variant" && variantGene.has(n.id)) parent = variantGene.get(n.id)!;
    if (SEIZURE_KINDS.has(n.id)) parent = "HP:0001250";
    node({ id: n.id, kind: "entity", label: n.label, parent_id: parent, category, entity_type: n.type, cluster_id: n.cluster_id, centrality: n.centrality });
  }

  const byId = new Map(nodes.map((n) => [n.id, n]));
  const kids = new Map<string, N[]>();
  for (const n of nodes) if (n.parent_id) kids.set(n.parent_id, [...(kids.get(n.parent_id) ?? []), n]);
  const count = (id: string): number =>
    (kids.get(id) ?? []).reduce((s, k) => s + count(k.id), byId.get(id)!.kind === "entity" ? 1 : 0);

  // Pre-order with simple radial positions (parents before children).
  const out: Record<string, unknown>[] = [];
  const walk = (n: N, depth: number, a0: number, a1: number) => {
    const angle = (a0 + a1) / 2;
    const r = depth === 0 ? 0 : 180 + (depth - 1) * 140;
    const children = kids.get(n.id) ?? [];
    out.push({
      ...n, depth, angle, x: Math.cos(angle) * r, y: Math.sin(angle) * r, ref_id: null,
      entity_count: count(n.id), child_count: children.length, contributed: false,
    });
    const step = (a1 - a0) / Math.max(1, children.length);
    children.forEach((k, i) => walk(k, depth + 1, a0 + step * i, a0 + step * (i + 1)));
  };
  const span = (2 * Math.PI) / ORDER.length;
  const start = (i: number) => Math.PI / 2 - i * span;
  out.push({ ...byId.get("T:root")!, depth: 0, angle: 0, x: 0, y: 0, ref_id: null, entity_count: count("T:root"), child_count: ORDER.length, contributed: false });
  ORDER.forEach((c, i) => walk(byId.get(`T:${c}`)!, 1, start(i) - span * 0.9, start(i)));

  return {
    data_version: "fixture",
    layout_version: 1,
    root_id: "T:root",
    categories: ORDER.map((c, i) => ({
      id: c,
      node_id: `T:${c}`,
      label: c,
      entity_count: count(`T:${c}`),
      angle_start: start(i),
      angle_end: start(i) - span * 0.9,
      label_x: Math.cos(start(i) - span * 0.45) * 700,
      label_y: Math.sin(start(i) - span * 0.45) * 700,
    })),
    nodes: out,
    edges: fixture.edges.map((e) => ({
      id: e.id, source: e.source_id, target: e.target_id, relation: e.relation,
      family: e.family, confidence: e.confidence, origin: e.origin, status: e.status,
    })),
    clusters: fixture.clusters.map((c) => ({ ...c, origin: "inferred" })),
  };
}

/** Graph mocks plus the mini tree; summaries 404 (panels are not under test here). */
export function treeMocks(extra: Record<string, unknown> = {}) {
  return graphMocks({
    "GET /atlas/tree.json": miniTree(),
    "GET /atlas/summary/*": { status: 404, json: { error: { code: "not_found", message: "Not found" } } },
    ...extra,
  });
}
