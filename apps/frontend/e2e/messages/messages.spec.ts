import { expect, test, type Page } from "@playwright/test";

import { expectNoHealthDataInBrowser } from "../account/fixtures";
import { errorEnvelope, mockApi, setTheme, trackConsoleErrors } from "../helpers";
import { CARD_ID, SECRET, card, expertThreads, messagingMocks, thread, type Req } from "./fixtures";

const SHOTS = process.env.MSG_SHOTS_DIR;
const OPEN = "a0000000-0000-4000-8000-000000000001";
const REQ = "b0000000-0000-4000-8000-000000000001";

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  await page.waitForTimeout(250);
  await page.screenshot({ path: `${SHOTS}/${name}.png`, animations: "disabled" });
}

const bodies = (calls: Req[], method: string, path: RegExp) =>
  calls.filter((c) => c.method === method && path.test(new URL(c.url).pathname)).map((c) => c.body);

test.describe("messages, patient", () => {
  test("list shows every status, the deleted counterpart and unread counts; opening marks read", async ({ page }) => {
    const m = messagingMocks();
    await mockApi(page, m.mocks);
    const errors = trackConsoleErrors(page);
    await page.goto("/messages");

    await expect(page.getByTestId("messages-count")).toHaveText("2");
    const rows = page.getByTestId("thread-row");
    await expect(rows).toHaveCount(6);
    await expect(rows.nth(0).getByTestId("thread-unread")).toContainText("2");
    await expect(page.locator('[data-status="requested"]').getByTestId("thread-status")).toHaveText("Waiting");
    await expect(page.locator('[data-status="declined"]').getByTestId("thread-status")).toHaveText("Declined");
    await expect(page.locator('[data-status="blocked"]').getByTestId("thread-status")).toHaveText("Blocked");
    await expect(rows.filter({ hasText: "Deleted account" }).getByTestId("thread-status")).toHaveText("Account deleted");
    await expect(page.getByTestId("no-thread")).toBeVisible();

    await rows.nth(0).click();
    await expect(page).toHaveURL(new RegExp(`/messages/${OPEN}$`));
    await expect(page.getByTestId("thread-name")).toHaveText("Dr. Anna Berg");
    await expect(page.getByTestId("banner-patient")).toContainText("not Dr. Wu");
    await expect(page.getByTestId("banner-patient")).toContainText("112/911");
    // Plain text: the URL is not a link, line breaks are kept.
    const bodiesEl = page.getByTestId("message-body");
    await expect(bodiesEl.nth(1)).toContainText("https://example.org/trial");
    await expect(page.getByTestId("message-log").locator("a")).toHaveCount(0);
    await expect(bodiesEl.nth(2)).toHaveCSS("white-space", "pre-wrap");
    // Read: the list and the header follow.
    await expect(rows.nth(0).getByTestId("thread-unread")).toHaveCount(0);
    await expect(page.getByTestId("messages-count")).toHaveCount(0);
    await expect(page).toHaveTitle(/^Messages/);
    // An application view: no site footer, and the page itself does not scroll.
    await expect(page.locator("footer")).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollHeight - window.innerHeight)).toBeLessThanOrEqual(0);
    expect(errors()).toEqual([]);
  });

  test("each status explains itself instead of the composer", async ({ page }) => {
    const m = messagingMocks();
    await mockApi(page, m.mocks);
    const note = page.getByTestId("thread-note");
    const cases: Array<[string, RegExp]> = [
      ["a0000000-0000-4000-8000-000000000002", /Waiting for Prof\. Jonas Weber to accept/],
      ["a0000000-0000-4000-8000-000000000003", /Dr\. Kim Lee declined/],
      ["a0000000-0000-4000-8000-000000000004", /This conversation is closed/],
      ["a0000000-0000-4000-8000-000000000005", /You blocked this person\. Unblock in your profile/],
      ["a0000000-0000-4000-8000-000000000006", /This account was deleted/],
    ];
    for (const [id, text] of cases) {
      await page.goto(`/messages/${id}`);
      await expect(note).toContainText(text);
      await expect(page.getByTestId("composer")).toHaveCount(0);
    }
    await expect(page.getByTestId("thread-name")).toHaveText("Deleted account");
  });

  test("send, delete and nothing of a message in the URL or browser storage", async ({ page }) => {
    const m = messagingMocks();
    await mockApi(page, m.mocks);
    await page.goto(`/messages/${OPEN}`);
    await page.getByTestId("composer-input").fill(SECRET);
    await page.getByTestId("composer-send").click();
    await expect(page.getByTestId("message-body").last()).toContainText(SECRET);
    await expect(page.getByTestId("composer-input")).toHaveValue("");
    expect(bodies(m.calls, "POST", /messages$/)).toEqual([{ body: SECRET, guardian_agreed: false }]);
    await expectNoHealthDataInBrowser(page, [SECRET, "Dr. Anna Berg", "Dravet"]);
    expect(await page.title()).not.toContain("Anna");

    await page.getByTestId("message").last().hover();
    await page.getByTestId("message-delete").last().click();
    await page.getByTestId("confirm-action").click();
    await expect(page.getByText(SECRET)).toHaveCount(0);
    expect(m.calls.some((c) => c.method === "DELETE" && /messages\/s4$/.test(c.url))).toBe(true);
  });

  test("hide removes it from the list", async ({ page }) => {
    const m = messagingMocks();
    await mockApi(page, m.mocks);
    await page.goto(`/messages/${OPEN}`);
    await page.getByTestId("thread-actions").click();
    await page.getByRole("menuitem", { name: "Hide" }).click();
    await expect(page).toHaveURL(/\/messages$/);
    await expect(page.getByTestId("thread-row")).toHaveCount(5);
  });

  test("block, then unblock in the profile", async ({ page }) => {
    const m = messagingMocks();
    await mockApi(page, m.mocks);
    await page.goto(`/messages/${OPEN}`);
    await page.getByTestId("thread-actions").click();
    await page.getByRole("menuitem", { name: "Block" }).click();
    await expect(page.getByTestId("confirm-dialog")).toContainText("Block Dr. Anna Berg?");
    await page.getByTestId("confirm-action").click();
    await expect(page.getByTestId("thread-note")).toContainText("You blocked this person");
    await expect(page.getByTestId("thread-badge")).toHaveText("Blocked");

    await page.goto("/profile#settings");
    const blocked = page.getByTestId("blocked-person");
    await expect(blocked).toHaveCount(1);
    await expect(blocked).toContainText("Dr. Anna Berg");
    await blocked.getByTestId("unblock").click();
    await expect(page.getByTestId("blocked-people")).toHaveCount(0);
    expect(m.calls.some((c) => c.method === "DELETE" && /\/me\/blocks\//.test(c.url))).toBe(true);
  });

  test("report needs a reason and the authorization", async ({ page }) => {
    const m = messagingMocks();
    await mockApi(page, m.mocks);
    await page.goto(`/messages/${OPEN}`);
    await page.getByTestId("message").nth(1).hover();
    await page.getByTestId("message-report").first().click();
    const dialog = page.getByTestId("report-dialog");
    await expect(dialog).toContainText("Every access is logged");
    await expect(page.getByTestId("report-send")).toBeDisabled();
    await dialog.getByRole("radio", { name: "Spam" }).click();
    await expect(page.getByTestId("report-send")).toBeDisabled();
    await page.getByTestId("report-authorize").click();
    await page.getByTestId("report-send").click();
    await expect(dialog).toHaveCount(0);
    expect(bodies(m.calls, "POST", /report$/)).toEqual([{ reason: "spam", message_id: "m2", authorize_review: true }]);
  });

  test("a 16-17 user ticks the guardian box on the first message of a conversation", async ({ page }) => {
    const m = messagingMocks({ ageGroup: "16_17", threads: [thread(OPEN, { guardian_agreement_needed: true })] });
    await mockApi(page, m.mocks);
    await page.goto(`/messages/${OPEN}`);
    const box = page.getByTestId("composer").getByText("agrees that I share it with Dr. Anna Berg");
    await expect(box).toBeVisible();
    await page.getByTestId("composer-input").fill("Hello");
    await expect(page.getByTestId("composer-send")).toBeDisabled();
    await page.getByTestId("guardian-checkbox").click();
    await page.getByTestId("composer-send").click();
    await expect(page.getByTestId("message-body").last()).toContainText("Hello");
    expect(bodies(m.calls, "POST", /messages$/)).toEqual([{ body: "Hello", guardian_agreed: true }]);
    await expect(page.getByTestId("guardian-checkbox")).toHaveCount(0);
  });

  test("sending without the connect consent asks for it, then the age group", async ({ page }) => {
    const m = messagingMocks({ consents: ["health_data"], ageGroup: null });
    await mockApi(page, m.mocks);
    await page.goto(`/messages/${OPEN}`);
    await page.getByTestId("composer-input").fill("Hi");
    await page.getByTestId("composer-send").click();
    const consent = page.getByTestId("consent-content-connect");
    await expect(consent).toBeVisible();
    // Messaging is always one's own: no "whose information" question.
    await expect(consent.getByRole("radio")).toHaveCount(0);
    await consent.getByRole("checkbox").click();
    await consent.getByRole("button", { name: "I agree, continue" }).click();
    await expect(page.getByTestId("age-group-dialog")).toBeVisible();
    await page.getByRole("radio", { name: "18 or older" }).click();
    await page.getByTestId("age-group-continue").click();
    await expect(page.getByTestId("message-body").last()).toContainText("Hi");
    expect(bodies(m.calls, "POST", /^\/consents$/)).toEqual([expect.objectContaining({ consent_type: "connect", version: "connect-signups-2026-10-04" })]);
    expect(bodies(m.calls, "PUT", /age-group$/)).toEqual([{ age_group: "18_plus" }]);
  });

  test("send errors are short and clear", async ({ page }) => {
    const m = messagingMocks({ send: () => errorEnvelope(409, "conflict", "This conversation is not open for messages.") });
    await mockApi(page, m.mocks);
    await page.goto(`/messages/${OPEN}`);
    await page.getByTestId("composer-input").fill("Hi");
    await page.getByTestId("composer-send").click();
    await expect(page.getByTestId("composer-error")).toHaveText("This conversation is not open for messages.");
  });

  test("withdrawing the connect consent in the profile says what it does", async ({ page }) => {
    const m = messagingMocks();
    await mockApi(page, m.mocks);
    await page.goto("/profile#consents");
    const box = page.getByTestId("consent-connect");
    await expect(box).toContainText("Withdrawing deletes your messages, withdraws your sign-ups, switches suggestions off and closes your conversations.");
    await box.getByTestId("withdraw-connect").click();
    await expect(page.getByTestId("consent-connect-state")).toHaveText("Not given");
    expect(m.calls.some((c) => c.method === "DELETE" && c.url.endsWith("/consents/connect"))).toBe(true);
    await page.goto("/messages");
    await expect(page.locator('[data-status="closed"]')).toHaveCount(6);
  });

  test("the age group can be corrected in the profile", async ({ page }) => {
    const m = messagingMocks();
    await mockApi(page, m.mocks);
    await page.goto("/profile#settings");
    await page.getByTestId("age-16_17").click();
    await expect(page.getByTestId("age-16_17")).toHaveAttribute("aria-checked", "true");
    expect(bodies(m.calls, "PUT", /age-group$/)).toEqual([{ age_group: "16_17" }]);
  });
});

