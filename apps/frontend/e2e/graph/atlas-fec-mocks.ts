/**
 * Mocks for the summary panel and Dr. Wu dock specs: a small Atlas tree and
 * `/atlas/summary/*` payloads built from the backend demo graph. Kept local
 * to these specs until the shared tree fixtures land in fixtures.ts.
 */
import { clusters, fixture } from "./fixtures";

const CATEGORY_OF: Record<string, string> = {
  researcher: "researchers", institution: "institutions", paper: "literature", trial: "literature",
  grant: "literature", claim: "literature", patient_org: "community", registry: "community",
  network: "community", pathway: "pathways", gene: "genes", variant: "genes", mechanism: "genes",
  disease: "diseases", cluster: "diseases", phenotype: "symptoms", doctor: "doctors",
};
const ORDER = ["researchers", "institutions", "literature", "community", "pathways", "genes", "diseases", "symptoms", "doctors"];

/** A group under Genes: chromosome 2 holds the genes. */
export const GENE_GROUP = "T:genes/chr-2";

type TreeNode = {
  id: string;
  kind: "root" | "category" | "group" | "entity";
  label: string;
  parent_id: string | null;
  category: string | null;
  entity_type: string | null;
  group_basis: string | null;
  ref_id: string | null;
  cluster_id: string | null;
  centrality: number | null;
};

export function fecTree() {
  const nodes: TreeNode[] = [];
  const add = (n: Partial<TreeNode> & Pick<TreeNode, "id" | "kind" | "label" | "parent_id">) =>
    nodes.push({ category: null, entity_type: null, group_basis: null, ref_id: null, cluster_id: null, centrality: null, ...n });
  add({ id: "T:root", kind: "root", label: "Atlas", parent_id: null });
  for (const c of ORDER) add({ id: `T:${c}`, kind: "category", label: c, parent_id: "T:root", category: c });
  add({ id: GENE_GROUP, kind: "group", label: "Chromosome 2", parent_id: "T:genes", category: "genes", group_basis: "chromosome", ref_id: "2" });
  // Clusters first so their diseases can hang below them.
  const sorted = [...fixture.nodes].sort((a, b) => Number(b.type === "cluster") - Number(a.type === "cluster"));
  for (const n of sorted) {
    const category = CATEGORY_OF[n.type];
    let parent = `T:${category}`;
    if (n.type === "disease" && n.cluster_id) parent = n.cluster_id;
    if (n.type === "gene") parent = GENE_GROUP;
    add({ id: n.id, kind: "entity", label: n.label, parent_id: parent, category, entity_type: n.type, cluster_id: n.cluster_id, centrality: n.centrality });
  }

  const byId = new Map(nodes.map((n) => [n.id, n]));
  const kids = new Map<string, TreeNode[]>();
  for (const n of nodes) if (n.parent_id) kids.set(n.parent_id, [...(kids.get(n.parent_id) ?? []), n]);
  const count = (id: string): number =>
    (kids.get(id) ?? []).reduce((s, k) => s + count(k.id), byId.get(id)!.kind === "entity" ? 1 : 0);

  const out: Record<string, unknown>[] = [];
  const walk = (n: TreeNode, depth: number, a0: number, a1: number) => {
    const angle = (a0 + a1) / 2;
    const r = depth === 0 ? 0 : 180 + (depth - 1) * 140;
    const children = kids.get(n.id) ?? [];
    out.push({
      ...n,
      depth,
      x: r * Math.cos(angle),
      y: r * Math.sin(angle),
      angle,
      entity_count: count(n.id),
      child_count: children.length,
      contributed: false,
    });
    const span = (a1 - a0) / Math.max(children.length, 1);
    children.forEach((c, i) => walk(c, depth + 1, a0 + i * span, a0 + (i + 1) * span));
  };
  walk(byId.get("T:root")!, 0, -Math.PI, Math.PI);

  const sector = (2 * Math.PI) / ORDER.length;
  return {
    data_version: "fixture",
    layout_version: 1,
    root_id: "T:root",
    categories: ORDER.map((c, i) => ({
      id: c,
      node_id: `T:${c}`,
      label: c,
      entity_count: count(`T:${c}`),
      angle_start: Math.PI / 2 - i * sector,
      angle_end: Math.PI / 2 - (i + 1) * sector,
      label_x: 700 * Math.cos(Math.PI / 2 - (i + 0.5) * sector),
      label_y: 700 * Math.sin(Math.PI / 2 - (i + 0.5) * sector),
    })),
    nodes: out,
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
  };
}

