/**
 * Realistic chat mocks for the STXBP1 demo journey, built on the backend's
 * hand-written fixture graph (apps/backend/src/backend/fixtures/demo_graph.json)
 * so edge and node IDs, relations, origins and evidence match the API.
 */
import { readFileSync } from "node:fs";
import path from "node:path";

import { sseBody } from "../helpers";

type FxEvidence = Record<string, unknown> & { polarity: string; tier: string };
type FxEdge = {
  id: string;
  source_id: string;
  target_id: string;
  relation: string;
  family: string;
  confidence: number;
  origin: string;
  status: string;
  features: unknown;
  evidence: FxEvidence[];
};
type FxNode = { id: string; type: string; label: string; description?: string; url?: string; attrs?: Record<string, unknown> };

const graph = JSON.parse(
  readFileSync(path.resolve(__dirname, "../../../backend/src/backend/fixtures/demo_graph.json"), "utf8"),
) as { nodes: FxNode[]; edges: FxEdge[] };

const nodes = new Map(graph.nodes.map((n) => [n.id, n]));
const edges = new Map(graph.edges.map((e) => [e.id, e]));

const level = (c: number) => (c >= 0.8 ? "high" : c >= 0.5 ? "medium" : "low");
const apiNode = (n: FxNode) => ({ attrs: {}, ...n });

export function edgeEvidence(id: string) {
  const e = edges.get(id);
  if (!e) return null;
  const ev = e.evidence.map((x, i) => ({ id: i + 1, edge_id: id, tier_weight: 0.5, ...x }));
  return {
    edge: {
      ...e,
      evidence: undefined,
      confidence_level: level(e.confidence),
      evidence_count: ev.length,
      contradiction_count: ev.filter((x) => x.polarity === "contradicts").length,
    },
    source: apiNode(nodes.get(e.source_id)!),
    target: apiNode(nodes.get(e.target_id)!),
    supporting: ev.filter((x) => x.polarity === "supports"),
    contradicting: ev.filter((x) => x.polarity === "contradicts"),
    confidence_breakdown: { score: e.confidence, terms: [] },
  };
}

export function nodeDetail(id: string) {
  const n = nodes.get(id);
  if (!n) return null;
  const classification = (n.attrs?.classification as string | undefined) ?? null;
  return {
    node: apiNode(n),
    synonyms: [],
    summary: n.description ?? null,
    classification,
    vus_notice:
      classification === "uncertain_significance"
        ? "This result is uncertain. Discuss it with a genetic counselor before acting on it."
        : null,
  };
}

/** Graph endpoints answered from the fixture graph. */
export const graphMocks = {
  "GET /edge/*/evidence": (req: { url: string }) => {
    const id = decodeURIComponent(new URL(req.url).pathname.split("/")[2]);
    const data = edgeEvidence(id);
    return data ? { json: data } : { status: 404, json: { error: { code: "not_found", message: "Not found" } } };
  },
  "GET /node/*": (req: { url: string }) => {
    const id = decodeURIComponent(new URL(req.url).pathname.split("/")[2]);
    const data = nodeDetail(id);
    return data ? { json: data } : { status: 404, json: { error: { code: "not_found", message: "Not found" } } };
  },
};

export const STORY =
  "My daughter is 2, diagnosed with STXBP1 last month. Lots of seizures, not walking yet, no problems with eating.";

export const SESSION_ID = "11111111-1111-4111-8111-111111111111";

export const chips = [
  { type: "disease", id: "MONDO:9900007", label: "STXBP1 encephalopathy", negated: false, confirmed: false },
  { type: "gene", id: "HGNC:11444", label: "STXBP1", negated: false, confirmed: false },
  { type: "symptom", id: "HP:0001250", label: "Seizure", negated: false, confirmed: false },
  { type: "symptom", id: "HP:0001263", label: "Global developmental delay", negated: false, confirmed: false },
  { type: "symptom", id: "HP:0011968", label: "Feeding difficulties", negated: true, confirmed: false },
  { type: "variant", id: "CLINVAR:FX0004", label: "STXBP1 missense variant", negated: false, confirmed: false },
];

