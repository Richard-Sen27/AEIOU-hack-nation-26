/**
 * Live guest journey on paths: supported route with alternatives, family
 * filter, cached explanation, evidence sheet, a pair with no supported route
 * (coverage report), graph export, privacy and about-data pages.
 * Start the processes as described in live-helpers.ts, then `PORT=3106 pnpm test:e2e:live`.
 */
import { expect, test } from "@playwright/test";

import { API, IDS, shot, trackProblems } from "./live-helpers";

// Dravet syndrome → GEFS+ via SCN1A: a demo path with precomputed explanations.
const CACHED = "/path?from=MONDO%3A0100135&to=MONDO%3A0018214";
// DEE4 → a disease with no supported DNA route.
const NO_ROUTE = "/path?from=MONDO%3A0012812&to=MONDO%3A0011297&family=dna";

test.describe("guest path journey", () => {
  test("supported route, alternatives, family filter and cached explanation", async ({ page }) => {
    const problems = trackProblems(page);
    await page.goto(CACHED);
    await expect(page.getByTestId("path-result")).toBeVisible({ timeout: 30_000 });
    const flow = page.getByTestId("path-flow");
    await expect(flow.getByTestId("flow-node").first()).toHaveAttribute("data-node-id", "MONDO:0100135");
    await expect(flow.getByTestId("flow-node").last()).toHaveAttribute("data-node-id", "MONDO:0018214");
    await expect(page.getByTestId("path-steps").getByTestId("path-step").first().getByTestId("confidence-badge")).toBeVisible();

    const explanation = page.getByTestId("explanation");
    await expect(explanation.getByTestId("explanation-cached")).toBeVisible({ timeout: 30_000 });
    await expect(explanation.getByTestId("explanation-text")).not.toBeEmpty();
    await expect(explanation.getByTestId("explanation-text")).not.toContainText("[e_");
    await expect(explanation.getByText("AI-generated · Dr. Wu")).toBeVisible();
    await shot(page, "guest-path");

    // Alternatives.
    const options = page.getByTestId("route-option");
    expect(await options.count()).toBeGreaterThan(1);
    await page.getByRole("radio", { name: /Route 2/ }).check({ force: true });
    await expect(options.nth(1)).toHaveAttribute("data-selected", "true");

    // Evidence for a step.
    await page.getByTestId("path-steps").getByTestId("open-evidence").first().click();
    const sheet = page.getByTestId("evidence-sheet");
    await expect(sheet.getByTestId("evidence-list")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(sheet).toBeHidden();

    // Family filter keeps the pair and changes the query.
    await page.getByTestId("family-filter").getByText("Shared biology").click();
    await expect(page).toHaveURL(/family=dna/);
    await expect(page.getByTestId("path-result").or(page.getByTestId("no-route"))).toBeVisible({ timeout: 30_000 });
    expect(problems()).toEqual([]);
  });

  test("a pair with no supported route shows the coverage report", async ({ page }) => {
    const problems = trackProblems(page);
    await page.goto(NO_ROUTE);
    await expect(page.getByTestId("coverage-report")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("no-route-statement")).toBeVisible();
    await expect(page.getByTestId("sources-queried")).toContainText(/pubmed|PubMed/);
    await expect(page.getByTestId("suggested-question")).not.toBeEmpty();
    await expect(page.getByTestId("action-view")).toHaveCount(0);
    // Guests are asked to sign in before gap search.
    await page.getByTestId("gap-start").click();
    await expect(page.getByTestId("sign-in-dialog")).toBeVisible();
    await shot(page, "guest-no-route");
    expect(problems()).toEqual([]);
  });

  test("graph export downloads CSV and GraphML", async ({ page }) => {
    const problems = trackProblems(page);
    await page.goto(`/node/${encodeURIComponent(IDS.stxbp1)}`);
    await page.getByTestId("export").click();
    for (const [id, ext] of [["export-csv", ".csv"], ["export-graphml", ".graphml"]] as const) {
      const href = await page.getByTestId(id).getAttribute("href");
      expect(href).toContain(`${API}/export/graph`);
      const download = page.waitForEvent("download");
      await page.getByTestId(id).click();
      const d = await download;
      expect(d.suggestedFilename()).toMatch(new RegExp(`\\${ext}$`));
      const res = await page.request.get(href!);
      expect(res.ok()).toBeTruthy();
      expect((await res.text()).length).toBeGreaterThan(100);
    }
    expect(problems()).toEqual([]);
  });

  test("privacy and about-data notices", async ({ page }) => {
    const problems = trackProblems(page);
    await page.goto("/privacy");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.locator("main")).toContainText(/Global Privacy Control/i);
    await page.goto("/about-data");
    await expect(page.locator("main")).toContainText(/claim|remove/i);
    expect(problems()).toEqual([]);
  });
});
