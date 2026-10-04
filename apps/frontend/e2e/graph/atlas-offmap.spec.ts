import { expect, test, type Page } from "@playwright/test";

import { mockApi, signedInSession, sseBody, trackConsoleErrors } from "../helpers";
import { CORE, FOCUS_DISEASE_COUNT, wideMocks } from "./fixtures";

/**
 * Wide scope, stage A: every qualifying rare disease is in the atlas and
 * findable, but the map shows only the focus set. Nodes that exist but are
 * not on the map must read as intentionally limited, never as broken.
 * Mocked only: the dev database does not hold the wide set yet.
 */

const SCRATCH = process.env.SHOT_DIR;
const COVERAGE = `Literature, trials, researchers and patient groups are collected for ${FOCUS_DISEASE_COUNT} focus diseases; this one isn't one of them yet.`;

async function mapReady(page: Page) {
  await expect(page.getByTestId("atlas-canvas").locator("canvas").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("atlas-logo")).toBeVisible();
  await expect(page.getByTestId("atlas-category-label")).toHaveCount(9);
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
  await page.waitForTimeout(300);
}

/** The logo sits on the hub and scales with the camera: its box is the camera state. */
const logoBox = async (page: Page) => (await page.getByTestId("atlas-logo").boundingBox())!;

async function shoot(page: Page, name: string) {
  if (SCRATCH) await page.screenshot({ path: `${SCRATCH}/${name}.png`, animations: "disabled" });
}

const panel = (page: Page) => page.getByTestId("atlas-panel");

async function expectCorePanel(page: Page) {
  await expect(panel(page).getByRole("heading", { level: 2 })).toHaveText("fibrodysplasia ossificans progressiva");
  await expect(panel(page).getByTestId("atlas-coverage")).toHaveText(COVERAGE);
  await expect(panel(page).getByTestId("atlas-panel-ids").getByTestId("atlas-offmap")).toHaveText("Not on the map yet");
  const links = panel(page).getByTestId("atlas-panel-id-link");
  await expect(links).toHaveText([/MONDO:0007606/, /ORPHA:337/, /OMIM:135100/]);
  const hrefs = await links.evaluateAll((as) => as.map((a) => a.getAttribute("href")));
  expect(hrefs).toEqual([
    "https://purl.obolibrary.org/obo/MONDO_0007606",
    "https://www.orpha.net/en/disease/detail/337",
    "https://omim.org/entry/135100",
  ]);
  // Ids only in the URLs, never names.
  for (const h of hrefs) expect(h).not.toMatch(/fibrodysplasia|ossificans/i);
  await expect(panel(page).getByTestId("atlas-crumb")).toHaveCount(0);

  // Symptoms by frequency with the source's label; the gene with its sources.
  const symptoms = panel(page).locator('[data-section="symptoms"] [data-testid="atlas-summary-item"]');
  await expect(symptoms).toHaveText([
    /Ectopic ossification in muscle tissue.*Very frequent/,
    /Hallux valgus.*Frequent/,
    /Hearing impairment.*Occasional/,
  ]);
  await expect(panel(page).locator('[data-section="genes"] [data-testid="atlas-summary-detail"]')).toHaveText("Orphanet · HPO");
  // Similar conditions keep their confidence and explanation.
  const similar = panel(page).locator('[data-section="similar_diseases"] [data-testid="atlas-summary-item"]');
  await expect(similar.first()).toContainText("progressive osseous heteroplasia");
  await expect(similar.first().getByTestId("atlas-summary-explanation")).toContainText("Similar symptom profile");
  await expect(similar.first()).toContainText("Medium");
  // None of these links is on the map: nothing to draw, so no "Show the link".
  await expect(panel(page).getByTestId("atlas-summary-chain")).toHaveCount(0);
}