export const claims = [
  {
    text: "Children with early-onset SCN2A encephalopathy have many of the same symptoms as children with STXBP1 encephalopathy.",
    edge_ids: ["e_3b8845b635b8"],
    origin: "inferred",
    confidence: "high",
  },
  {
    text: "The SCN2A Community Alliance supports families with early-onset SCN2A encephalopathy.",
    edge_ids: ["e_0af807385728"],
    origin: "observed",
    confidence: "high",
  },
  {
    text: "The same group runs the Sodium Channel Epilepsy Registry.",
    edge_ids: ["e_558f7d2a940d"],
    origin: "observed",
    confidence: "high",
  },
];

export const contradictions = [
  {
    claim_index: 0,
    edge_ids: ["e_9a6ff6e0e247"],
    note: "In later-onset SCN2A disorder, seizures are only occasional.",
  },
];

export const reply = {
  summary:
    "STXBP1 encephalopathy and early-onset SCN2A encephalopathy share many symptoms, possibly from a different cause. An SCN2A patient group runs a registry that families like yours could join.",
  uncertainty: null,
  chips,
  claims,
  contradictions,
  missing_evidence: ["No source links STXBP1 to SYNGAP1 through a shared pathway; a functional study would close this gap."],
  cards: [
    {
      type: "mini_graph",
      node_ids: ["MONDO:9900007", "MONDO:9900003", "ORG:fx-scn2a-community", "REG:fx-sodium-channel-registry"],
      edge_ids: ["e_3b8845b635b8", "e_0af807385728", "e_558f7d2a940d", "e_275854103db5"],
    },
    { type: "patient_group", node_ids: ["ORG:fx-stxbp1-parents", "ORG:fx-scn2a-community"], edge_ids: ["e_0af807385728"] },
    { type: "evidence", node_ids: [], edge_ids: ["e_3b8845b635b8"] },
    { type: "open_in_atlas", node_ids: ["MONDO:9900007"], edge_ids: [] },
  ],
  graph_focus: { node_ids: ["MONDO:9900007"], highlight_path: ["e_3b8845b635b8", "e_0af807385728", "e_558f7d2a940d"] },
  actions: [
    {
      title: "Join the Sodium Channel Epilepsy Registry instead of building a new one",
      type: "reuse_asset",
      viable: true,
      edge_ids: ["e_0af807385728", "e_558f7d2a940d"],
      timeline_today: "2 to 3 years to set up an STXBP1 registry",
      timeline_proposed: "Enrol within 3 months",
      assumptions: ["The registry accepts related conditions", "Consent forms can be shared"],
    },
    {
      title: "Ask SYNGAP1 researchers about a shared pathway study",
      type: "contact",
      viable: false,
      edge_ids: ["e_275854103db5"],
      timeline_today: null,
      timeline_proposed: null,
      assumptions: ["The shared pathway is real (currently a hypothesis)"],
    },
  ],
  follow_up: {
    question: "Did the seizures start in the first weeks of life?",
    quick_replies: ["Yes, in the first weeks", "Later than that"],
    skippable: true,
  },
  ai_notice: null,
  gap_search: null,
  kind: "answer",
};

export function fullTurnEvents(r: Record<string, unknown> = reply) {
  const summary = r.summary as string;
  const mid = Math.floor(summary.length / 2);
  return [
    { type: "status", tool: "extract_entities", message: "Reading what you described" },
    { type: "status", tool: "resolve_to_ids", message: "Matching it to the atlas" },
    { type: "status", tool: "find_path", message: "Finding the most trustworthy connections" },
    // Like the API: the one-line uncertainty statement comes before any summary text.
    ...(r.uncertainty ? [{ type: "uncertainty", text: r.uncertainty }] : []),
    { type: "summary_delta", text: summary.slice(0, mid) },
    { type: "summary_delta", text: summary.slice(mid) },
    { type: "chips", chips: r.chips },
    { type: "claims", claims: r.claims, contradictions: r.contradictions },
    { type: "cards", cards: r.cards },
    { type: "actions", actions: r.actions },
    ...(r.follow_up ? [{ type: "follow_up", follow_up: r.follow_up }] : []),
    { type: "final", reply: r, session_id: SESSION_ID, message_id: "22222222-2222-4222-8222-222222222222" },
  ];
}

export const turnBody = (r: Record<string, unknown> = reply) => sseBody(fullTurnEvents(r));

export function emptyReply(summary: string, extra: Record<string, unknown> = {}) {
  return {
    summary,
    uncertainty: null,
    chips: [],
    claims: [],
    contradictions: [],
    missing_evidence: [],
    cards: [],
    graph_focus: null,
    actions: [],
    follow_up: null,
    ...extra,
  };
}
