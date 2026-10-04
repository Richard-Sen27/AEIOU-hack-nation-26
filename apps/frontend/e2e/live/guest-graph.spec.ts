/**
 * Live guest journey through the graph: landing → search → node → connection
 * → evidence → lens switch → Atlas (search, focus, filters, outline, tour) → clusters.
 * Start the processes as described in live-helpers.ts, then `PORT=3106 pnpm test:e2e:live`.
 */
import { expect, test, type Page } from "@playwright/test";

import { IDS, shot, storageDump, trackProblems, trackUrls } from "./live-helpers";

async function switchLens(page: Page, name: RegExp) {
  await page.getByTestId("lens-switcher").click();
  await page.getByRole("menuitemradio", { name }).click();
  await page.keyboard.press("Escape");
}

test.describe("guest graph journey", () => {
  test("landing search opens the node, its connections and their evidence", async ({ page }) => {
    const problems = trackProblems(page);
    await page.goto("/");
    const input = page.getByRole("textbox", { name: /Describe the diagnosis/ });
    await input.fill("Dravet syndrome");
    await expect(page.getByTestId("hero-hint")).toHaveAttribute("data-mode", "search");
    await input.press("Enter");
    await expect(page).toHaveURL(/\/node\/MONDO%3A0100135$/);
    await expect(page.getByRole("heading", { level: 1, name: /Dravet syndrome/i })).toBeVisible();
    await expect(page.getByTestId("node-graph").locator("canvas").first()).toBeVisible({ timeout: 30_000 });
    const panel = page.getByTestId("node-panel");
    await expect(panel.getByTestId("relation-group").first()).toBeVisible();
    await expect(panel).not.toContainText("[object Object]");
    await shot(page, "guest-node");

    // Follow a connection to its evidence: SCN1A, the gene behind Dravet.
    await panel.getByRole("button", { name: /^Sources for SCN1A/ }).first().click();
    const edge = page.getByTestId("edge-panel");
    await expect(edge.getByTestId("evidence-list")).toBeVisible();
    await expect(edge.getByTestId("evidence-list").getByRole("link").first()).toHaveAttribute("href", /^https?:\/\//);
    await expect(edge.getByTestId("origin-badge").first()).toBeVisible();
    await edge.getByTestId("confidence-badge").first().click();
    await expect(page.getByTestId("confidence-breakdown").first()).toContainText(/source/i);
    await shot(page, "guest-edge");
    await edge.getByRole("button", { name: "Back" }).click();

    // Follow the connection itself: open the gene's node.
    await panel.getByRole("link", { name: /^SCN1A \(/ }).first().click();
    await expect(page).toHaveURL(new RegExp(`/node/${encodeURIComponent(IDS.scn1a)}$`));
    await expect(page.getByRole("heading", { level: 1, name: "SCN1A" })).toBeVisible();
    expect(problems()).toEqual([]);
  });

  test("an edge with contradicting evidence shows the contradiction", async ({ page }) => {
    const problems = trackProblems(page);
    // complex neurodevelopmental disorder → RELN has a contradicting source in the real graph.
    await page.goto(`/node/${encodeURIComponent("MONDO:0100038")}`);
    await page.getByTestId("node-panel").getByRole("button", { name: /^Sources for RELN/ }).first().click();
    const edge = page.getByTestId("edge-panel");
    await expect(edge.getByTestId("contradiction-note")).toContainText(/contradict/);
    await expect(edge.getByTestId("evidence-list").locator('[data-polarity="contradicts"]')).toHaveCount(1);
    await shot(page, "guest-edge-contradiction");
    expect(problems()).toEqual([]);
  });

  test("lens switch changes wording, never the node or edge set", async ({ page }) => {
    const problems = trackProblems(page);
    await page.goto(`/node/${encodeURIComponent(IDS.dee4)}`);
    const counts = page.getByTestId("node-counts");
    await expect(counts).toContainText("connections");
    const before = await counts.textContent();
    await page.getByRole("radio", { name: "List" }).click();
    const rows = page.getByTestId("node-list-row");
    await expect(rows.first()).toBeVisible();
    const nRows = await rows.count();
    const headingsBefore = await page.getByTestId("relation-heading").allTextContents();
    await switchLens(page, /Researcher/);
    await expect.poll(() => page.getByTestId("relation-heading").allTextContents()).not.toEqual(headingsBefore);
    await expect(counts).toHaveText(before!);
    await expect(rows).toHaveCount(nRows);
    await switchLens(page, /Doctor/);
    await expect(counts).toHaveText(before!);
    await expect(rows).toHaveCount(nRows);
    await switchLens(page, /Guest/);
    expect(problems()).toEqual([]);
  });

  test("atlas loads the real tree, searches, focuses, filters and lists", async ({ page }) => {
    const problems = trackProblems(page);
    await page.goto("/atlas");
    await expect(page.getByTestId("atlas-counts")).toContainText(/[\d,]+ items · [\d,]+ connections/, { timeout: 30_000 });
    const canvas = page.getByTestId("atlas-canvas");
    await expect(canvas.locator("canvas").first()).toBeVisible({ timeout: 30_000 });
    // The logo hub and the nine category names, mixed case.
    await expect(page.getByTestId("atlas-logo")).toBeVisible();
    const labels = page.getByTestId("atlas-category-label");
    await expect(labels).toHaveCount(9);
    for (const text of await labels.allTextContents()) {
      expect(text.trim().length).toBeGreaterThan(0);
      expect(text).not.toBe(text.toUpperCase());
    }
    await expect(page.getByTestId("atlas-panel")).toHaveCount(0);

    // Pan and zoom stay responsive on ~7k tree nodes / ~17k edges.
    const box = (await canvas.boundingBox())!;
    const cx = box.x + box.width / 2;
    const cy = box.y + box.height / 2;
    const t0 = Date.now();
    await page.mouse.move(cx, cy);
    for (let i = 0; i < 5; i++) await page.mouse.wheel(0, -200);
    await page.mouse.down();
    await page.mouse.move(cx + 150, cy + 80, { steps: 10 });
    await page.mouse.up();
    const frameMs = await page.evaluate(
      () =>
        new Promise<number>((resolve) => {
          const start = performance.now();
          let n = 0;
          const tick = () => (++n === 30 ? resolve((performance.now() - start) / 30) : requestAnimationFrame(tick));
          requestAnimationFrame(tick);
        }),
    );
    expect(Date.now() - t0).toBeLessThan(8_000);
    expect(frameMs, "average frame time while idle after pan/zoom").toBeLessThan(100);

    // Focus by URL: the summary panel opens.
    await page.goto(`/atlas?focus=${encodeURIComponent(IDS.stxbp1)}`);
    const atlasPanel = page.getByTestId("atlas-panel");
    await expect(atlasPanel.getByRole("heading", { level: 2 })).toHaveText("STXBP1", { timeout: 30_000 });
    await expect(atlasPanel.getByTestId("atlas-summary-section").first()).toBeVisible();
    await expect(page.getByTestId("atlas-open-node")).toHaveAttribute("href", `/node/${encodeURIComponent(IDS.stxbp1)}`);
    await shot(page, "guest-atlas-focus");

    // Search the map.
    const search = page.getByTestId("atlas-search");
    await search.getByRole("combobox", { name: "Search the map" }).fill("Dravet syndrome");
    await search.locator('[data-node-id="MONDO:0100135"]').click();
    await expect(atlasPanel.getByRole("heading", { level: 2 })).toHaveText(/Dravet syndrome/i);
    await expect(page).toHaveURL(/focus=MONDO%3A0100135/);

    // Filters: connection kinds drawn on click.
    await page.getByTestId("atlas-filters").click();
    const chip = page.getByTestId("family-chip-symptoms");
    await chip.click();
    await expect(chip).toHaveAttribute("aria-pressed", "false");
    await page.keyboard.press("Escape");

    // List view: the same trees as an outline, with the selection revealed.
    await page.getByTestId("view-toggle").getByRole("radio", { name: "List" }).click();
    const outline = page.getByTestId("atlas-outline");
    await expect(outline.locator('[data-testid="atlas-outline-item"][data-id="MONDO:0100135"]')).toHaveAttribute("aria-selected", "true");
    await outline.getByTestId("atlas-outline-filter").fill("dravet");
    await expect(outline.getByTestId("atlas-outline-status")).toContainText(/match/);
    expect(problems()).toEqual([]);
  });

  test("guided tour at /atlas?tour=1", async ({ page }) => {
    const problems = trackProblems(page);
    await page.goto("/atlas?tour=1");
    const tour = page.getByTestId("atlas-tour");
    await expect(tour).toBeVisible({ timeout: 30_000 });
    await expect(tour).toContainText("One map, many trees");
    await shot(page, "guest-tour-1");
    await expect(page.getByText("Drawing the map")).toBeHidden({ timeout: 30_000 });
    const next = page.getByTestId("tour-next");
    for (let i = 0; i < 4; i++) {
      await next.click();
      await expect(tour).toContainText(`${i + 2} of 5`);
    }
    await expect(tour).toContainText("Ask Dr. Wu");
    await expect(next).toHaveText(/Start exploring/);
    await shot(page, "guest-tour-end");
    await next.click();
    await expect(tour).toBeHidden();
    expect(problems()).toEqual([]);
  });

  test("clusters list opens a cluster with its members", async ({ page }) => {
    const problems = trackProblems(page);
    await page.goto("/clusters");
    const cards = page.getByTestId("cluster-card");
    await expect(cards).toHaveCount(9);
    await expect(cards.first().getByTestId("origin-badge")).toHaveAttribute("data-origin", "inferred");
    await cards.first().getByRole("heading").getByRole("link").click();
    await expect(page).toHaveURL(/\/node\/CLUSTER%3A\d+$/);
    await expect(page.getByTestId("cluster-members")).toBeVisible();
    await shot(page, "guest-cluster");
    expect(problems()).toEqual([]);
  });

  test("researcher entries can be claimed or removed", async ({ page }) => {
    const problems = trackProblems(page);
    await page.goto(`/node/${encodeURIComponent("ORCID:0000-0001-8898-8313")}`);
    await page.getByTestId("claim-entry-link").click();
    await expect(page).toHaveURL(/\/about-data\?entry=ORCID%3A0000-0001-8898-8313#claim$/);
    await expect(page.getByTestId("claim-entry")).toContainText("ORCID:0000-0001-8898-8313");
    // Either a prefilled mailto, or a clear explanation when no address is configured.
    const mailto = page.getByTestId("claim-mailto");
    if (await mailto.count()) await expect(mailto).toHaveAttribute("href", /ORCID%3A0000-0001-8898-8313/);
    else await expect(page.getByTestId("claim-no-email")).toBeVisible();
    expect(problems()).toEqual([]);
  });

  test("nothing health-related ends up in URLs or storage", async ({ page }) => {
    const urls = trackUrls(page);
    await page.goto("/");
    await page.getByRole("textbox", { name: /Describe the diagnosis/ }).fill(
      "My son has seizures and is not walking yet",
    );
    await page.getByRole("button", { name: "Send to Dr. Wu" }).click();
    await expect(page.getByTestId("sign-in-dialog")).toBeVisible();
    expect(urls.some((u) => /seizure|walking/i.test(decodeURIComponent(u)))).toBe(false);
    expect(await storageDump(page)).not.toMatch(/seizure|walking/i);
  });
});
