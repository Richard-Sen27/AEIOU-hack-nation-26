import { expect, test, type Page } from "@playwright/test";

import { mockApi, signedInSession } from "../helpers";
import { atlasTreePayload, summaryMock } from "../graph/fixtures";
import { graphMocks, reply, STORY, turnBody } from "./fixtures";

/*
 * The Dr. Wu interface: the AI notice (once, scrolls away), sources in plain words (collapsed
 * by default) and the Atlas acting on a reply (select one find, draw a found connection).
 */

async function signedIn(page: Page, mocks: Record<string, unknown> = {}) {
  await mockApi(page, {
    "GET /auth/session": signedInSession({ consents: ["health_data"] }),
    "GET /chat/sessions": [],
    "GET /chat/runs": [],
    "GET /profile": { updated_at: "2026-10-03T00:00:00Z" },
    "GET /atlas/tree.json": atlasTreePayload(),
    "GET /atlas/summary/*": summaryMock(),
    ...graphMocks,
    "POST /chat": () => turnBody({ ...reply, follow_up: null }),
    ...mocks,
  });
}

async function ask(page: Page, scope: ReturnType<Page["locator"]>, text = STORY) {
  const box = scope.getByRole("textbox", { name: "Message Dr. Wu" });
  await box.fill(text);
  await box.press("Enter");
}

test.describe("Dr. Wu AI notice", () => {
  test("chat: one quiet line at the start that scrolls away, not repeated per turn", async ({ page }) => {
    await signedIn(page);
    await page.setViewportSize({ width: 1440, height: 700 });
    await page.goto("/chat");
    const notice = page.getByTestId("ai-disclosure");
    await expect(notice).toHaveCount(1);
    await expect(notice).toContainText("Dr. Wu is an AI, not a doctor.");
    await expect(notice).toBeInViewport();
    await ask(page, page.locator("body"));
    await ask(page, page.locator("body"), "And the registry?");
    await expect(page.getByTestId("assistant-turn")).toHaveCount(2);
    await expect(page.getByTestId("assistant-turn").last()).toHaveAttribute("data-phase", "done");
    await expect(notice).toHaveCount(1);
    await expect(page.getByText("AI-generated · Dr. Wu")).toHaveCount(0);
    // Inside the conversation's scroll area: scrolled to the end, it is out of view.
    expect(await notice.evaluate((el) => !!el.closest('[data-testid="chat-log"]'))).toBe(true);
    await page.getByTestId("chat-log").evaluate((el) => el.scrollTo(0, el.scrollHeight));
    await expect(notice).not.toBeInViewport();
  });

  test("dock: the same line once, in the scrolling body, not in the header", async ({ page }) => {
    await signedIn(page);
    await page.goto("/atlas");
    const dock = page.getByTestId("atlas-wu-dock");
    await dock.getByTestId("atlas-wu-open").click();
    await ask(page, dock);
    await expect(dock.getByTestId("atlas-wu-turn")).toHaveAttribute("data-phase", "done");
    await expect(dock.getByTestId("ai-disclosure")).toHaveCount(1);
    expect(await dock.getByTestId("ai-disclosure").evaluate((el) => !!el.closest('[data-testid="atlas-wu-body"]'))).toBe(true);
    await expect(dock.getByText("AI-generated · Dr. Wu")).toHaveCount(0);
  });
});
