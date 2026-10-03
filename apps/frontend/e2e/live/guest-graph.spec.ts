/**
 * Live guest journey through the graph: landing → search → node → connection
 * → evidence → lens switch → Atlas (focus, filters, list, tour) → clusters.
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

  test("atlas loads the real graph, focuses, filters, lists and tours", async ({ page }) => {
    const problems = trackProblems(page);
    await page.goto("/atlas");
    await expect(page.getByTestId("atlas-counts")).toContainText(/[\d,]+ items · [\d,]+ connections/, { timeout: 30_000 });
    const canvas = page.getByTestId("atlas-canvas");
    await expect(canvas.locator("canvas").first()).toBeVisible({ timeout: 30_000 });

    // Pan and zoom stay responsive on ~6k nodes / ~17k edges.
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

    // Focus by URL.
    await page.goto(`/atlas?focus=${encodeURIComponent(IDS.stxbp1)}`);
    const atlasPanel = page.getByTestId("atlas-panel");
    await expect(atlasPanel.getByRole("heading", { level: 2 })).toHaveText("STXBP1", { timeout: 30_000 });
    await expect(page.getByTestId("atlas-open-node")).toHaveAttribute("href", `/node/${encodeURIComponent(IDS.stxbp1)}`);
    await shot(page, "guest-atlas-focus");

    // Find on map.
    await page.getByTestId("atlas-find").click();
    await page.getByRole("combobox", { name: "Find on the map" }).fill("Dravet syndrome");
    await page.getByRole("option", { name: /Dravet syndrome/ }).first().click();
    await expect(atlasPanel.getByRole("heading", { level: 2 })).toHaveText(/Dravet syndrome/i);
    await expect(page).toHaveURL(/focus=MONDO%3A0100135/);

    // List view and filters.
    await page.getByRole("radio", { name: "List" }).click();
    const list = page.getByTestId("atlas-list");
    await expect(list.getByTestId("atlas-list-row").first()).toBeVisible();
    await list.getByRole("textbox").fill("dravet");
    await expect(list.getByTestId("atlas-list-row").first()).toContainText(/dravet/i);
    await page.getByTestId("atlas-filters").click();
    await page.getByRole("checkbox", { name: /^Symptoms/ }).click();
    await page.keyboard.press("Escape");
    await expect(list.getByTestId("atlas-list-row").first()).toBeVisible();
    expect(problems()).toEqual([]);
  });

  test("guided tour at /atlas?tour=1", async ({ page }) => {
    const problems = trackProblems(page);
    await page.goto("/atlas?tour=1");
    const tour = page.getByTestId("atlas-tour");
    await expect(tour).toBeVisible({ timeout: 30_000 });
    await shot(page, "guest-tour-1");
    await expect(page.getByText("Drawing the map")).toBeHidden({ timeout: 30_000 });
    const next = page.getByTestId("tour-next");
    for (let i = 0; i < 10; i++) {
      const isLast = /Start exploring/.test((await next.textContent()) ?? "");
      await next.click();
      if (isLast) break;
      await expect(tour).toContainText(`${i + 2} of`);
    }
    await shot(page, "guest-tour-end");
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
