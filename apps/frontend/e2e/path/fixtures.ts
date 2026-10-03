/**
 * Payloads for /path tests, modelled on apps/backend/src/backend/fixtures/demo_graph.json
 * (the cached demo path STXBP1 → SCN2A DEE → patient group → registry, and
 * the unsupported pair SYNGAP1 ↔ Dravet).
 */
import { mockApi, signedInSession, guestSession, sseBody } from "../helpers";
import type { Page } from "@playwright/test";

export const N = {
  stxbp1: { id: "MONDO:9900007", type: "disease", label: "STXBP1 encephalopathy", description: "Early-onset epilepsy and developmental delay caused by STXBP1 variants.", url: null, attrs: {} },
  scn2a: { id: "MONDO:9900003", type: "disease", label: "SCN2A developmental and epileptic encephalopathy (early onset)", description: "Neonatal or early-infantile seizures with SCN2A gain-of-function variants.", url: null, attrs: {} },
  org: { id: "ORG:fx-scn2a-community", type: "patient_org", label: "SCN2A Community Alliance (fixture)", description: null, url: null, attrs: {} },
  registry: { id: "REG:fx-sodium-channel-registry", type: "registry", label: "Sodium Channel Epilepsy Registry (fixture)", description: null, url: null, attrs: {} },
  seizure: { id: "HP:0001250", type: "phenotype", label: "Seizure", description: null, url: "https://hpo.jax.org/browse/term/HP:0001250", attrs: {} },
  syngap1: { id: "MONDO:9900010", type: "disease", label: "SYNGAP1-related intellectual disability", description: null, url: null, attrs: {} },
  syngap1Gene: { id: "HGNC:99000001", type: "gene", label: "SYNGAP1", description: null, url: null, attrs: {} },
  dravet: { id: "MONDO:0100135", type: "disease", label: "Dravet syndrome", description: null, url: null, attrs: {} },
} as const;

type Node = (typeof N)[keyof typeof N];

function edge(
  id: string,
  source: Node,
  target: Node,
  relation: string,
  family: string,
  confidence: number,
  extra: Record<string, unknown> = {},
) {
  return {
    id,
    source_id: source.id,
    target_id: target.id,
    relation,
    family,
    confidence,
    confidence_level: confidence >= 0.8 ? "high" : confidence >= 0.5 ? "medium" : "low",
    origin: "observed",
    status: "active",
    features: null,
    data_version: "fixture",
    evidence_count: 1,
    contradiction_count: 0,
    flagged: false,
    ...extra,
  };
}

export const E = {
  similar: edge("e_3b8845b635b8", N.scn2a, N.stxbp1, "similar_symptoms", "symptoms", 0.9, {
    origin: "inferred",
    features: { shared_hpo: ["HP:0001250", "HP:0001263"], bma_similarity: 0.74 },
  }),
  serves: edge("e_0af807385728", N.org, N.scn2a, "serves", "community", 0.9),
  runs: edge("e_558f7d2a940d", N.org, N.registry, "runs", "community", 0.9),
  stxSeizure: edge("e_bbb03f09d0fa", N.stxbp1, N.seizure, "has_phenotype", "symptoms", 0.9, { evidence_count: 2 }),
  scnSeizure: edge("e_9a6ff6e0e247", N.scn2a, N.seizure, "has_phenotype", "symptoms", 0.87, {
    evidence_count: 3,
    contradiction_count: 1,
  }),
  lowPathway: edge("e_275854103db5", N.stxbp1, N.syngap1, "shared_pathway", "dna", 0.3, { origin: "inferred" }),
};

function step(e: ReturnType<typeof edge>, from: Node, to: Node) {
  return { edge: e, from_node: from, to_node: to, reversed: e.source_id !== from.id };
}