test.describe("messages, expert", () => {
  test("a waiting request: header mark, accept, then reply", async ({ page }) => {
    const m = messagingMocks({ role: "doctor", threads: expertThreads() });
    await mockApi(page, m.mocks);
    await page.goto("/messages");
    await expect(page.getByTestId("messages-count")).toHaveText("1");
    await expect(page.getByTestId("thread-group-requests").getByTestId("thread-row")).toHaveCount(1);
    await expect(page.getByTestId("thread-group-requests").getByTestId("thread-status")).toHaveText("Request");
    await page.getByTestId("thread-group-requests").getByTestId("thread-row").click();
    await expect(page.getByTestId("banner-expert")).toContainText("Do not give individual medical advice");
    await expect(page.getByTestId("composer")).toHaveCount(0);
    await expect(page.getByTestId("respond")).toBeVisible();
    // Opening it read the message; the request still waits, so the header shows the dot.
    await expect(page.getByTestId("messages-requests")).toBeVisible();
    await page.getByTestId("accept").click();
    await expect(page.getByTestId("composer")).toBeVisible();
    await page.getByTestId("composer-input").fill("Yes, it is open.");
    await page.getByTestId("composer-send").click();
    await expect(page.getByTestId("message-body").last()).toContainText("Yes, it is open.");
    await expect(page.getByTestId("thread-group-requests")).toHaveCount(0);
  });

  test("declining a request", async ({ page }) => {
    const m = messagingMocks({ role: "doctor", threads: expertThreads() });
    await mockApi(page, m.mocks);
    await page.goto(`/messages/${REQ}`);
    await page.getByTestId("decline").click();
    await expect(page.getByTestId("thread-note")).toHaveText("You declined this request.");
    expect(m.calls.some((c) => c.method === "POST" && c.url.endsWith("/decline"))).toBe(true);
  });
});

