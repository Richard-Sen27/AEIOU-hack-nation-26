import { expect, test, type Page } from "@playwright/test";

import { mockApi, signedInSession } from "../helpers";
import { atlasTreePayload, summaryMock } from "../graph/fixtures";
import { graphMocks, reply, STORY, turnBody } from "./fixtures";

/*
 * The Dr. Wu interface: the AI notice (once, scrolls away), sources in plain words (collapsed
 * by default) and the Atlas acting on a reply (select one find, draw a found connection).
 */

async function signedIn(page: Page, mocks: Record<string, unknown> = {}) {
  await mockApi(page, {
    "GET /auth/session": signedInSession({ consents: ["health_data"] }),
    "GET /chat/sessions": [],
    "GET /chat/runs": [],
    "GET /profile": { updated_at: "2026-10-03T00:00:00Z" },
    "GET /atlas/tree.json": atlasTreePayload(),
    "GET /atlas/summary/*": summaryMock(),
    ...graphMocks,
    "POST /chat": () => turnBody({ ...reply, follow_up: null }),
    ...mocks,
  });
}

async function ask(page: Page, scope: ReturnType<Page["locator"]>, text = STORY) {
  const box = scope.getByRole("textbox", { name: "Message Dr. Wu" });
  await box.fill(text);
  await box.press("Enter");
}

// Two cited links as the API serves them: an observed one backed by a paper, a trial and
// Orphanet, and a computed hypothesis with its one-line reason.
function apiEdge(id: string, relation: string, origin: string, explanation: string | null, evidence: Array<Record<string, unknown>>) {
  return {
    edge: {
      id,
      source_id: "MONDO:0100135",
      target_id: "HGNC:10585",
      relation,
      family: "dna",
      confidence: origin === "inferred" ? 0.7 : 0.95,
      confidence_level: origin === "inferred" ? "medium" : "high",
      origin,
      status: "active",
      features: null,
      data_version: "test",
      evidence_count: evidence.length,
      contradiction_count: 0,
      flagged: false,
      explanation,
    },
    source: { id: "MONDO:0100135", type: "disease", label: "Dravet syndrome", attrs: {} },
    target: { id: "HGNC:10585", type: "gene", label: "SCN1A", attrs: {} },
    supporting: evidence.map((e, i) => ({ id: i + 1, edge_id: id, tier_weight: 1, retrieved_at: "2026-10-04T00:00:00Z", quote: null, claim_type: null, polarity: "supports", ...e })),
    contradicting: [],
    confidence_breakdown: { score: 0.9, terms: [] },
  };
}
const OBSERVED = apiEdge("e_obs", "caused_by_variant_in", "observed", null, [
  { tier: "peer_reviewed", source_type: "pubmed", source_id: "35490361", url: "https://pubmed.ncbi.nlm.nih.gov/35490361/" },
  { tier: "curated_db", source_type: "clinicaltrials", source_id: "NCT05419492", url: "https://clinicaltrials.gov/study/NCT05419492" },
  { tier: "curated_db", source_type: "orphanet", source_id: "ORPHA:33069", url: "https://www.orpha.net/en/disease/detail/33069" },
]);
const COMPUTED = apiEdge("e_hyp", "shared_pathway", "inferred", "Their linked genes both take part in GABA receptor activation.", [
  { tier: "computed", source_type: "analytics", source_id: "SCN1A: go + reactome", url: null },
]);
const sourcesReply = {
  ...reply,
  claims: [
    { text: "Dravet syndrome is caused by changes in SCN1A.", edge_ids: ["e_obs"], origin: "observed", confidence: "high" },
    { text: "Dravet syndrome may affect the same body process as GEFS+.", edge_ids: ["e_hyp"], origin: "inferred", confidence: "medium" },
  ],
  contradictions: [],
  cards: [],
  actions: [],
  follow_up: null,
};
const sourceMocks = {
  "POST /chat": () => turnBody(sourcesReply),
  "GET /edge/*/evidence": (req: { url: string }) => ({ json: new URL(req.url).pathname.includes("e_obs") ? OBSERVED : COMPUTED }),
  "GET /node/*": () => ({
    json: {
      node: { id: "PMID:35490361", type: "paper", label: "International consensus on diagnosis and management of Dravet syndrome", attrs: { year: 2022 } },
      synonyms: [],
      summary: null,
      classification: null,
      vus_notice: null,
    },
  }),
};