export const demoPath = {
  path_id: "p_ec8907fa38b0b33d",
  steps: [step(E.similar, N.stxbp1, N.scn2a), step(E.serves, N.scn2a, N.org), step(E.runs, N.org, N.registry)],
  edge_ids: [E.similar.id, E.serves.id, E.runs.id],
  total_cost: 0.316,
  min_confidence: 0.9,
  min_confidence_level: "high",
  all_observed: false,
  all_active: true,
  supported: true,
};

export const altPath = {
  path_id: "p_0000000000000002",
  steps: [
    step(E.stxSeizure, N.stxbp1, N.seizure),
    step(E.scnSeizure, N.seizure, N.scn2a),
    step(E.serves, N.scn2a, N.org),
    step(E.runs, N.org, N.registry),
  ],
  edge_ids: [E.stxSeizure.id, E.scnSeizure.id, E.serves.id, E.runs.id],
  total_cost: 0.455,
  min_confidence: 0.87,
  min_confidence_level: "high",
  all_observed: true,
  all_active: true,
  supported: true,
};

export const okResponse = {
  status: "ok",
  from_id: N.stxbp1.id,
  to_id: N.registry.id,
  family: "all",
  threshold: 0.6,
  paths: [demoPath, altPath],
  coverage: null,
};

export const noRouteResponse = {
  status: "no_supported_route",
  from_id: N.syngap1.id,
  to_id: N.dravet.id,
  family: "all",
  threshold: 0.6,
  paths: [],
  coverage: {
    sources_queried: [
      { source: "ClinVar", count: 12 },
      { source: "HPO", count: 31 },
      { source: "PubMed", count: 4 },
      { source: "Reactome", count: 0 },
    ],
    closest_partial_path: {
      path_id: "p_partial000000001",
      steps: [step(E.lowPathway, N.syngap1, N.stxbp1)],
      edge_ids: [E.lowPathway.id],
      total_cost: 1.2,
      min_confidence: 0.3,
      min_confidence_level: "low",
      all_observed: false,
      all_active: true,
      supported: false,
    },
    missing_link: {
      from_id: N.stxbp1.id,
      to_id: N.dravet.id,
      description: "No source links STXBP1 encephalopathy to Dravet syndrome; a shared-mechanism study would close this gap.",
    },
    suggested_question: "Do SYNGAP1 and SCN1A variants affect the same synaptic pathway?",
  },
};

export function evidenceFor(edgeId: string) {
  const all = [...demoPath.steps, ...altPath.steps, ...noRouteResponse.coverage.closest_partial_path.steps];
  const s = all.find((x) => x.edge.id === edgeId)!;
  const contradicted = edgeId === E.scnSeizure.id;
  const supporting = [
    {
      id: 1,
      edge_id: edgeId,
      tier: "peer_reviewed",
      tier_weight: 0.7,
      source_type: "PubMed",
      source_id: "PMID:12345678",
      url: "https://pubmed.ncbi.nlm.nih.gov/12345678/",
      quote: "Seizures were observed in most patients with early-onset disease.",
      retrieved_at: "2026-10-03T00:00:00Z",
      polarity: "supports",
      claim_type: "experimental",
    },
    {
      id: 2,
      edge_id: edgeId,
      tier: "curated_db",
      tier_weight: 0.9,
      source_type: "HPO",
      source_id: "HPOA",
      url: null,
      quote: null,
      retrieved_at: "2026-10-02T00:00:00Z",
      polarity: "supports",
      claim_type: null,
    },
  ];
  const contradicting = contradicted
    ? [
        {
          id: 3,
          edge_id: edgeId,
          tier: "review",
          tier_weight: 0.5,
          source_type: "PubMed",
          source_id: "PMID:87654321",
          url: "https://pubmed.ncbi.nlm.nih.gov/87654321/",
          quote: "Seizures are not a universal feature of later-onset SCN2A disorders.",
          retrieved_at: "2026-10-03T00:00:00Z",
          polarity: "contradicts",
          claim_type: "review",
        },
      ]
    : [];
  return {
    edge: s.edge,
    source: s.reversed ? s.to_node : s.from_node,
    target: s.reversed ? s.from_node : s.to_node,
    supporting,
    contradicting,
    confidence_breakdown: {
      supporting: [
        { evidence_id: 1, tier: "peer_reviewed", weight: 0.7 },
        { evidence_id: 2, tier: "curated_db", weight: 0.9 },
      ],
      support_score: 0.97,
      n_contradicting: contradicting.length,
      penalty_per_contradiction: 0.1,
      penalty: 0.1 * contradicting.length,
      result: s.edge.confidence,
      level: s.edge.confidence_level,
      formula: `1 - (1-0.7)(1-0.9) - 0.1×${contradicting.length} = ${s.edge.confidence}`,
    },
    open_flags: 0,
  };
}

