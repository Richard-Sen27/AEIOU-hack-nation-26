import { expect, test } from "@playwright/test";

import {
  guestSession,
  hit,
  mockApi,
  setTheme,
  shot,
  signedInSession,
  trackConsoleErrors,
} from "./helpers";

const ROUTES = [
  "/",
  "/atlas",
  "/node/MONDO%3A0100135",
  "/clusters",
  "/path",
  "/chat",
  "/documents",
  "/documents/doc-1",
  "/profile",
  "/welcome",
  "/privacy",
  "/about-data",
];

test.describe("shell", () => {
  for (const route of ROUTES) {
    test(`renders ${route} with the API down`, async ({ page }) => {
      await mockApi(page, {}); // everything offline
      const errors = trackConsoleErrors(page);
      await page.goto(route);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expect(page.getByRole("link", { name: /Amber/ }).first()).toBeVisible();
      await expect(page.getByRole("contentinfo")).toContainText("information, not medical advice");
      expect(errors()).toEqual([]);
    });
  }

  test("unknown route shows not-found", async ({ page }) => {
    await mockApi(page, { "GET /auth/session": guestSession });
    await page.goto("/no-such-page");
    await expect(page.getByRole("heading", { name: /not on the map/ })).toBeVisible();
  });

  test("global search shows the matched synonym and opens the node", async ({ page }) => {
    await mockApi(page, {
      "GET /auth/session": guestSession,
      "GET /search": { results: [hit("MONDO:0100135", "disease", "STXBP1 encephalopathy", "Ohtahara syndrome")] },
    });
    await page.goto("/atlas");
    await page.keyboard.press("ControlOrMeta+k");
    const dialog = page.getByTestId("global-search");
    await expect(dialog).toBeVisible();
    await page.getByRole("combobox", { name: "Search the atlas" }).fill("Ohtahara");
    await expect(dialog.getByText("Ohtahara syndrome")).toBeVisible();
    await expect(dialog.getByText("STXBP1 encephalopathy")).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/node\/MONDO%3A0100135$/);
  });

  test("long free text is never sent to GET /search", async ({ page }) => {
    const searched: string[] = [];
    await mockApi(page, {
      "GET /auth/session": guestSession,
      "GET /search": (req: { url: string }) => {
        searched.push(req.url);
        return { results: [] };
      },
    });
    await page.goto("/atlas");
    await page.getByTestId("search-trigger").click();
    await page.getByRole("combobox", { name: "Search the atlas" }).fill("My daughter is 2 and has lots of seizures");
    await expect(page.getByText("reads like a description")).toBeVisible();
    await page.waitForTimeout(400);
    expect(searched).toEqual([]);
  });

  test("guest gets the sign-in dialog with the notice at collection", async ({ page }) => {
    await mockApi(page, { "GET /auth/session": guestSession });
    await page.goto("/");
    await page.getByRole("textbox", { name: /Describe the diagnosis/ }).fill("My son was diagnosed with Dravet last year");
    await page.keyboard.press("Enter");
    const dialog = page.getByTestId("sign-in-dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Continue with ChatGPT" })).toBeVisible();
    await expect(dialog).toContainText("16 or older");
    await expect(dialog).toContainText("Nothing is sold or shared");
    await expect(dialog.getByRole("link", { name: "Privacy notice" })).toHaveAttribute("href", "/privacy");
  });

  test("signed-in user sees the account menu and their lens", async ({ page }) => {
    await mockApi(page, { "GET /auth/session": signedInSession({ role: "researcher" }) });
    await page.goto("/atlas");
    await expect(page.getByTestId("user-menu")).toBeVisible();
    await expect(page.getByTestId("lens-switcher")).toContainText("Researcher");
  });

  test("screenshots: light and dark", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockApi(page, {
      "GET /auth/session": guestSession,
      "GET /search": { results: [
        hit("MONDO:0100135", "disease", "STXBP1 encephalopathy", "Ohtahara syndrome"),
        hit("HGNC:11444", "gene", "STXBP1"),
        hit("HP:0012469", "phenotype", "Infantile spasms"),
      ] },
    });
    for (const theme of ["light", "dark"] as const) {
      await setTheme(page, theme);
      await page.goto("/");
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await shot(page, `landing-${theme}-desktop`);
      await page.goto("/chat");
      await shot(page, `chat-${theme}-desktop`);
      await page.keyboard.press("ControlOrMeta+k");
      await page.getByRole("combobox", { name: "Search the atlas" }).fill("STXBP1");
      await expect(page.getByTestId("global-search").getByText("Infantile spasms")).toBeVisible();
      await shot(page, `search-${theme}-desktop`);
      await page.keyboard.press("Escape");
      await page.goto("/");
      await page.getByRole("textbox", { name: /Describe the diagnosis/ }).fill("My son has seizures every night");
      await page.keyboard.press("Enter");
      await expect(page.getByTestId("sign-in-dialog")).toBeVisible();
      await shot(page, `sign-in-${theme}-desktop`);
    }
  });
});

test("mobile shell @mobile", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockApi(page, { "GET /auth/session": guestSession });
  const errors = trackConsoleErrors(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await shot(page, "landing-mobile");
  await page.getByRole("button", { name: "Open menu" }).click();
  await expect(page.getByRole("link", { name: "Ask Dr. Wu" })).toBeVisible();
  await shot(page, "menu-mobile");
  expect(errors()).toEqual([]);
});
