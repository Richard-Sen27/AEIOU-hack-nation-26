import { expect, test, type Locator, type Page } from "@playwright/test";

import { mockApi, signedInSession } from "./helpers";
import { graphMocks, STORY } from "./chat/fixtures";
import { atlasTreePayload, summaryMock } from "./graph/fixtures";

/** A 429 as the API sends it: error envelope with reason and retry_after, plus Retry-After. */
function tooMany(reason: "rate" | "busy" | "budget", retryAfter: number, message: string, scope?: "account" | "server") {
  return {
    status: 429,
    headers: { "retry-after": String(retryAfter) },
    json: {
      error: { code: "rate_limited", message, reason, retry_after: retryAfter, request_id: "0123456789abcdef", ...(scope ? { scope } : {}) },
    },
  };
}

/** The public contact address the dev server was started with (NEXT_PUBLIC_PRIVACY_EMAIL), if any. */
const CONTACT = process.env.NEXT_PUBLIC_PRIVACY_EMAIL || "";

/** "Need more? Write to <address>." with a mailto link when an address is set; nothing otherwise. */
async function expectContact(scope: Locator) {
  const line = scope.getByTestId("limit-contact");
  if (!CONTACT) {
    await expect(line).toHaveCount(0);
    return;
  }
  await expect(line).toHaveText(`Need more? Write to ${CONTACT}.`);
  await expect(line.getByRole("link", { name: CONTACT })).toHaveAttribute("href", `mailto:${CONTACT}`);
}

const atlasMocks = { "GET /atlas/tree.json": atlasTreePayload(), "GET /atlas/summary/*": summaryMock() };

async function askChat(page: Page) {
  const box = page.getByRole("textbox", { name: "Message Dr. Wu" });
  await box.fill(STORY);
  await box.press("Enter");
  return page.getByTestId("assistant-turn").last().getByTestId("turn-error");
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
          ? tooMany("rate", 150, "Too many requests. Try again in 3 minutes.")
          : { json: { count: 0 } };
      },
    });
    await page.goto("/privacy");
    await expect.poll(() => polls).toBe(1);
    const toast = page.locator("[data-sonner-toast]").filter({ hasText: "Please wait a moment" });
    await expect(toast).toBeVisible();
    await expect(toast).toContainText("Too many requests. Try again in 3 minutes.");

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

  test("daily budget: try again tomorrow, and the contact line when an address is set", async ({ page }) => {
    await signedIn(page, {
      "POST /chat": tooMany("budget", 30_000, "Today's AI limit is reached. Try again tomorrow.", "account"),
    });
    await page.goto("/chat");
    const err = await askChat(page);
    await expect(err).toContainText("Today's limit for Dr. Wu is reached. Try again tomorrow.");
    await expectContact(err);
  });

  test("Amber's daily ceiling says it is Amber's limit, not the user's", async ({ page }) => {
    await signedIn(page, {
      "POST /chat": tooMany("budget", 30_000, "Amber's daily limit is reached. Try again tomorrow.", "server"),
    });
    await page.goto("/chat");
    const err = await askChat(page);
    await expect(err).toContainText("Amber's daily limit is reached. Try again tomorrow.");
    await expect(err).not.toContainText("Today's limit for");
    await expectContact(err);
  });

  test("a per-day route limit also says tomorrow", async ({ page }) => {
    await signedIn(page, { "POST /chat": tooMany("rate", 20_000, "Today's limit is reached. Try again tomorrow.") });
    await page.goto("/chat");
    const err = await askChat(page);
    await expect(err).toContainText("Try again tomorrow.");
    await expect(err).not.toContainText("moment");
    await expectContact(err);
  });

  test("a short-term limit counts the real wait down, without a contact line", async ({ page }) => {
    await page.clock.install();
    await signedIn(page, { "POST /chat": tooMany("rate", 42, "Too many requests. Try again in 42 seconds.") });
    await page.goto("/chat");
    const err = await askChat(page);
    await expect(err).toContainText("Too many requests. Try again in 42 seconds.");
    await page.clock.runFor(10_000);
    await expect(err).toContainText("Try again in 32 seconds.");
    await expect(err.getByTestId("limit-contact")).toHaveCount(0);
    await page.clock.runFor(40_000);
    await expect(err).toContainText("You can try again now.");
  });

  test("dock: daily budget, short wait and busy", async ({ page }) => {
    let reply = tooMany("budget", 30_000, "Today's AI limit is reached. Try again tomorrow.", "account");
    await signedIn(page, { ...atlasMocks, "POST /chat": () => reply });
    await page.goto("/atlas");
    const dock = page.getByTestId("atlas-wu-dock");
    await dock.getByTestId("atlas-wu-open").click();
    const box = dock.getByRole("textbox", { name: "Message Dr. Wu" });
    await box.fill(STORY);
    await box.press("Enter");
    const err = dock.getByTestId("turn-error");
    await expect(err).toContainText("Today's limit for Dr. Wu is reached. Try again tomorrow.");
    await expectContact(err);

    reply = tooMany("rate", 90, "Too many requests. Try again in about a minute.");
    await err.getByRole("button", { name: "Retry" }).click();
    await expect(err).toContainText("Too many requests. Try again in about a minute.");
    await expect(err.getByTestId("limit-contact")).toHaveCount(0);

    reply = tooMany("busy", 5, "Amber is busy right now. Try again in a moment.");
    await err.getByRole("button", { name: "Retry" }).click();
    await expect(err).toContainText("Dr. Wu is busy. Try again in a moment.");
  });

  test("dock: the daily message fits the phone layout @mobile", async ({ page }) => {
    await signedIn(page, {
      ...atlasMocks,
      "POST /chat": tooMany("budget", 30_000, "Today's AI limit is reached. Try again tomorrow.", "account"),
    });
    await page.goto("/atlas");
    await page.getByTestId("atlas-wu-dock").getByTestId("atlas-wu-open").click();
    const sheet = page.getByTestId("atlas-wu-sheet");
    const box = sheet.getByRole("textbox", { name: "Message Dr. Wu" });
    await box.fill(STORY);
    await box.press("Enter");
    const err = sheet.getByTestId("turn-error");
    await expect(err).toContainText("Today's limit for Dr. Wu is reached. Try again tomorrow.");
    await expectContact(err);
    const width = page.viewportSize()!.width;
    const right = await err.evaluate((el) => el.getBoundingClientRect().right);
    expect(right).toBeLessThanOrEqual(width);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });

  for (const [name, reply, text] of [
    ["daily budget", tooMany("budget", 30_000, "Today's AI limit is reached. Try again tomorrow.", "account"), "Today's limit for summaries is reached. Try again tomorrow."],
    ["short wait", tooMany("rate", 600, "Too many requests. Try again in 10 minutes."), "Too many requests. Try again in 10 minutes."],
    ["busy", tooMany("busy", 5, "Amber is busy right now. Try again in a moment."), "Busy. Try again in a moment."],
  ] as const) {
    test(`summary: ${name}`, async ({ page }) => {
      await signedIn(page, {
        ...atlasMocks,
        "POST /explain": reply,
      });
      await page.goto("/atlas?focus=MONDO:9900007");
      const panel = page.getByTestId("atlas-panel");
      await panel.getByTestId("atlas-summary-write").click();
      const alert = panel.getByTestId("atlas-summary-write-error");
      await expect(alert).toContainText(text);
      if (name === "daily budget") await expectContact(alert);
      else await expect(alert.getByTestId("limit-contact")).toHaveCount(0);
      await expect(alert.getByRole("button", { name: "Retry" })).toBeVisible();
    });
  }
});
