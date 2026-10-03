import { expect, test, type Page } from "@playwright/test";

import { guestSession, mockApi, setTheme, shot, trackConsoleErrors } from "../helpers";

/** Heading levels never skip (h1 → h2 → h3), and there is exactly one h1. */
async function expectHeadingsInOrder(page: Page) {
  const levels = await page
    .locator("main")
    .locator("h1, h2, h3, h4, h5, h6")
    .evaluateAll((els) => els.map((e) => Number(e.tagName.slice(1))));
  expect(levels[0]).toBe(1);
  expect(levels.filter((l) => l === 1)).toHaveLength(1);
  for (let i = 1; i < levels.length; i++) expect(levels[i] - levels[i - 1]).toBeLessThanOrEqual(1);
}

async function expectNoForbiddenClaims(page: Page) {
  const text = (await page.locator("body").innerText()).toLowerCase();
  expect(text).not.toContain("hipaa compliant");
  expect(text).not.toMatch(/medically certified|certified medical device|fda[- ]approved/);
}

test("privacy notice: layered, all required sections, no forbidden claims", async ({ page }) => {
  await mockApi(page, { "GET /auth/session": guestSession });
  const errors = trackConsoleErrors(page);
  await page.goto("/privacy");
  await expect(page.getByRole("heading", { level: 1, name: "Privacy notice" })).toBeVisible();
  for (const name of [
    "The short version",
    "Who is responsible",
    "What we collect",
    "Why, and on which legal basis",
    "What we never do",
    "Who receives data",
    "How long we keep it",
    "Your rights",
    "California residents",
    "Children",
    "AI transparency",
    "Security and incidents",
    "Contact and complaints",
  ]) {
    await expect(page.getByRole("heading", { level: 2, name, exact: true })).toBeVisible();
  }
  const body = page.locator("main");
  await expect(body).toContainText("Health and genetic data (special category)");
  await expect(body).toContainText("We never sell");
  await expect(body).toContainText("No training of AI models");
  await expect(body).toContainText("Global Privacy Control");
  await expect(body).toContainText("10 business days");
  await expect(body).toContainText("45 days");
  await expect(body).toContainText("Non-discrimination");
  await expect(body).toContainText("72 hours");
  await expect(body).toContainText("16 or older");
  // Without NEXT_PUBLIC_PRIVACY_EMAIL the contact is a marked placeholder, never invented.
  await expect(page.getByTestId("to-be-completed").first()).toBeVisible();
  await expectHeadingsInOrder(page);
  await expectNoForbiddenClaims(page);
  expect(errors()).toEqual([]);
});

test("about this data: sources, licences, labels, version and claim-or-remove", async ({ page }) => {
  await mockApi(page, { "GET /auth/session": { ...guestSession, data_version: "2026.10.03-a1b2c3" } });
  const errors = trackConsoleErrors(page);
  await page.goto("/about-data");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const main = page.locator("main");
  for (const src of ["MONDO", "HGNC", "Human Phenotype Ontology", "ClinVar", "ClinGen", "Reactome", "Gene Ontology", "Orphanet", "PubMed", "ClinicalTrials.gov", "NIH RePORTER", "Patient-organisation websites"]) {
    await expect(main).toContainText(src);
  }
  await expect(main).toContainText("CC BY 4.0, Orphanet");
  await expect(page.getByTestId("data-version")).toHaveText("2026.10.03-a1b2c3");
  await expect(page.getByRole("heading", { name: "People in the atlas" })).toBeVisible();
  await expect(main).toContainText("Art. 14");
  await expect(main).toContainText("There is no in-app form for this yet.");
  await expect(main.getByTestId("origin-badge").first()).toBeVisible();
  await expectHeadingsInOrder(page);
  await expectNoForbiddenClaims(page);
  expect(errors()).toEqual([]);
});

test("screenshots: notices light and dark", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockApi(page, { "GET /auth/session": { ...guestSession, data_version: "2026.10.03-a1b2c3" } });
  for (const theme of ["light", "dark"] as const) {
    await setTheme(page, theme);
    await page.goto("/privacy");
    await shot(page, `account-privacy-${theme}`, { fullPage: true });
    await page.goto("/about-data");
    await expect(page.getByTestId("data-version")).toBeVisible();
    await shot(page, `account-about-data-${theme}`, { fullPage: true });
  }
});

test("notices on a phone @mobile", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockApi(page, { "GET /auth/session": guestSession });
  await page.goto("/privacy");
  await shot(page, "account-privacy-mobile", { fullPage: true });
  await page.goto("/about-data");
  await shot(page, "account-about-data-mobile", { fullPage: true });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  expect(overflow).toBe(false);
});