test.describe("starting a conversation from a card", () => {
  async function openDialog(page: Page) {
    await page.goto(`/people/${CARD_ID}`);
    await page.getByTestId("message-card").click();
  }

  test("consent, age group 16-17 and the guardian box, then the request is sent", async ({ page }) => {
    const m = messagingMocks({ consents: ["health_data"], ageGroup: null, threads: [] });
    await mockApi(page, m.mocks);
    await openDialog(page);
    const consent = page.getByTestId("consent-content-connect");
    await consent.getByRole("checkbox").click();
    await consent.getByRole("button", { name: "I agree, continue" }).click();
    await page.getByRole("radio", { name: "16 or 17" }).click();
    await page.getByTestId("age-group-continue").click();
    const dialog = page.getByTestId("message-request-dialog");
    await expect(dialog).toContainText("not Dr. Wu");
    await expect(dialog).toContainText("A parent or guardian knows about this and agrees that I share it with Dr. Anna Berg.");
    await page.getByTestId("request-name").fill("Maria");
    await page.getByTestId("request-body").fill(SECRET);
    await expect(page.getByTestId("request-send")).toBeDisabled();
    await page.getByTestId("guardian-checkbox").click();
    await shot(page, "messages-request-guardian");
    await page.getByTestId("request-send").click();
    await expect(page).toHaveURL(/\/messages\/c0000000-0000-4000-8000-000000000001$/);
    expect(bodies(m.calls, "POST", /^\/me\/threads$/)).toEqual([
      { card_id: CARD_ID, display_name: "Maria", body: SECRET, guardian_agreed: true },
    ]);
    await expect(page.getByTestId("thread-note")).toContainText("Waiting for Dr. Anna Berg to accept");
    await expectNoHealthDataInBrowser(page, [SECRET, "Maria"]);
  });

  const errorCases: Array<[string, number, string, string]> = [
    ["not accepting", 404, "not_found", "This person does not accept messages."],
    ["existing conversation", 409, "conflict", "You already have a conversation with this person."],
    ["daily limit", 429, "rate_limited", "You can start 5 new conversations a day. Try again tomorrow."],
    ["professional", 403, "forbidden", "Only patients and caregivers can start a conversation."],
    ["not configured", 501, "not_implemented", "Messaging is not available on this server yet."],
    ["guardian", 403, "guardian_agreement_required", "Tick the parent or guardian box to send."],
  ];
  for (const [name, status, code, text] of errorCases) {
    test(`request error: ${name}`, async ({ page }) => {
      const m = messagingMocks({ threads: [], open: () => errorEnvelope(status, code) });
      await mockApi(page, m.mocks);
      await openDialog(page);
      await page.getByTestId("request-name").fill("Maria");
      await page.getByTestId("request-body").fill("Hello");
      await page.getByTestId("request-send").click();
      await expect(page.getByTestId("request-error")).toContainText(text);
      if (code === "guardian_agreement_required") await expect(page.getByTestId("guardian-checkbox")).toBeVisible();
    });
  }

  test("a professional has no way to start a conversation", async ({ page }) => {
    const m = messagingMocks({ role: "doctor", threads: [] });
    await mockApi(page, m.mocks);
    await page.goto(`/people/${CARD_ID}`);
    await expect(page.getByTestId("card-accepts-messages")).toBeVisible();
    await expect(page.getByTestId("message-card")).toHaveCount(0);
    await page.goto("/messages");
    await expect(page.getByTestId("threads-empty")).toHaveText("No conversations yet.");
  });

  test("no Message action on a card that does not accept messages", async ({ page }) => {
    const m = messagingMocks({ threads: [] });
    await mockApi(page, { ...m.mocks, "GET /people/*": card({ accepts_patient_messages: false }) });
    await page.goto(`/people/${CARD_ID}`);
    await expect(page.getByRole("heading", { name: "Dr. Anna Berg" })).toBeVisible();
    await expect(page.getByTestId("message-card")).toHaveCount(0);
  });
});

