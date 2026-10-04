/**
 * The landing page's switches and fixed ids, in one file.
 *
 * Honesty guard: everything the page shows is live data, or it is marked
 * "Coming soon". When a networking stage lands, set its item to "live" and
 * give it an `href`; the card then links there and drops the badge.
 */

export type ConnectStatus = "live" | "coming";

export const CONNECT_STATUS = {
  follow: "live",
  calls: "coming",
  choose: "coming",
} as const satisfies Record<string, ConnectStatus>;

export type ConnectItem = keyof typeof CONNECT_STATUS;

/** Where a networking card links once its item is live (unused while "coming"). */
export const CONNECT_HREF: Partial<Record<ConnectItem, string>> = {
  // Diseases are followed from the Atlas panel or a disease page.
  follow: "/atlas",
};

/** The demo family's condition: developmental and epileptic encephalopathy 4 (STXBP1). */
export const HERO_FOCUS_ID = "MONDO:0012812";

/**
 * The hero map cycles through these nodes, one kind each, so the map shows that
 * everything is connected, not only diseases. Missing ids are skipped; with fewer
 * than three left, the best-linked node per category fills up (atlas-preview-model).
 * The first is also the static view under reduced motion.
 */
export const HERO_CYCLE_IDS = [
  HERO_FOCUS_ID, // condition: the demo family's (STXBP1) disease
  "HGNC:11444", // gene: STXBP1
  "HP:0001263", // symptom: global developmental delay
  "PMID:26865513", // paper: STXBP1 encephalopathy cohort study, linking researchers, gene and diseases
  "REG:nct01793168", // patient registry: CoRDS, linking diseases and an institution
] as const;

/** At most this many links (the strongest) are drawn per cycle node, so a hub never becomes a solid fan. */
export const HERO_MAX_LINKS = 80;

/** One node's cycle in milliseconds: about 1 s drawing, 3.6 s holding, 0.6 s fading. */
export const HERO_CYCLE_MS = 5200;

/** SCN1A, the second focus chip of the graph section (hidden if not in the tree). */
export const GENE_FOCUS_ID = "HGNC:10585";

/** The spec's example message: the demo family's journey. */
export const DEMO_MESSAGE =
  "My daughter is 2, diagnosed with STXBP1 last month. Lots of seizures, not walking yet, no problems with eating.";
