import { readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { guestSession, mockApi, setTheme, signedInSession, trackConsoleErrors } from "../helpers";

/** Screenshots go outside the repository: GUIDE_SHOTS=<dir>; skipped when unset. */
const SHOTS = process.env.GUIDE_SHOTS;

/** Route patterns of the app, read from src/app (`[id]` matches one segment). */
function appRoutes(): RegExp[] {
  const root = join(__dirname, "..", "..", "src", "app");
  const out: RegExp[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const p = join(dir, name);
      if (statSync(p).isDirectory()) walk(p);
      else if (name === "page.tsx") {
        const rel = relative(root, dir).split(sep).filter((s) => s && !s.startsWith("("));
        const pattern = rel.map((s) => (s.startsWith("[") ? "[^/]+" : s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))).join("/");
        out.push(new RegExp(`^/${pattern}$`));
      }
    }
  };
  walk(root);
  return out;
}

const SECTIONS = ["Explore the atlas", "Ask Dr. Wu", "Your account", "Studies", "For doctors and researchers", "Messages", "Trust and privacy"];

async function expectGuide(page: Page) {
  await expect(page.getByRole("heading", { level: 1, name: "Getting started with Amber" })).toBeVisible();
  for (const s of SECTIONS) await expect(page.getByRole("heading", { level: 2, name: s })).toBeVisible();
  expect(await page.getByTestId("guide-feature").count()).toBeGreaterThanOrEqual(25);
}

async function noSidewaysScroll(page: Page) {
  const { scroll, client } = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }));
  expect(scroll).toBeLessThanOrEqual(client);
}

