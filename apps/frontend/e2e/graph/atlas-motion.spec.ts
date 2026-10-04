import { expect, test, type Page } from "@playwright/test";

import { guestSession, mockApi, trackConsoleErrors } from "../helpers";
import { atlasTreePayload, summaryMock } from "./fixtures";

/** The summary card's enter and exit (the map's colour fade needs WebGL and is checked by hand). */
async function atlas(page: Page) {
  await mockApi(page, {
    "GET /auth/session": guestSession,
    "GET /atlas/tree.json": atlasTreePayload(),
    "GET /atlas/summary/*": summaryMock(),
    "GET /chat/sessions": [],
  });
}

const frame = (page: Page) => page.getByTestId("atlas-panel-frame");

test.describe("atlas card motion", () => {
  test("slides in, keeps its frame when the node changes, and slides out before it unmounts", async ({ page }) => {
    await atlas(page);
    const errors = trackConsoleErrors(page);
    await page.goto("/atlas?focus=MONDO:9900007");
    const card = frame(page);
    await expect(card).toHaveAttribute("data-state", "open");
    await expect(card).toHaveClass(/animate-in/);
    await expect(card.getByRole("heading", { name: "STXBP1 encephalopathy" })).toBeVisible();

    // Another node: same frame element, no second entrance, no closed state in between.
    await card.evaluate((el) => ((el as HTMLElement & { __mark?: boolean }).__mark = true));
    await card.getByTestId("atlas-crumb").first().click();
    await expect(card.getByRole("heading", { name: "STXBP1 encephalopathy" })).toHaveCount(0);
    await expect(card).toHaveAttribute("data-state", "open");
    expect(await card.evaluate((el) => !!(el as HTMLElement & { __mark?: boolean }).__mark)).toBe(true);

    // Close: the card plays its exit with the last content, then unmounts. The exit is short, so
    // a MutationObserver records what the card looked like instead of polling for it.
    await card.evaluate((el) => {
      const w = window as unknown as { __exit: string[] };
      w.__exit = [];
      new MutationObserver(() => {
        const f = document.querySelector('[data-testid="atlas-panel-frame"]');
        w.__exit.push(
          f ? `${f.getAttribute("data-state")}:${/animate-out/.test(f.className)}:${!!f.querySelector('[data-testid="atlas-panel"]')}` : "gone",
        );
      }).observe(el.parentElement!, { childList: true, subtree: true, attributes: true, attributeFilter: ["data-state"] });
    });
    await card.getByRole("button", { name: "Close summary" }).click();
    await expect(card).toHaveCount(0);
    const seen = await page.evaluate(() => (window as unknown as { __exit: string[] }).__exit);
    expect(seen).toContain("closed:true:true");
    expect(seen.at(-1)).toBe("gone");
    expect(errors()).toEqual([]);
  });

  test("with reduced motion the card leaves at once", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await atlas(page);
    await page.goto("/atlas?focus=MONDO:9900007");
    const card = frame(page);
    await expect(card).toHaveAttribute("data-state", "open");
    await expect(card).toHaveClass(/motion-reduce:animate-none/);
    await card.getByRole("button", { name: "Close summary" }).click();
    // No exit state at all: gone on the next render.
    await expect(card).toHaveCount(0, { timeout: 100 });
  });
});