test.describe("nodes that are not on the map", () => {
  test("search lists them, marked, and opens the panel without moving the camera", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockApi(page, wideMocks());
    const errors = trackConsoleErrors(page);
    await page.goto("/atlas");
    await mapReady(page);
    const before = await logoBox(page);

    const search = page.getByTestId("atlas-search");
    await search.getByRole("combobox", { name: "Search the map" }).fill("fop");
    const option = search.locator(`[data-node-id="${CORE.fop}"]`);
    await expect(option).toHaveAttribute("data-offmap", "true");
    await expect(option).toContainText("FOP");
    await expect(option).toContainText("fibrodysplasia ossificans progressiva");
    await expect(option.getByTestId("atlas-offmap")).toHaveText("Not on the map yet");
    await expect(search.locator(`[data-node-id="${CORE.acvr1}"]`).getByTestId("atlas-offmap")).toBeVisible();
    await shoot(page, `stage-a-fe-search-${page.viewportSize()!.width}`);

    await option.click();
    await expectCorePanel(page);
    await expect(page.getByTestId("atlas-missing-focus")).toHaveCount(0);
    await page.waitForTimeout(600);
    const after = await logoBox(page);
    expect(Math.abs(after.x - before.x)).toBeLessThan(1);
    expect(Math.abs(after.y - before.y)).toBeLessThan(1);
    expect(Math.abs(after.width - before.width)).toBeLessThan(1);
    await shoot(page, `stage-a-fe-panel-${page.viewportSize()!.width}`);

    // An item of the panel that is also off the map opens in place, again without a camera move.
    await panel(page).getByRole("button", { name: /progressive osseous heteroplasia/ }).click();
    await expect(panel(page).getByRole("heading", { level: 2 })).toHaveText("progressive osseous heteroplasia");
    await expect(page.getByTestId("atlas-missing-focus")).toHaveCount(0);
    expect(errors()).toEqual([]);
  });

  test("?focus= of an off-map node opens its summary with the reworded notice", async ({ page }) => {
    await mockApi(page, wideMocks());
    await page.goto(`/atlas?focus=${encodeURIComponent(CORE.fop)}`);
    await expectCorePanel(page);
    const notice = page.getByTestId("atlas-missing-focus");
    await expect(notice).toHaveAttribute("data-reason", "off-map");
    await expect(notice).toHaveText(`${CORE.fop} isn't on the map yet. Its summary is open.`);
    await expect(notice.getByRole("link")).toHaveCount(0);
  });

  test("?focus= of an id that does not exist keeps the old notice", async ({ page }) => {
    await mockApi(page, wideMocks());
    await page.goto("/atlas?focus=MONDO%3A404");
    const notice = page.getByTestId("atlas-missing-focus");
    await expect(notice).toHaveAttribute("data-reason", "unknown");
    await expect(notice).toContainText("MONDO:404 is not on the map.");
    await expect(notice.getByRole("link", { name: "Open it directly" })).toHaveAttribute("href", "/node/MONDO%3A404");
    await expect(panel(page)).toHaveCount(0);
  });

  test("a focus disease's panel offers 'Show the link' only for links on the map", async ({ page }) => {
    await mockApi(page, wideMocks());
    await page.goto("/atlas?focus=MONDO%3A9900007");
    await expect(panel(page).getByRole("heading", { level: 2 })).toHaveText("STXBP1 encephalopathy");
    await expect(panel(page).getByTestId("atlas-coverage")).toHaveCount(0);
    // Its ids are linked too, but it is on the map: no off-map mark.
    await expect(panel(page).getByTestId("atlas-panel-id-link")).toHaveText([/MONDO:9900007/]);
    await expect(panel(page).getByTestId("atlas-panel-ids").getByTestId("atlas-offmap")).toHaveCount(0);
    await expect(panel(page).getByTestId("atlas-summary-chain").first()).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// Dr. Wu: finds on and off the map

const STORY = "Muscles turning to bone after small injuries, and a short big toe.";
const ON_MAP = ["MONDO:9900007", "HGNC:11444"];
const reply = {
  summary: "These conditions in the atlas have recorded symptoms that overlap with what you describe.",
  uncertainty: null,
  chips: [{ type: "symptom", id: "HP:0011987", label: "Ectopic ossification in muscle tissue", negated: false, confirmed: false }],
  claims: [],
  contradictions: [],
  missing_evidence: [],
  cards: [],
  graph_focus: { node_ids: [CORE.fop, ...ON_MAP, CORE.pcd], highlight_path: ["e_e5f778ac8a21"] },
  actions: [],
  follow_up: null,
  ai_notice: null,
  gap_search: null,
  kind: "answer",
};
const turnBody = sseBody([
  { type: "summary_delta", text: reply.summary },
  { type: "final", reply, session_id: "11111111-1111-4111-8111-111111111111", message_id: "22222222-2222-4222-8222-222222222222" },
]);

test("the dock lists finds on and off the map, counts all, rings only those on it", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const urls: string[] = [];
  page.on("request", (r) => urls.push(decodeURIComponent(r.url())));
  await mockApi(page, wideMocks({ "GET /auth/session": signedInSession({ consents: ["health_data"] }), "GET /chat/sessions": [], "POST /chat": turnBody }));
  const errors = trackConsoleErrors(page);
  await page.goto("/atlas");
  const dock = page.getByTestId("atlas-wu-dock");
  await dock.getByTestId("atlas-wu-open").click();
  const box = dock.getByRole("textbox", { name: "Message Dr. Wu" });
  await box.fill(STORY);
  await box.press("Enter");

  const found = dock.getByTestId("atlas-wu-found");
  await expect(found).toContainText("Dr. Wu found 5");
  const items = found.getByTestId("atlas-wu-found-item");
  await expect(items).toHaveText([
    /fibrodysplasia ossificans progressiva.*Not on the map yet/,
    /STXBP1 encephalopathy/,
    /^STXBP1/,
    /primary ciliary dyskinesia 25.*Not on the map yet/,
    /Ectopic ossification in muscle tissue.*Not on the map yet/,
  ]);
  await expect(items.nth(1).getByTestId("atlas-offmap")).toHaveCount(0);
  await shoot(page, `stage-a-fe-dock-${page.viewportSize()!.width}`);

  // An off-map find opens its summary; nothing is written to the URL or storage.
  await items.first().click();
  await expectCorePanel(page);
  const url = decodeURIComponent(page.url());
  expect(url).not.toContain("focus");
  for (const id of [CORE.fop, CORE.pcd, ...ON_MAP]) expect(url).not.toContain(id);
  const stored = await page.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }));
  for (const id of [CORE.fop, CORE.pcd, ...ON_MAP]) expect(stored).not.toContain(id);
  expect(urls.some((u) => /muscles|toe/i.test(u))).toBe(false);
  expect(errors()).toEqual([]);
});