test.describe("guide", () => {
  test("a guest reads it, and every Try it link opens an existing page", async ({ page, request }) => {
    await mockApi(page, { "GET /auth/session": guestSession });
    const errors = trackConsoleErrors(page);
    await page.goto("/guide");
    await expectGuide(page);
    await expect(page).toHaveTitle(/Getting started/);

    const routes = appRoutes();
    const hrefs = await page.locator("a[data-testid=guide-try]").evaluateAll((els) => els.map((e) => e.getAttribute("href") ?? ""));
    expect(hrefs.length).toBeGreaterThanOrEqual(25);
    for (const href of new Set(hrefs)) {
      const path = new URL(href, "http://x").pathname;
      expect(routes.some((r) => r.test(decodeURIComponent(path))), `${href} is a route of the app`).toBe(true);
      const res = await request.get(href);
      expect(res.status(), `${href} answers`).toBe(200);
    }

    // Search has no page: its Try it opens the global search.
    await page.locator("[data-try=search]").click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");

    // Every section is in the contents list.
    const toc = page.getByRole("navigation", { name: "On this page" });
    for (const s of SECTIONS) await expect(toc.getByRole("link", { name: s })).toBeVisible();
    expect(errors()).toEqual([]);
  });

  for (const role of ["patient", "researcher"] as const) {
    test(`renders for a signed-in ${role}`, async ({ page }) => {
      await mockApi(page, {
        "GET /auth/session": signedInSession({ role, role_verified: role !== "patient" }),
        "GET /notifications/unread-count": { count: 0 },
        "GET /me/threads/unread-count": { count: 0, requests: 0 },
      });
      const errors = trackConsoleErrors(page);
      await page.goto("/guide");
      await expectGuide(page);
      await expect(page).toHaveURL(/\/guide$/);
      expect(errors()).toEqual([]);
    });
  }

  test("an account still in the welcome flow can read it", async ({ page }) => {
    await mockApi(page, { "GET /auth/session": signedInSession({ role: null, age_confirmed: false }) });
    await page.goto("/guide");
    await page.waitForTimeout(500);
    await expect(page).toHaveURL(/\/guide$/);
  });

  test("found from the landing page, the footer and the user menu", async ({ page }) => {
    await mockApi(page, { "GET /auth/session": guestSession });
    await page.goto("/");
    await page.getByTestId("landing-guide").click();
    await expect(page).toHaveURL(/\/guide$/);

    await page.goto("/privacy");
    await page.getByRole("navigation", { name: "Footer" }).getByRole("link", { name: "Guide" }).click();
    await expect(page).toHaveURL(/\/guide$/);

    await page.unrouteAll();
    await mockApi(page, { "GET /auth/session": signedInSession() });
    await page.goto("/privacy");
    await page.getByTestId("user-menu").click();
    await page.getByRole("menuitem", { name: "Getting started" }).click();
    await expect(page).toHaveURL(/\/guide$/);
  });

  test("found at the end of the welcome flow", async ({ page }) => {
    let session = signedInSession({ role: null, age_confirmed: false, auth_provider: "google" });
    await mockApi(page, {
      "GET /auth/session": () => ({ json: session }),
      "PATCH /me/settings": () => {
        session = signedInSession({ role: "patient", age_confirmed: true, auth_provider: "google" });
        return { json: session.user };
      },
    });
    await page.goto("/welcome?next=%2Fprivacy");
    await expect(page.getByTestId("welcome-guide")).toHaveAttribute("href", "/guide");
    await page.getByRole("radio", { name: "Patient or family" }).click();
    await page.getByRole("checkbox", { name: /16 or older/ }).click();
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page).toHaveURL(/\/privacy$/);
    // Not a forced step: an action on the closing toast.
    await page.getByRole("button", { name: "Getting started" }).click();
    await expect(page).toHaveURL(/\/guide$/);
  });

  test("the header still fits at 1024 px, signed out and signed in", async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 800 });
    for (const session of [guestSession, signedInSession()]) {
      await page.unrouteAll();
      await mockApi(page, {
        "GET /auth/session": session,
        "GET /notifications/unread-count": { count: 0 },
        "GET /me/threads/unread-count": { count: 0, requests: 0 },
      });
      await page.goto("/guide");
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      const bar = page.locator("header > div").first();
      const { scroll, client } = await bar.evaluate((el) => ({ scroll: el.scrollWidth, client: el.clientWidth }));
      expect(scroll).toBeLessThanOrEqual(client);
      const last = session.user ? page.getByTestId("user-menu") : page.getByTestId("privacy-menu");
      const box = await last.boundingBox();
      expect(box && box.x + box.width).toBeLessThanOrEqual(1024);
      await noSidewaysScroll(page);
    }
  });

  test("no sideways scrolling at 360 px", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 780 });
    await mockApi(page, { "GET /auth/session": guestSession });
    await page.goto("/guide");
    await expectGuide(page);
    await noSidewaysScroll(page);
  });

  test("screenshots, light and dark", async ({ page }) => {
    test.skip(!SHOTS, "GUIDE_SHOTS not set");
    for (const theme of ["light", "dark"] as const) {
      for (const width of [1440, 390]) {
        await page.unrouteAll();
        await setTheme(page, theme);
        await page.setViewportSize({ width, height: width > 500 ? 900 : 844 });
        await mockApi(page, { "GET /auth/session": guestSession });
        await page.goto("/guide");
        await expectGuide(page);
        await page.screenshot({ path: `${SHOTS}/guide-${theme}-${width}.png`, fullPage: true, animations: "disabled" });
        await page.screenshot({ path: `${SHOTS}/guide-${theme}-${width}-top.png`, animations: "disabled" });
      }
    }
  });
});

test("found in the phone menu @mobile", async ({ page }) => {
  for (const session of [guestSession, signedInSession()]) {
    await page.unrouteAll();
    await mockApi(page, {
      "GET /auth/session": session,
      "GET /notifications/unread-count": { count: 0 },
      "GET /me/threads/unread-count": { count: 0, requests: 0 },
    });
    await page.goto("/privacy");
    await page.getByRole("button", { name: /Open menu/ }).click();
    await page.getByTestId("menu-guide").click();
    await expect(page).toHaveURL(/\/guide$/);
    await noSidewaysScroll(page);
  }
});
