import { expect, test } from "@playwright/test";

import { errorEnvelope, mockApi, setTheme, shot, trackConsoleErrors } from "../helpers";
import { graphMocks, largeAtlas } from "./fixtures";

test.describe("atlas", () => {
  test("renders the map, legend and counts", async ({ page }) => {
    await mockApi(page, graphMocks());
    const errors = trackConsoleErrors(page);
    await page.goto("/atlas");
    await expect(page.getByRole("heading", { level: 1, name: "Atlas" })).toBeVisible();
    await expect(page.getByTestId("atlas-counts")).toContainText("69 items");
    await expect(page.getByTestId("atlas-canvas").locator("canvas").first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("graph-legend")).toBeVisible();
    expect(errors()).toEqual([]);
  });

  test("?focus= selects a node and shows its summary", async ({ page }) => {
    await mockApi(page, graphMocks());
    const errors = trackConsoleErrors(page);
    await page.goto("/atlas?focus=MONDO%3A0100135");
    const panel = page.getByTestId("atlas-panel");
    await expect(panel).toBeVisible();
    await expect(panel.getByRole("heading", { name: "Dravet syndrome" })).toBeVisible();
    await expect(panel).toContainText("Severe childhood epilepsy");
    await expect(panel.getByTestId("edge-trust-row").first()).toBeVisible();
    await expect(page.getByTestId("atlas-open-node")).toHaveAttribute("href", "/node/MONDO%3A0100135");
    await panel.getByRole("button", { name: "Close summary" }).click();
    await expect(panel).toBeHidden();
    await expect(page).not.toHaveURL(/focus=/);
    expect(errors()).toEqual([]);
  });

  test("unknown focus id says so", async ({ page }) => {
    await mockApi(page, graphMocks());
    await page.goto("/atlas?focus=MONDO%3A404");
    await expect(page.getByTestId("atlas-missing-focus")).toContainText("MONDO:404");
  });

  test("find on map focuses a node", async ({ page }) => {
    await mockApi(page, graphMocks());
    await page.goto("/atlas");
    await page.getByTestId("atlas-find").click();
    await page.getByRole("combobox", { name: "Find on the map" }).fill("STXBP1 Par");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("atlas-panel").getByRole("heading", { level: 2 })).toHaveText("STXBP1 Parents Group (fixture)");
    await expect(page).toHaveURL(/focus=ORG%3Afx-stxbp1-parents/);
  });

  test("list view is the same data, keyboard operable", async ({ page }) => {
    await mockApi(page, graphMocks());
    const errors = trackConsoleErrors(page);
    await page.goto("/atlas");
    await page.getByRole("radio", { name: "List" }).click();
    const list = page.getByTestId("atlas-list");
    await expect(list.getByTestId("atlas-list-row")).toHaveCount(69);
    await list.getByRole("textbox").fill("dravet");
    await expect(list.getByTestId("atlas-list-row").first()).toBeVisible();
    await expect(list.getByTestId("atlas-list-row")).not.toHaveCount(69);
    await list.getByRole("button", { name: "Dravet syndrome", exact: true }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("atlas-panel").getByRole("heading", { level: 2 })).toHaveText("Dravet syndrome");
    expect(errors()).toEqual([]);
  });

  test("filters hide node types in the list", async ({ page }) => {
    await mockApi(page, graphMocks());
    await page.goto("/atlas");
    await page.getByRole("radio", { name: "List" }).click();
    await page.getByTestId("atlas-filters").click();
    await page.getByRole("checkbox", { name: /^Symptoms/ }).click();
    await expect(page.getByTestId("atlas-list").getByTestId("atlas-list-row")).toHaveCount(58);
  });

  test("empty graph shows a clear state", async ({ page }) => {
    await mockApi(page, graphMocks({ "GET /atlas.json": { nodes: [], edges: [], clusters: [] } }));
    await page.goto("/atlas");
    await expect(page.getByTestId("atlas-empty")).toContainText("empty");
  });

  test("failed load shows an error with retry", async ({ page }) => {
    let fail = true;
    await mockApi(
      page,
      graphMocks({
        "GET /atlas.json": () => (fail ? errorEnvelope(500, "internal_error") : { json: { nodes: [], edges: [] } }),
      }),
    );
    await page.goto("/atlas");
    await expect(page.getByTestId("atlas-error")).toContainText("could not be loaded");
    fail = false;
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByTestId("atlas-empty")).toBeVisible();
  });

  test("API down and not implemented degrade gracefully", async ({ page }) => {
    await mockApi(page, { "GET /auth/session": { user: null } });
    await page.goto("/atlas");
    await expect(page.getByTestId("atlas-error")).toContainText("can't be reached");
    await mockApi(page, graphMocks({ "GET /atlas.json": errorEnvelope(501, "not_implemented") }));
    await page.reload();
    await expect(page.getByTestId("atlas-error")).toContainText("not available yet");
  });

  test("3,000 nodes and 20,000 edges render and stay interactive", async ({ page }) => {
    test.setTimeout(120_000);
    const big = largeAtlas(3000, 20000);
    await mockApi(page, graphMocks({ "GET /atlas.json": big }));
    const errors = trackConsoleErrors(page);
    await page.goto("/atlas");
    await expect(page.getByTestId("atlas-counts")).toContainText("3,000 items · 20,000 connections");
    const canvas = page.getByTestId("atlas-canvas");
    await expect(canvas.locator("canvas").first()).toBeVisible({ timeout: 30_000 });
    const box = (await canvas.boundingBox())!;
    // Wheel-zoom and drag; the main thread must stay responsive.
    const t0 = Date.now();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.wheel(0, -400);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 120, box.y + box.height / 2 + 60, { steps: 8 });
    await page.mouse.up();
    const frame = await page.evaluate(
      () =>
        new Promise<number>((resolve) => {
          const s = performance.now();
          requestAnimationFrame(() => requestAnimationFrame(() => resolve(performance.now() - s)));
        }),
    );
    // Generous: CI renders WebGL in software (SwiftShader).
    expect(frame).toBeLessThan(1500);
    // Focus via the URL-free path: find and select.
    await page.getByTestId("atlas-find").click();
    await page.getByRole("combobox", { name: "Find on the map" }).fill("Synthetic item 1234");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("atlas-panel").getByRole("heading", { level: 2 })).toHaveText("Synthetic item 1234");
    expect(Date.now() - t0).toBeLessThan(60_000);
    await shot(page, "atlas-large-desktop");
    expect(errors()).toEqual([]);
  });

  test("screenshots: light and dark", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockApi(page, graphMocks());
    for (const theme of ["light", "dark"] as const) {
      await setTheme(page, theme);
      await page.goto("/atlas");
      await expect(page.getByTestId("atlas-canvas").locator("canvas").first()).toBeVisible({ timeout: 30_000 });
      await page.waitForTimeout(400);
      await shot(page, `atlas-${theme}-desktop`);
      await page.goto("/atlas?focus=MONDO%3A9900003");
      await expect(page.getByTestId("atlas-panel")).toContainText("connection");
      await page.waitForTimeout(400);
      await shot(page, `atlas-focus-${theme}-desktop`);
    }
  });
});

test("atlas on a phone @mobile", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockApi(page, graphMocks());
  const errors = trackConsoleErrors(page);
  await page.goto("/atlas?focus=MONDO%3A0100135");
  await expect(page.getByTestId("atlas-panel")).toBeVisible();
  await page.waitForTimeout(400);
  await shot(page, "atlas-mobile");
  await page.getByRole("button", { name: "Close summary" }).click();
  await page.getByRole("radio", { name: "List" }).click();
  await shot(page, "atlas-list-mobile");
  expect(errors()).toEqual([]);
});