test.describe("on a 390 px phone", () => {
test.use({ viewport: { width: 390, height: 844 } });

test("dock with mixed finds on a phone @mobile", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockApi(page, wideMocks({ "GET /auth/session": signedInSession({ consents: ["health_data"] }), "GET /chat/sessions": [], "POST /chat": turnBody }));
  await page.goto("/atlas");
  await page.getByTestId("atlas-wu-open").click();
  const sheet = page.getByTestId("atlas-wu-sheet");
  const box = sheet.getByRole("textbox", { name: "Message Dr. Wu" });
  await box.fill(STORY);
  await box.press("Enter");
  await expect(sheet.getByTestId("atlas-wu-found")).toContainText("Dr. Wu found 5");
  await expect(sheet.getByTestId("atlas-wu-found-item").first()).toContainText("Not on the map yet");
  await shoot(page, `stage-a-fe-dock-${page.viewportSize()!.width}`);
});

test("search and panel for an off-map disease on a phone @mobile", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockApi(page, wideMocks());
  await page.goto("/atlas");
  await mapReady(page);
  const search = page.getByTestId("atlas-search");
  await search.getByRole("combobox", { name: "Search the map" }).fill("fop");
  const option = search.locator(`[data-node-id="${CORE.fop}"]`);
  await expect(option.getByTestId("atlas-offmap")).toBeVisible();
  await shoot(page, `stage-a-fe-search-${page.viewportSize()!.width}`);
  await option.click();
  await expect(panel(page).getByTestId("atlas-coverage")).toHaveText(COVERAGE);
  await page.getByTestId("atlas-sheet").getByRole("button", { name: "Show more" }).click();
  await expect(panel(page).getByTestId("atlas-panel-id-link")).toHaveCount(3);
  await shoot(page, `stage-a-fe-panel-${page.viewportSize()!.width}`);
});
});

