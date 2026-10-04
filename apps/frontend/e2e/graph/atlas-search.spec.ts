import { expect, test, type Page } from "@playwright/test";

import { hit, mockApi, setTheme, shot, trackConsoleErrors } from "../helpers";
import { graphMocks } from "./fixtures";

async function openAtlas(page: Page) {
  await page.goto("/atlas");
  const search = page.getByTestId("atlas-search");
  await expect(search).toBeVisible();
  return { search, input: search.getByRole("combobox", { name: "Search the map" }) };
}

test.describe("search the map", () => {
  test("matches groups and entities locally, with type and breadcrumb", async ({ page }) => {
    await mockApi(page, graphMocks({ "GET /search": { results: [] } }));
    const errors = trackConsoleErrors(page);
    const { search, input } = await openAtlas(page);

    await input.focus();
    await expect(search).toContainText("Type a name");

    await input.fill("seiz");
    // "Seizure" is a symptom and also the branch its kinds sit under.
    const seizure = search.locator('[data-node-id="HP:0001250"]');
    await expect(seizure).toContainText("Symptom");
    await expect(seizure).toContainText("Symptoms");
    await expect(search.locator('[data-node-id="HP:0002373"]')).toContainText("Seizure");

    await input.fill("chromosome");
    const group = search.locator('[data-node-id="T:genes/chr2"]');
    await expect(group).toContainText("Chromosome 2");
    await expect(group).toContainText("Group");
    await expect(group).toContainText("Genes");
    expect(errors()).toEqual([]);
  });

  test("is operable with the keyboard and picks a result", async ({ page }) => {
    await mockApi(page, graphMocks({ "GET /search": { results: [] } }));
    const { search, input } = await openAtlas(page);

    await input.focus();
    await input.fill("scn");
    await expect(input).toHaveAttribute("aria-expanded", "true");
    const options = search.getByRole("option");
    await expect(options.first()).toBeVisible();
    const n = await options.count();
    expect(n).toBeGreaterThan(1);

    await page.keyboard.press("ArrowDown");
    await expect(options.nth(0)).toHaveAttribute("aria-selected", "true");
    await expect(input).toHaveAttribute("aria-activedescendant", (await options.nth(0).getAttribute("id"))!);
    await page.keyboard.press("End");
    await expect(options.nth(n - 1)).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("Home");
    await expect(options.nth(0)).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("ArrowUp");
    await expect(options.nth(n - 1)).toHaveAttribute("aria-selected", "true");

    await page.keyboard.press("Escape");
    await expect(input).toHaveAttribute("aria-expanded", "false");
    await expect(input).toHaveValue("scn");
    await page.keyboard.press("Escape");
    await expect(input).toHaveValue("");

    await input.fill("stxbp1 ence");
    const target = search.locator('[data-node-id="MONDO:9900007"]');
    await expect(target).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(input).toHaveValue("");
    await expect(input).toHaveAttribute("aria-expanded", "false");
    await expect(page).toHaveURL(/focus=MONDO%3A9900007|focus=MONDO:9900007/);
  });

  test("merges synonym matches from the server and marks those not on the map", async ({ page }) => {
    const queries: string[] = [];
    await mockApi(
      page,
      graphMocks({
        "GET /search": ({ url }: { url: string }) => {
          queries.push(new URL(url).searchParams.get("q") ?? "");
          return {
            json: {
              results: [
                hit("MONDO:0100135", "disease", "Dravet syndrome", "Severe myoclonic epilepsy of infancy"),
                hit("MONDO:NOT-ON-MAP", "disease", "Not on the map"),
              ],
            },
          };
        },
      }),
    );
    const { search, input } = await openAtlas(page);
    await input.fill("severe myoclonic");
    const dravet = search.locator('[data-node-id="MONDO:0100135"]');
    await expect(dravet).toContainText("Severe myoclonic epilepsy of infancy");
    await expect(dravet).toContainText("Dravet syndrome");
    await expect(dravet).toContainText("Conditions");
    const offMap = search.locator('[data-node-id="MONDO:NOT-ON-MAP"]');
    await expect(offMap).toHaveAttribute("data-offmap", "true");
    await expect(offMap.getByTestId("atlas-offmap")).toHaveText("Not on the map yet");
    await expect(dravet.getByTestId("atlas-offmap")).toHaveCount(0);
    // Debounced: one request for the settled query, not one per keystroke.
    expect(queries).toEqual(["severe myoclonic"]);
  });

  test("offers Dr. Wu for descriptions and never sends them to search", async ({ page }) => {
    const urls: string[] = [];
    page.on("request", (r) => urls.push(r.url()));
    let searched = 0;
    await mockApi(page, graphMocks({ "GET /search": () => ((searched += 1), { json: { results: [] } }) }));
    const { search, input } = await openAtlas(page);

    const text = "my daughter has seizures when she has a fever";
    await input.fill(text);
    const ask = search.getByTestId("atlas-search-ask");
    await expect(ask).toContainText("Ask Dr. Wu");
    await expect(ask).toContainText("reads like a description");
    await page.waitForTimeout(500);
    expect(searched).toBe(0);

    await page.keyboard.press("ArrowDown");
    await expect(ask).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("Enter");
    await expect(input).toHaveValue("");
    expect(urls.some((u) => u.includes("daughter") || u.includes("fever"))).toBe(false);
    expect(page.url()).not.toContain("daughter");
  });

  test("says when nothing matches", async ({ page }) => {
    await mockApi(page, graphMocks({ "GET /search": { results: [] } }));
    const { search, input } = await openAtlas(page);
    await input.fill("zzqx");
    await expect(search).toContainText("Nothing on the map by that name");
    await expect(search.getByTestId("atlas-search-ask")).toBeVisible();
  });

  test("screenshots", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockApi(page, graphMocks({ "GET /search": { results: [] } }));
    for (const theme of ["light", "dark"] as const) {
      await setTheme(page, theme);
      const { search, input } = await openAtlas(page);
      await input.fill("seiz");
      await expect(search.getByTestId("atlas-search-option").first()).toBeVisible();
      await shot(page, `atlas-search-${theme}-desktop`);
    }
  });
});

test("search on a phone @mobile", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockApi(page, graphMocks({ "GET /search": { results: [] } }));
  const { search, input } = await openAtlas(page);
  await input.fill("seiz");
  await expect(search.getByTestId("atlas-search-option").first()).toBeVisible();
  const box = await search.boundingBox();
  const vw = page.viewportSize()!.width;
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(vw);
  await shot(page, "atlas-search-mobile");
});