test.describe("header", () => {
  test("fits at 1024 px with the messages entry", async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 768 });
    const m = messagingMocks();
    await mockApi(page, m.mocks);
    await page.goto("/messages");
    await expect(page.getByTestId("messages-link")).toBeVisible();
    await expect(page.getByTestId("user-menu")).toBeVisible();
    const overflow = await page.locator("header > div").evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    const right = await page.getByTestId("user-menu").evaluate((el) => el.getBoundingClientRect().right);
    expect(right).toBeLessThanOrEqual(1024);
    await shot(page, "messages-header-1024");
  });
});

test.describe("phone", () => {
  test("list first, then the conversation, and the menu entry @mobile", async ({ page }) => {
    const m = messagingMocks();
    await mockApi(page, m.mocks);
    await page.goto("/messages");
    await expect(page.getByTestId("thread-list-pane")).toBeVisible();
    await expect(page.getByTestId("thread-pane")).toBeHidden();
    await page.getByTestId("thread-row").first().click();
    await expect(page.getByTestId("thread-pane")).toBeVisible();
    await expect(page.getByTestId("thread-list-pane")).toBeHidden();
    await expect(page.getByTestId("composer")).toBeInViewport();
    const scroll = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(scroll).toBeLessThanOrEqual(0);
    await expect(page.locator("footer")).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollHeight - window.innerHeight)).toBeLessThanOrEqual(0);
    await page.getByLabel("All conversations").click();
    await expect(page.getByTestId("thread-list-pane")).toBeVisible();

    await page.getByRole("button", { name: /Open menu/ }).click();
    await expect(page.getByTestId("menu-messages")).toBeVisible();
    await page.getByTestId("menu-messages").click();
    await expect(page).toHaveURL(/\/messages$/);
  });
});

