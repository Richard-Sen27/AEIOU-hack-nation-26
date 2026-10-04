// The single source of the video's narration, scene lengths and the data the
// diagrams show. Read by the scenes and by scripts/generate-voiceover.ts.
// Keep this file free of imports and of TypeScript-only runtime syntax
// (enums, namespaces), so Node can run the voiceover script on it by
// stripping types.
//
// Every number and name below comes from docs/current-state.md (data version
// 2026-10-04.24) or from GET requests to the local API on 2026-10-04; the
// comment on each block says which.
//
// Rule for on-screen text: labels only (names, ids, numbers, a formula),
// never a phrase that the narration of the same scene says.

export type SceneId =
  | 'sources'
  | 'extract'
  | 'confidence'
  | 'clusters'
  | 'agent'
  | 'atlas';

export type SceneContent = {
  readonly id: SceneId;
  readonly number: number;
  readonly name: string;
  readonly narration: string;
  // Path inside public/.
  readonly voiceover: string;
  // Length of the voiceover clip in frames (30 fps), measured with ffprobe
  // and rounded up. TechnicalVideo.tsx refuses a scene shorter than
  // VOICE_DELAY + voiceFrames. Update after regenerating a clip.
  readonly voiceFrames: number;
};

// Frame at which each scene's voiceover starts.
export const VOICE_DELAY = 6;

export const SCENES = {
  sources: {
    id: 'sources',
    number: 1,
    name: 'Sources',
    narration:
      'An offline pipeline merges thirteen public sources into one typed graph, and every link keeps the records behind it.',
    voiceover: 'voiceover/01-sources.mp3',
    voiceFrames: 230,
  },
  extract: {
    id: 'extract',
    number: 2,
    name: 'Verified extraction',
    narration:
      'A model reads PubMed abstracts and quotes the sentence behind each relation. Code checks each quote word for word, and drops what the model only guessed.',
    voiceover: 'voiceover/02-extract.mp3',
    voiceFrames: 310,
  },
  confidence: {
    id: 'confidence',
    number: 3,
    name: 'Confidence',
    narration:
      'Confidence is arithmetic, not opinion. Independent sources push it up, contradictions pull it down, and a computed link is capped just below the top band.',
    voiceover: 'voiceover/03-confidence.mp3',
    voiceFrames: 311,
  },
  clusters: {
    id: 'clusters',
    number: 4,
    name: 'Clusters by mechanism',
    narration:
      'Clustering has a negative layer: when one gene acts in opposite ways, its diseases are pushed apart, and the build fails if they still meet.',
    voiceover: 'voiceover/04-clusters.mp3',
    voiceFrames: 265,
  },
  agent: {
    id: 'agent',
    number: 5,
    name: 'Checked agent',
    narration:
      'Dr. Wu is a LangGraph turn over OpenAI models with six graph tools. Before anything is shown, code deletes any claim citing an edge the tools never returned.',
    voiceover: 'voiceover/05-agent.mp3',
    voiceFrames: 335,
  },
  atlas: {
    id: 'atlas',
    number: 6,
    name: 'Atlas',
    narration:
      'The map is laid out on the server and drawn in WebGL. Solid lines are cited; dashed lines are computed.',
    voiceover: 'voiceover/06-atlas.mp3',
    voiceFrames: 230,
  },
} as const satisfies Record<SceneId, SceneContent>;

// Scene 1. current-state.md §2 "Sources" (13 public sources) and §12.
export const SOURCES = [
  'MONDO',
  'HGNC',
  'HPO',
  'Orphanet',
  'ClinGen',
  'MANE',
  'ClinVar',
  'Reactome',
  'GO',
  'PubMed',
  'ClinicalTrials.gov',
  'NIH RePORTER',
  'Patient orgs',
] as const;

export const STAGES = [
  'fetch',
  'normalize',
  'extract',
  'build',
  'analytics',
  'validate',
  'load',
] as const;

export const TOTALS = [
  {value: 31222, label: 'nodes'},
  {value: 315732, label: 'edges'},
  {value: 447668, label: 'evidence rows'},
] as const;

