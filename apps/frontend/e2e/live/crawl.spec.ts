/**
 * Live crawl: every page renders against the real API without console errors,
 * hydration warnings or failed requests, in light and dark.
 * Start the processes as described in live-helpers.ts, then `PORT=3106 pnpm test:e2e:live`.
 */
import { expect, test } from "@playwright/test";

import { IDS, setTheme, shot, trackProblems } from "./live-helpers";

const ROUTES = [
  "/",
  "/atlas",
  `/node/${encodeURIComponent(IDS.dee4)}`,
  `/node/${encodeURIComponent(IDS.stxbp1)}`,
  "/clusters",
  "/path",
  "/chat",
  "/documents",
  "/profile",
  "/privacy",
  "/about-data",
];

for (const theme of ["light", "dark"] as const) {
  test.describe(`crawl ${theme}`, () => {
    for (const route of ROUTES) {
      test(`${route}`, async ({ page }) => {
        await setTheme(page, theme);
        const problems = trackProblems(page);
        await page.goto(route);
        await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
        await page.waitForLoadState("networkidle");
        await shot(page, `crawl-${theme}-${route.replace(/[^a-z0-9]+/gi, "_")}`);
        expect(problems()).toEqual([]);
      });
    }
  });
}

test.describe("crawl mobile", () => {
  for (const route of ROUTES) {
    test(`${route} @mobile`, async ({ page }) => {
      const problems = trackProblems(page);
      await page.goto(route);
      await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
      await page.waitForLoadState("networkidle");
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      await shot(page, `crawl-mobile-${route.replace(/[^a-z0-9]+/gi, "_")}`);
      expect(overflow, "no horizontal page scroll").toBeLessThanOrEqual(1);
      expect(problems()).toEqual([]);
    });
  }
});