test.describe("Dr. Wu sources", () => {
  test("chat: collapsed behind one line, named by what they are, hypothesis marked", async ({ page }) => {
    await signedIn(page, sourceMocks);
    await page.goto("/chat");
    await ask(page, page.locator("body"));
    const t = page.getByTestId("assistant-turn").last();
    await expect(t).toHaveAttribute("data-phase", "done");
    // The answer reads on its own; the sources are one click away.
    await expect(t.getByTestId("claim")).toHaveCount(2);
    await expect(t.getByTestId("sources-list")).toHaveCount(0);
    const toggle = t.getByTestId("sources").getByRole("button");
    await expect(toggle).toHaveText("Sources · 4");
    // The hypothesis is marked with its reason.
    await expect(t.getByTestId("claim").nth(1).getByTestId("claim-hypothesis")).toContainText("Hypothesis");
    await expect(t.getByTestId("claim").nth(1).getByTestId("claim-hypothesis")).toContainText("GABA receptor activation");
    await expect(t.getByTestId("claim").first().getByTestId("claim-hypothesis")).toHaveCount(0);
    await toggle.click();
    const list = t.getByTestId("sources-list");
    const rows = list.getByTestId("source");
    await expect(rows).toHaveCount(4);
    await expect(rows.nth(0)).toContainText("International consensus on diagnosis and management of Dravet syndrome");
    await expect(rows.nth(0)).toContainText("2022 · Paper, PubMed");
    await expect(rows.nth(0).getByRole("link")).toHaveAttribute("href", "https://pubmed.ncbi.nlm.nih.gov/35490361/");
    await expect(rows.nth(1)).toContainText("Clinical trial NCT05419492");
    await expect(list.getByTestId("source").filter({ hasText: "Orphanet" })).toContainText("rare disease database");
    await expect(list.locator('[data-kind="computed"]')).toContainText("Worked out by Amber");
    await expect(rows.nth(0)).toContainText("for 1");
    // Names, never raw ids or internal relation names.
    const text = await t.innerText();
    expect(text).not.toMatch(/caused_by_variant_in|shared_pathway|e_obs|e_hyp|ORPHA:33069|SCN1A: go/);
  });

  test("dock: the same statements and sources line, compact", async ({ page }) => {
    await signedIn(page, sourceMocks);
    await page.goto("/atlas");
    const dock = page.getByTestId("atlas-wu-dock");
    await dock.getByTestId("atlas-wu-open").click();
    await ask(page, dock);
    await expect(dock.getByTestId("atlas-wu-turn")).toHaveAttribute("data-phase", "done");
    await expect(dock.getByTestId("claim")).toHaveCount(2);
    await expect(dock.getByTestId("sources-list")).toHaveCount(0);
    await dock.getByTestId("sources").getByRole("button").click();
    await expect(dock.getByTestId("sources-list").getByTestId("source")).toHaveCount(4);
  });
});

test.describe("Dr. Wu AI notice", () => {
  test("chat: one quiet line at the start that scrolls away, not repeated per turn", async ({ page }) => {
    await signedIn(page);
    await page.setViewportSize({ width: 1440, height: 700 });
    await page.goto("/chat");
    const notice = page.getByTestId("ai-disclosure");
    await expect(notice).toHaveCount(1);
    await expect(notice).toContainText("Dr. Wu is an AI, not a doctor.");
    await expect(notice).toBeInViewport();
    await ask(page, page.locator("body"));
    await ask(page, page.locator("body"), "And the registry?");
    await expect(page.getByTestId("assistant-turn")).toHaveCount(2);
    await expect(page.getByTestId("assistant-turn").last()).toHaveAttribute("data-phase", "done");
    await expect(notice).toHaveCount(1);
    await expect(page.getByText("AI-generated · Dr. Wu")).toHaveCount(0);
    // Inside the conversation's scroll area: scrolled to the end, it is out of view.
    expect(await notice.evaluate((el) => !!el.closest('[data-testid="chat-log"]'))).toBe(true);
    await page.getByTestId("chat-log").evaluate((el) => el.scrollTo(0, el.scrollHeight));
    await expect(notice).not.toBeInViewport();
  });

  test("dock: the same line once, in the scrolling body, not in the header", async ({ page }) => {
    await signedIn(page);
    await page.goto("/atlas");
    const dock = page.getByTestId("atlas-wu-dock");
    await dock.getByTestId("atlas-wu-open").click();
    await ask(page, dock);
    await expect(dock.getByTestId("atlas-wu-turn")).toHaveAttribute("data-phase", "done");
    await expect(dock.getByTestId("ai-disclosure")).toHaveCount(1);
    expect(await dock.getByTestId("ai-disclosure").evaluate((el) => !!el.closest('[data-testid="atlas-wu-body"]'))).toBe(true);
    await expect(dock.getByText("AI-generated · Dr. Wu")).toHaveCount(0);
  });
});