// Scene 2. The abstract is PMID 24434335 as fetched by the pipeline
// (apps/pipeline/data/raw/pubmed); its first sentence is the quote stored on
// edge e_da7bfb96736c (GET /edge/e_da7bfb96736c/evidence). Counts:
// current-state.md §2 "Quote verification".
export const ABSTRACT = {
  id: 'PMID:24434335',
  journal: 'Neurobiol Dis · 2014',
  title:
    'Strain- and age-dependent hippocampal neuron sodium currents correlate with epilepsy severity in Dravet syndrome mice.',
  quote:
    'Heterozygous loss-of-function SCN1A mutations cause Dravet syndrome, an epileptic encephalopathy of infancy that exhibits variable clinical severity.',
  rest: 'We utilized a heterozygous Scn1a knockout (Scn1a(+/-)) mouse model of Dravet syndrome to investigate the basis for phenotype variability. These animals exhibit strain-dependent seizure severity and survival.',
} as const;

export const EXTRACTION = {
  subject: 'Dravet syndrome',
  relation: 'caused_by_variant_in',
  object: 'SCN1A',
  tier: 'peer_reviewed',
  quotesChecked: 1202,
  quotesPassed: 1188,
  inferredDropped: 697,
} as const;

// Scene 3. Tier weights: schemas/enums.py via current-state.md §3. The 40
// rows are the supporting evidence of e_da7bfb96736c in API order. The
// computed link is e_9a02d642ad28 (Dravet syndrome and familial hemiplegic
// migraine 3): basis "the weaker of the two mechanism records (0.90, 0.90)",
// confidence_cap 0.79, confidence 0.79.
export const TIER_WEIGHT = {
  curated_db: 0.9,
  peer_reviewed: 0.7,
  review: 0.5,
} as const;

export type Tier = keyof typeof TIER_WEIGHT;

export const DRAVET_SCN1A_ROWS: readonly Tier[] = [
  'curated_db', 'curated_db', 'peer_reviewed', 'curated_db', 'curated_db',
  'peer_reviewed', 'peer_reviewed', 'review', 'review', 'peer_reviewed',
  'peer_reviewed', 'peer_reviewed', 'review', 'peer_reviewed', 'peer_reviewed',
  'peer_reviewed', 'peer_reviewed', 'review', 'review', 'review',
  'peer_reviewed', 'review', 'review', 'review', 'peer_reviewed',
  'peer_reviewed', 'review', 'review', 'review', 'review',
  'review', 'review', 'review', 'review', 'review',
  'review', 'peer_reviewed', 'peer_reviewed', 'review', 'peer_reviewed',
];

export const COMPUTED_LINK = {
  relation: 'same_gene_different_mechanism',
  basis: 0.9,
  cap: 0.79,
} as const;

// Scene 4. current-state.md §3 "Clustering" (multiplex Leiden, layer
// weights [1, -1], counterexample check) and GET /clusters.
export const COUNTEREXAMPLE = {
  gene: 'SCN1A',
  lof: {label: 'Dravet syndrome', mechanism: 'loss_of_function', cluster: 'CLUSTER:4'},
  gof: {
    label: 'migraine, familial hemiplegic, 3',
    mechanism: 'gain_of_function',
    cluster: 'CLUSTER:55',
  },
  relation: 'same_gene_different_mechanism',
} as const;

// Scene 5. current-state.md §5 "One turn" and "Tools". The cited edge ids
// are real; which ids a given turn returns is illustrative.
export const TURN_NODES = ['safety', 'entities', 'agent', 'postcheck'] as const;

export const TOOLS = [
  'resolve_to_ids',
  'search_graph',
  'get_neighborhood',
  'find_path',
  'match_phenotypes',
  'ask_followup',
] as const;

export const CLAIMS = [
  {edge: 'e_da7bfb96736c', kept: true},
  {edge: 'e_9a02d642ad28', kept: true},
  {edge: 'e_7adecce86d41', kept: false},
] as const;

// Scene 6. current-state.md §6 "How link origin is drawn" and §12.
export const ORIGINS = [
  {origin: 'observed', dash: 'none'},
  {origin: 'inferred', dash: '18 12'},
  {origin: 'patient_reported', dash: '4 9'},
] as const;

export const OUTRO = {
  name: 'Amber',
  logo: 'brand/amber-logo.webp',
  atlas: 'screens/atlas-map.jpg',
  detail: 'screens/atlas-dravet-lines.jpg',
  footer: 'data 2026-10-04.24 · validate 38/38',
} as const;
