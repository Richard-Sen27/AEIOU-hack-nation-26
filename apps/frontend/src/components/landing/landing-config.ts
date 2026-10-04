/**
 * The landing page's switches and fixed ids, in one file.
 *
 * Honesty guard: everything the page shows is live data, or it is marked
 * "Coming soon". When a networking stage lands, set its item to "live" and
 * give it an `href`; the card then links there and drops the badge.
 */

export type ConnectStatus = "live" | "coming";

export const CONNECT_STATUS = {
  follow: "coming",
  calls: "coming",
  choose: "coming",
} as const satisfies Record<string, ConnectStatus>;

export type ConnectItem = keyof typeof CONNECT_STATUS;

/** Where a networking card links once its item is live (unused while "coming"). */
export const CONNECT_HREF: Partial<Record<ConnectItem, string>> = {};

/** The demo family's condition: developmental and epileptic encephalopathy 4 (STXBP1). */
export const HERO_FOCUS_ID = "MONDO:0012812";

/** SCN1A, the second focus chip of the graph section (hidden if not in the tree). */
export const GENE_FOCUS_ID = "HGNC:10585";

/** The spec's example message: the demo family's journey. */
export const DEMO_MESSAGE =
  "My daughter is 2, diagnosed with STXBP1 last month. Lots of seizures, not walking yet, no problems with eating.";