// ---------------------------------------------------------------------------
// The chat hands finds over in memory: off-map ones are listed too.

test("the chat handoff lists off-map finds and rings only those on the map", async ({ page }) => {
  await mockApi(
    page,
    wideMocks({
      "GET /auth/session": signedInSession({ consents: ["health_data"] }),
      "GET /chat/sessions": [],
      "GET /profile": { updated_at: "2026-10-03T00:00:00Z" },
      "POST /chat": turnBody,
    }),
  );
  await page.goto("/chat");
  const composer = page.getByRole("textbox", { name: "Message Dr. Wu" });
  await composer.fill(STORY);
  await composer.press("Enter");
  await page.getByTestId("show-in-graph").click();
  await expect(page).toHaveURL(/\/atlas$/);
  await expect(page.getByTestId("atlas-wu-found")).toContainText("Dr. Wu found 4");
  await page.getByTestId("atlas-wu-open").click();
  await expect(page.getByTestId("atlas-wu-found-item")).toHaveText([
    /fibrodysplasia ossificans progressiva.*Not on the map yet/,
    /STXBP1 encephalopathy/,
    /^STXBP1/,
    /primary ciliary dyskinesia 25.*Not on the map yet/,
  ]);
});

// ---------------------------------------------------------------------------
// Node page and about-data

test("the node page says when a hub's neighbourhood was cut", async ({ page }) => {
  const mocks = wideMocks();
  const hood = mocks["GET /neighborhood/*"] as (req: { url: string }) => { json: unknown };
  await mockApi(page, {
    ...mocks,
    "GET /neighborhood/*": (req: { url: string }) => ({
      ...hood(req),
      headers: { "X-Neighborhood-Total": "2172", "X-Neighborhood-Truncated": "true", "Access-Control-Expose-Headers": "X-Neighborhood-Total, X-Neighborhood-Truncated" },
    }),
  });
  await page.goto("/node/HP%3A0001250");
  const line = page.getByTestId("node-truncated");
  await expect(line).toHaveText(/^Showing the \d+ strongest of 2,172 links$/);
});

test("the node page shows no cut line when nothing was cut", async ({ page }) => {
  await mockApi(page, wideMocks());
  await page.goto("/node/HP%3A0001250");
  await expect(page.getByTestId("node-counts")).toBeVisible();
  await expect(page.getByTestId("node-truncated")).toHaveCount(0);
});

test("about-data states the inclusion rule with live counts", async ({ page }) => {
  await mockApi(page, {
    "GET /auth/session": { user: null, gpc: false, demo_mode: false, data_version: "fixture" },
    "GET /stats": { data_version: "fixture", diseases: 7430, genes: 5172, symptoms: 10541, links_cited: 210000, links_computed: 75000 },
  });
  await page.goto("/about-data");
  const section = page.locator("#scope");
  await expect(page.getByTestId("scope-counts")).toHaveText(": 7,430 diseases, 5,172 genes and 10,541 symptoms right now.");
  await expect(page.getByTestId("scope-rule")).toContainText(
    "every rare disease with a MONDO identifier, at least one known gene and one recorded symptom, leaving out susceptibilities and broad disease groups",
  );
  await expect(section).toContainText("Focus diseases also have papers, trials");
  await expect(section).toContainText("Counts of ClinVar variants per gene; individual variants only for focus genes.");
  await expect(section).toContainText("Reactome");
});

test("about-data reads well without the counts", async ({ page }) => {
  await mockApi(page, { "GET /auth/session": { user: null, gpc: false, demo_mode: false, data_version: "fixture" }, "GET /stats": "offline" });
  await page.goto("/about-data");
  await expect(page.getByTestId("scope-rule")).toHaveText(
    "The atlas includes every rare disease with a MONDO identifier, at least one known gene and one recorded symptom, leaving out susceptibilities and broad disease groups.",
  );
});
