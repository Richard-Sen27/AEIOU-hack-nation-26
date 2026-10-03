import { expect, test } from "@playwright/test";

import { errorEnvelope, mockApi, setTheme, shot, trackConsoleErrors } from "../helpers";
import { graphMocks } from "./fixtures";

test.describe("clusters", () => {
  test("lists clusters as inferred groups that open their cluster node", async ({ page }) => {
    await mockApi(page, graphMocks());
    const errors = trackConsoleErrors(page);
    await page.goto("/clusters");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const cards = page.getByTestId("cluster-card");
    await expect(cards).toHaveCount(3);
    const first = cards.first();
    await expect(first.getByTestId("origin-badge")).toHaveAttribute("data-origin", "inferred");
    await expect(first).toContainText("members");
    await expect(first).toContainText("written by analysis");
    await first.getByRole("heading").getByRole("link").click();
    await expect(page).toHaveURL(/\/node\/CLUSTER%3A1$/);
    await expect(page.getByRole("heading", { level: 1, name: "Sodium channel gain-of-function epilepsies" })).toBeVisible();
    // Its neighbourhood is its members.
    await expect(page.getByTestId("cluster-members")).toContainText("SCN8A developmental");
    await page.getByRole("radio", { name: "List" }).click();
    await expect(page.getByTestId("node-list")).toContainText("SCN8A developmental");
    expect(errors()).toEqual([]);
  });

  test("wording follows the lens", async ({ page }) => {
    await mockApi(page, graphMocks());
    await page.goto("/clusters");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Groups of related conditions");
    await page.getByTestId("lens-switcher").click();
    await page.getByRole("menuitemradio", { name: /Researcher/ }).click();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Mechanism clusters");
    await expect(page.getByTestId("cluster-card").first()).toContainText("HGNC:");
  });

  test("empty and error states", async ({ page }) => {
    await mockApi(page, graphMocks({ "GET /clusters": [] }));
    await page.goto("/clusters");
    await expect(page.getByTestId("clusters-empty")).toBeVisible();
    await mockApi(page, graphMocks({ "GET /clusters": errorEnvelope(501, "not_implemented") }));
    await page.reload();
    await expect(page.getByTestId("clusters-error")).toContainText("not available yet");
  });

  test("screenshots: light and dark", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockApi(page, graphMocks());
    for (const theme of ["light", "dark"] as const) {
      await setTheme(page, theme);
      await page.goto("/clusters");
      await expect(page.getByTestId("cluster-card").first()).toBeVisible();
      await shot(page, `clusters-${theme}-desktop`);
    }
  });
});

test("clusters on a phone @mobile", async ({ page }) => {
  await mockApi(page, graphMocks());
  await page.goto("/clusters");
  await expect(page.getByTestId("cluster-card").first()).toBeVisible();
  await shot(page, "clusters-mobile", { fullPage: true });
});
