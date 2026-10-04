import { expect, test, type Page } from "@playwright/test";

import { mockApi, signedInSession } from "./helpers";
import { graphMocks, STORY } from "./chat/fixtures";

/** A 429 as the API sends it: error envelope with reason and retry_after, plus Retry-After. */
function tooMany(reason: "rate" | "busy" | "budget", retryAfter: number, message: string) {
  return {
    status: 429,
    headers: { "retry-after": String(retryAfter) },
    json: { error: { code: "rate_limited", message, reason, retry_after: retryAfter, request_id: "0123456789abcdef" } },
  };
}

type Call = { method: string; url: string };

async function signedIn(page: Page, mocks: Record<string, unknown>, calls: Call[] = []) {
  await mockApi(page, {
    "GET /auth/session": signedInSession({ consents: ["health_data"] }),
    "GET /me/threads/unread-count": { count: 0, requests_waiting: 0 },
    "GET /chat/sessions": [],
    "GET /profile": { updated_at: "2026-10-03T00:00:00Z" },
    ...graphMocks,
    ...mocks,
  });
  page.on("request", (r) => calls.push({ method: r.method(), url: r.url() }));
}

test.describe("rate limits", () => {
  test("a 429 on a background read shows one calm toast and the polls wait for Retry-After", async ({ page }) => {
    await page.clock.install();
    let polls = 0;
    await signedIn(page, {
      "GET /notifications/unread-count": () => {
        polls += 1;
        return polls === 1
          ? tooMany("rate", 150, "Too many requests in a short time. Please wait a moment.")
          : { json: { count: 0 } };
      },
    });
    await page.goto("/privacy");
    await expect.poll(() => polls).toBe(1);
    const toast = page.locator("[data-sonner-toast]").filter({ hasText: "Please wait a moment" });
    await expect(toast).toBeVisible();
    await expect(toast).toContainText("Try again shortly.");

    // The 60 s poll and a focus inside the 150 s pause send nothing.
    await page.clock.runFor(60_000);
    await page.evaluate(() => window.dispatchEvent(new Event("focus")));
    await page.clock.runFor(60_000);
    await page.waitForTimeout(300);
    expect(polls).toBe(1);

    // After the pause the next tick asks again.
    await page.clock.runFor(60_000);
    await expect.poll(() => polls).toBe(2);
  });

  test("busy: Dr. Wu says so briefly and offers Try again", async ({ page }) => {
    await signedIn(page, {
      "POST /chat": tooMany("busy", 5, "Amber is busy right now. Try again in a moment."),
    });
    await page.goto("/chat");
    const box = page.getByRole("textbox", { name: "Message Dr. Wu" });
    await box.fill(STORY);
    await box.press("Enter");
    const err = page.getByTestId("assistant-turn").last().getByTestId("turn-error");
    await expect(err).toContainText("Dr. Wu is busy");
    await expect(err).toContainText("Try again in a moment.");
    await expect(err.getByRole("button", { name: "Try again" })).toBeVisible();
    await expect(err).not.toContainText("usage limit");
  });

  test("daily budget: the usual usage-limit message", async ({ page }) => {
    await signedIn(page, {
      "POST /chat": tooMany("budget", 3600, "The AI usage limit is reached. Please try again later."),
    });
    await page.goto("/chat");
    const box = page.getByRole("textbox", { name: "Message Dr. Wu" });
    await box.fill(STORY);
    await box.press("Enter");
    const err = page.getByTestId("assistant-turn").last().getByTestId("turn-error");
    await expect(err).toContainText("The usage limit is reached");
  });
});