// Screenshots for review (run with MSG_SHOTS_DIR set).
test.describe("screenshots", () => {
  test.skip(!SHOTS, "MSG_SHOTS_DIR not set");
  for (const theme of ["light", "dark"] as const) {
    for (const width of [1440, 390]) {
      test(`list, conversation and expert request ${theme} ${width}`, async ({ page }) => {
        await setTheme(page, theme);
        await page.setViewportSize({ width, height: width > 500 ? 900 : 844 });
        const m = messagingMocks();
        await mockApi(page, m.mocks);
        await page.goto("/messages");
        await expect(page.getByTestId("thread-row")).toHaveCount(6);
        await shot(page, `messages-list-${theme}-${width}`);
        await page.goto(`/messages/${OPEN}`);
        await expect(page.getByTestId("message")).toHaveCount(3);
        await shot(page, `messages-conversation-${theme}-${width}`);

        const e = messagingMocks({ role: "doctor", threads: expertThreads() });
        await page.unrouteAll({ behavior: "ignoreErrors" });
        await mockApi(page, e.mocks);
        await page.goto(`/messages/${REQ}`);
        await expect(page.getByTestId("respond")).toBeVisible();
        await shot(page, `messages-expert-request-${theme}-${width}`);

        const g = messagingMocks({ ageGroup: "16_17", threads: [] });
        await page.unrouteAll({ behavior: "ignoreErrors" });
        await mockApi(page, g.mocks);
        await page.goto(`/people/${CARD_ID}`);
        await page.getByTestId("message-card").click();
        await page.getByTestId("request-name").fill("Maria");
        await page.getByTestId("request-body").fill("Hello, my daughter has STXBP1. Could we talk about your registry?");
        await page.getByTestId("guardian-checkbox").click();
        await shot(page, `messages-request-${theme}-${width}`);
      });
    }
  }
});
