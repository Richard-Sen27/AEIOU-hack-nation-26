// The single source of the video's words and file names.
// Read by the scenes (on-screen text, placeholder cards) and by
// scripts/generate-voiceover.ts (narration). Keep this file free of
// imports and of TypeScript-only runtime syntax (enums, namespaces), so
// Node can run the voiceover script on it by stripping types.

export type SceneId = 'arrive' | 'graph' | 'dr-wu' | 'gap' | 'people' | 'close';

export type SceneContent = {
  readonly id: SceneId;
  readonly number: number;
  readonly name: string;
  readonly narration: string;
  // Shooting guide, shown on the placeholder card until the recording exists.
  readonly shots: readonly string[];
  // Lower-third caption; only scenes that list one show one.
  readonly caption?: string;
  // Paths inside public/.
  readonly recording: string;
  readonly voiceover: string;
};

export const SCENES = {
  arrive: {
    id: 'arrive',
    number: 1,
    name: 'Alex arrives',
    narration:
      "Meet Alex. Diagnosis: pityriasis rubra pilaris, a skin disease found in a few people per million. What's known is scattered.",
    shots: [
      'Sign in with "Continue with ChatGPT"',
      'Welcome: "Patient or family", "I am 16 or older."',
      'Health profile: add diagnosis "PRP", two symptoms',
      'Consent, then "Profile saved"',
    ],
    recording: 'recordings/01-arrive.mp4',
    voiceover: 'voiceover/01-arrive.mp3',
  },
  graph: {
    id: 'graph',
    number: 2,
    name: 'The graph',
    narration:
      'Amber connects it. One search places the disease among seven thousand others: symptoms, look-alike conditions, and one gene, CARD14. Every link shows its sources.',
    shots: [
      'Atlas overview, 7,760 items',
      '⌘K, type "pityriasis", Enter',
      'PRP graph with 40 links',
      'Click the CARD14 link: "Supporting · 5"',
    ],
    recording: 'recordings/02-graph.mp4',
    voiceover: 'voiceover/02-graph.mp3',
  },
  'dr-wu': {
    id: 'dr-wu',
    number: 3,
    name: 'Dr. Wu',
    narration:
      'Dr. Wu, the AI guide, walks the graph, not the web, and finds a relative under another name: a psoriasis caused by the same gene. Shared mechanism? Not established.',
    shots: [
      '"Ask Dr. Wu"',
      'Type "Which conditions share a gene with PRP?"',
      'Step lines tick',
      'Answer with the "Hypothesis" pill',
      'Expand "Sources"',
    ],
    caption: 'Dr. Wu · OpenAI models · every citation checked in code',
    recording: 'recordings/03-dr-wu.mp4',
    voiceover: 'voiceover/03-dr-wu.mp3',
  },
  gap: {
    id: 'gap',
    number: 4,
    name: 'The honest gap',
    narration:
      "Amber doesn't guess. No supported research route, and here is what it checked. Then an agent searches PubMed and ClinicalTrials.gov and returns quoted evidence for review.",
    shots: [
      '"Find a path to…" psoriasis 2: cited route via CARD14',
      'Filter "Shared research": "No supported route"',
      '"Run gap search"',
      'Candidates "Pending review"',
      '"Submit to the shared graph"',
    ],
    recording: 'recordings/04-gap.mp4',
    voiceover: 'voiceover/04-gap.mp3',
  },
  people: {
    id: 'people',
    number: 5,
    name: 'People',
    narration:
      'Where evidence ends, people begin. A researcher is recruiting on this exact question. Alex signs up and starts a conversation.',
    shots: [
      'PRP page: "Looking for participants · 1"',
      'Study titled "Demo: …"',
      '"Sign up", diagnosis ticked, "Send"',
      '"Sent", then "Conversation"',
    ],
    recording: 'recordings/05-people.mp4',
    voiceover: 'voiceover/05-people.mp3',
  },
  close: {
    id: 'close',
    number: 6,
    name: 'Close',
    narration:
      'For rare diseases, the knowledge exists. Patients, research and experts are just disconnected. Amber brings them together.',
    shots: [
      'Atlas, slow zoom-out over all nine trees',
      'Cut to the Amber logo',
    ],
    caption: 'From weeks of searching to minutes',
    recording: 'recordings/06-close.mp4',
    voiceover: 'voiceover/06-close.mp3',
  },
} as const satisfies Record<SceneId, SceneContent>;

export const OUTRO = {
  name: 'Amber',
  tagline: 'Rare diseases, connected by what they share.',
  logo: 'brand/amber-logo.webp',
} as const;
