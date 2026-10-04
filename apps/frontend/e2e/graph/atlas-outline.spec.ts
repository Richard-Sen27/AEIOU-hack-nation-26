import { expect, test, type Page } from "@playwright/test";

import { mockApi, setTheme, shot, trackConsoleErrors } from "../helpers";
import { graphMocks } from "./fixtures";

async function openOutline(page: Page, url = "/atlas") {
  await page.goto(url);
  await page.getByTestId("view-toggle").getByRole("radio", { name: "List" }).click();
  const outline = page.getByTestId("atlas-outline");
  await expect(outline).toBeVisible();
  return { outline, tree: outline.getByRole("tree") };
}

const item = (page: Page, id: string) => page.locator(`[data-testid="atlas-outline-item"][data-id="${id}"]`);

test.describe("outline view", () => {
  test("shows the nine trees as a collapsed treeview", async ({ page }) => {
    await mockApi(page, graphMocks());
    const errors = trackConsoleErrors(page);
    const { outline, tree } = await openOutline(page);
    const rows = outline.getByTestId("atlas-outline-item");
    await expect(rows).toHaveCount(9);
    await expect(rows.first()).toHaveAttribute("role", "treeitem");
    await expect(rows.first()).toHaveAttribute("aria-level", "1");
    await expect(rows.first()).toHaveAttribute("aria-expanded", "false");
    await expect(rows.first()).toHaveAttribute("tabindex", "0");
    await expect(tree.locator('[tabindex="0"]')).toHaveCount(1);
    await expect(item(page, "T:diseases")).toContainText("Conditions");
    expect(errors()).toEqual([]);
  });

  test("arrows, Home/End, typeahead and Enter", async ({ page }) => {
    await mockApi(page, graphMocks());
    const { outline } = await openOutline(page);
    const rows = outline.getByTestId("atlas-outline-item");

    await item(page, "T:researchers").focus();
    await page.keyboard.press("End");
    await expect(item(page, "T:doctors")).toBeFocused();
    await page.keyboard.press("Home");
    await expect(item(page, "T:researchers")).toBeFocused();

    // Typeahead: "g" jumps to the genes tree.
    await page.keyboard.press("g");
    await expect(item(page, "T:genes")).toBeFocused();
    await page.keyboard.press("ArrowRight");
    await expect(item(page, "T:genes")).toHaveAttribute("aria-expanded", "true");
    await page.keyboard.press("ArrowRight");
    await expect(item(page, "T:genes/chr2")).toBeFocused();
    await expect(item(page, "T:genes/chr2")).toHaveAttribute("aria-level", "2");
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowDown");
    const gene = page.locator('[data-testid="atlas-outline-item"][aria-level="3"]').first();
    await expect(gene).toBeFocused();
    await page.keyboard.press("ArrowLeft");
    await expect(item(page, "T:genes/chr2")).toBeFocused();
    await page.keyboard.press("ArrowLeft");
    await expect(item(page, "T:genes/chr2")).toHaveAttribute("aria-expanded", "false");
    await page.keyboard.press("ArrowLeft");
    await expect(item(page, "T:genes")).toBeFocused();

    // Enter selects: the view marks it and writes ?focus= for entities.
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowDown");
    const first = page.locator('[data-testid="atlas-outline-item"][aria-level="3"]').first();
    const id = (await first.getAttribute("data-id"))!;
    await expect(first).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(first).toHaveAttribute("aria-selected", "true");
    await expect(page).toHaveURL(new RegExp(`focus=${encodeURIComponent(id)}`));
    expect(await rows.count()).toBeGreaterThan(9);
  });

  test("filters by name and reveals the matches", async ({ page }) => {
    await mockApi(page, graphMocks());
    const { outline } = await openOutline(page);
    await outline.getByTestId("atlas-outline-filter").fill("febrile");
    await expect(outline.getByTestId("atlas-outline-status")).toContainText("2 matches");
    // Ancestors are shown open: Symptoms › Seizure › Febrile seizure.
    await expect(item(page, "T:symptoms")).toHaveAttribute("aria-expanded", "true");
    await expect(item(page, "HP:0001250")).toHaveAttribute("aria-expanded", "true");
    await expect(item(page, "HP:0002373")).toHaveAttribute("aria-level", "3");
    await expect(item(page, "T:researchers")).toHaveCount(0);

    await outline.getByTestId("atlas-outline-filter").fill("zzqx");
    await expect(outline).toContainText("Nothing matches");
  });

  test("reveals and marks the selected node", async ({ page }) => {
    await mockApi(page, graphMocks());
    const { outline } = await openOutline(page, "/atlas?focus=HP%3A0012469");
    const selected = item(page, "HP:0012469");
    await expect(selected).toBeVisible();
    await expect(selected).toHaveAttribute("aria-selected", "true");
    await expect(selected).toHaveAttribute("tabindex", "0");
    await expect(item(page, "HP:0001250")).toHaveAttribute("aria-expanded", "true");
    await expect(outline.locator('[aria-selected="true"]')).toHaveCount(1);
  });

  test("screenshots", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockApi(page, graphMocks());
    for (const theme of ["light", "dark"] as const) {
      await setTheme(page, theme);
      await openOutline(page, "/atlas?focus=HP%3A0012469");
      await expect(item(page, "HP:0012469")).toBeVisible();
      await shot(page, `atlas-outline-${theme}-desktop`);
    }
  });
});

test("outline on a phone @mobile", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockApi(page, graphMocks());
  await openOutline(page, "/atlas?focus=HP%3A0012469");
  await expect(item(page, "HP:0012469")).toBeVisible();
  const width = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(width).toBeLessThanOrEqual(page.viewportSize()!.width);
  await shot(page, "atlas-outline-mobile");
});