const nodeById = new Map(fixture.nodes.map((n) => [n.id, n]));

function item(id: string, via: string[], extra: Record<string, unknown> = {}) {
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
  const node = nodeById.get("MONDO:9900007")!;
  const { synonyms: _s, ...api } = node;
  void _s;
  return {
    node: api,
    tree_path: [
      { id: "T:root", label: "Atlas", kind: "root" },
      { id: "T:diseases", label: "diseases", kind: "category" },
      { id: "CLUSTER:3", label: "Synaptic and potassium channel encephalopathies", kind: "entity" },
    ],
    headline: "A rare genetic condition with early seizures. Linked to 2 genes and 4 researchers in the atlas.",
    sections: [
      {
        key: "clusters",
        node_type: "cluster",
        total: 1,
        items: [item("CLUSTER:3", [], { inferred: true, best_confidence: 0, via_label: "Member by analysis (hypothesis)" })],
      },
      {
        key: "similar_diseases",
        node_type: "disease",
        total: 14,
        items: [
          item("MONDO:9900003", ["e_3b8845b635b8"], { inferred: true, under_review: true, best_confidence: 0.55 }),
          item("MONDO:9900010", ["e_275854103db5"], { inferred: true, best_confidence: 0.4 }),
        ],
      },
      { key: "genes", node_type: "gene", total: 1, items: [item("HGNC:11444", ["e_e5f778ac8a21"], { best_confidence: 0.97 })] },
      {
        key: "researchers",
        node_type: "researcher",
        total: 2,
        items: [
          item("RES:fx-alpha", ["e_e5f778ac8a21", "e_0af807385728"], { score: 4, via_label: "via 4 papers" }),
          item("RES:fx-beta", ["e_e5f778ac8a21", "e_558f7d2a940d"], { score: 1, via_label: "via gene STXBP1" }),
        ],
      },
    ],
    explain_edge_ids: ["e_e5f778ac8a21", "e_3b8845b635b8"],
    vus_notice: null,
    data_version: "fixture",
  };
}

/** A small generic summary for any other entity of the demo graph. */
export function genericSummary(id: string) {
  const n = nodeById.get(id);
  if (!n) return null;
  const { synonyms: _s, ...api } = n;
  void _s;
  return { node: api, tree_path: [], headline: `${n.label} in the atlas.`, sections: [], explain_edge_ids: [], vus_notice: null, data_version: "fixture" };
}

export function summaryMock(overrides: Record<string, unknown> = {}) {
  return ({ url }: { url: string }) => {
    const id = decodeURIComponent(new URL(url).pathname.split("/").pop()!);
    if (id in overrides) return overrides[id] as Record<string, unknown>;
    const s = id === "MONDO:9900007" ? stxbp1Summary() : genericSummary(id);
    return s ? { json: s } : { status: 404, json: { error: { code: "not_found", message: "Not found" } } };
  };
}

/** Explain SSE events: deltas then final. */
export function explainEvents(text: string, cached: boolean) {
  const mid = Math.floor(text.length / 2);
  return [
    { type: "delta", text: text.slice(0, mid) },
    { type: "delta", text: text.slice(mid) },
    { type: "final", path_id: "p_fixture", text, citations: ["e_e5f778ac8a21"], cached, role: "patient", language: "en", data_version: "fixture" },
  ];
}