export const cachedExplanation = [
  { type: "delta", text: "Your child's condition shares many symptoms with early-onset SCN2A encephalopathy " },
  { type: "delta", text: "[e_3b8845b635b8]. The SCN2A Community Alliance supports these families [e_0af807385728] and runs a registry [e_558f7d2a940d]." },
  {
    type: "final",
    path_id: demoPath.path_id,
    text: "Your child's condition shares many symptoms with early-onset SCN2A encephalopathy [e_3b8845b635b8]. The SCN2A Community Alliance supports these families [e_0af807385728] and runs a registry [e_558f7d2a940d].",
    citations: [E.similar.id, E.serves.id, E.runs.id],
    cached: true,
    reading_grade: 6.1,
    role: "guest",
    language: "en",
    data_version: "fixture",
  },
];

export const searchHits = [
  { id: N.stxbp1.id, type: "disease", label: N.stxbp1.label, matched_synonym: "STXBP1-DEE", score: 1, match_kind: "exact" },
  { id: N.registry.id, type: "registry", label: N.registry.label, matched_synonym: null, score: 0.9, match_kind: "trigram" },
  { id: N.dravet.id, type: "disease", label: N.dravet.label, matched_synonym: "Severe myoclonic epilepsy of infancy", score: 0.8, match_kind: "trigram" },
];

export function nodeDetail(id: string) {
  const n = Object.values(N).find((x) => x.id === id);
  return n ? { json: { node: n, synonyms: [], degree: 3 } } : { status: 404, json: { error: { code: "not_found", message: "Not found" } } };
}

export const DEMO_URL = `/path?from=${encodeURIComponent(N.stxbp1.id)}&to=${encodeURIComponent(N.registry.id)}`;
export const NO_ROUTE_URL = `/path?from=${encodeURIComponent(N.syngap1.id)}&to=${encodeURIComponent(N.dravet.id)}`;

/** Standard mocks; override any key. */
export async function mockPathApi(page: Page, overrides: Record<string, unknown> = {}, { signedIn = false } = {}) {
  await mockApi(page, {
    "GET /auth/session": signedIn ? signedInSession({ role: "patient" }) : guestSession,
    "GET /search": { results: searchHits },
    "GET /node/*": (req: { url: string }) => nodeDetail(decodeURIComponent(new URL(req.url).pathname.split("/").pop()!)),
    "GET /path": (req: { url: string }) => {
      const u = new URL(req.url);
      return { json: u.searchParams.get("from") === N.syngap1.id ? noRouteResponse : okResponse };
    },
    "GET /edge/*/evidence": (req: { url: string }) => ({ json: evidenceFor(new URL(req.url).pathname.split("/")[2]) }),
    "POST /explain": sseBody(cachedExplanation),
    "GET /neighborhood/*": { center: N.stxbp1, nodes: [N.stxbp1, N.scn2a, N.registry, N.org], edges: [], hints: { start_layout: "ring", label_style: "plain" } },
    ...overrides,
  });
}

/**
 * Screenshot that lets Motion's reveal finish (the shared `shot` disables
 * animations, which cuts the step reveal short in Chromium).
 */
export async function pathShot(page: Page, name: string, { fullPage = true } = {}) {
  await page.waitForTimeout(2200);
  await page.screenshot({ path: `e2e/screenshots/${name}.png`, fullPage });
}
