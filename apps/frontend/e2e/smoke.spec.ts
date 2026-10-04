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
      if (["/", "/privacy", "/about-data"].includes(route)) {
        await expect(page.getByRole("contentinfo")).toContainText("information, not medical advice");
      } else {
        // Application views drop the footer; Privacy and About this data stay in the header menus.
        await expect(page.getByRole("contentinfo")).toHaveCount(0);
      }
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

  test("signed-in user sees the account menu with their role, and no lens switcher", async ({ page }) => {
    await mockApi(page, { "GET /auth/session": signedInSession({ role: "researcher" }) });
    await page.goto("/atlas");
    await page.getByTestId("user-menu").click();
    await expect(page.getByRole("menu")).toContainText("Researcher");
    await expect(page.getByTestId("lens-switcher")).toHaveCount(0);
    await expect(page.getByTestId("privacy-menu")).toHaveCount(0);
  });

  test("a guest's old stored lens is ignored: guest wording and no errors", async ({ page }) => {
    await page.addInitScript(() => window.localStorage.setItem("amber.lens", "researcher"));
    await mockApi(page, { "GET /auth/session": guestSession, "GET /clusters": [] });
    const errors = trackConsoleErrors(page);
    await page.goto("/clusters");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Groups of related conditions");
    await expect(page.getByTestId("lens-switcher")).toHaveCount(0);
    expect(errors()).toEqual([]);
  });

  test("privacy and about this data stay reachable from the header without a footer", async ({ page }) => {
    await mockApi(page, { "GET /auth/session": guestSession });
    for (const route of ["/chat", "/atlas"]) {
      await page.goto(route);
      await page.getByTestId("privacy-menu").click();
      await expect(page.getByRole("menuitem", { name: "Privacy" })).toHaveAttribute("href", "/privacy");
      await expect(page.getByRole("menuitem", { name: "About this data" })).toHaveAttribute("href", "/about-data");
      await page.keyboard.press("Escape");
    }

    await page.unrouteAll({ behavior: "ignoreErrors" });
    await mockApi(page, { "GET /auth/session": signedInSession({ role: "patient" }) });
    await page.goto("/documents");
    await page.getByTestId("user-menu").click();
    await expect(page.getByRole("menuitem", { name: "Privacy and data" })).toHaveAttribute("href", "/privacy");
    await expect(page.getByRole("menuitem", { name: "About this data" })).toHaveAttribute("href", "/about-data");
  });

  test("header nav items stay on one line from 1024 px up, signed out and in", async ({ page }) => {
    for (const session of [guestSession, signedInSession({ role: "patient" })]) {
      await page.unrouteAll({ behavior: "ignoreErrors" });
      await mockApi(page, { "GET /auth/session": session });
      for (const width of [1024, 1100, 1280, 1440]) {
        await page.setViewportSize({ width, height: 800 });
        await page.goto("/atlas");
        const header = page.getByRole("banner");
        await expect(
          session.user ? header.getByTestId("user-menu") : header.getByRole("button", { name: "Continue with ChatGPT" }),
        ).toBeVisible();
        const links = header.getByRole("navigation", { name: "Primary" }).getByRole("link");
        await expect(links).toHaveCount(4);
        // One line: every item is one line tall, and the page does not scroll sideways.
        const heights = await links.evaluateAll((els) => els.map((el) => el.getBoundingClientRect().height));
        expect(Math.max(...heights) - Math.min(...heights), `nav items at ${width}px`).toBeLessThan(1);
        expect(Math.max(...heights), `nav items at ${width}px`).toBeLessThan(36);
        expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
      }
    }
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

test("privacy and about this data stay reachable from the phone menu for guests @mobile", async ({ page }) => {
  await mockApi(page, { "GET /auth/session": guestSession });
  for (const route of ["/chat", "/atlas"]) {
    await page.goto(route);
    await page.getByRole("button", { name: "Open menu" }).click();
    const menu = page.getByRole("dialog", { name: "Menu" });
    await expect(menu.getByRole("link", { name: "Privacy" })).toHaveAttribute("href", "/privacy");
    await expect(menu.getByRole("link", { name: "About this data" })).toHaveAttribute("href", "/about-data");
    await expect(menu.getByTestId("lens-switcher")).toHaveCount(0);
  }
  await page.getByRole("dialog", { name: "Menu" }).getByRole("link", { name: "About this data" }).click();
  await expect(page).toHaveURL(/\/about-data$/);
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
