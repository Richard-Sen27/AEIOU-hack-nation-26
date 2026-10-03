/**
 * Live chat with Dr. Wu on the real API (model answers from the mock OpenAI):
 * just-in-time consent with the child choice, the spec's example message
 * (status lines, summary, chips, profile hints), confirming a chip into the
 * profile (carrying the consent's child answer), "Show in graph", sessions
 * (list, reopen, delete), an emergency message and a diagnosis request.
 * Start the processes as described in live-helpers.ts, then `PORT=3106 pnpm test:e2e:live`.
 */
import { expect, test, type Page } from "@playwright/test";

import {
  API,
  STORY,
  deleteAccount,
  passWelcome,
  resetMock,
  shot,
  signInAs,
  storageDump,
  trackProblems,
  trackUrls,
} from "./live-helpers";

async function sendMessage(page: Page, text: string) {
  const box = page.getByTestId("composer").getByRole("textbox");
  await box.fill(text);
  await box.press("Enter");
}

const lastTurn = (page: Page) => page.getByTestId("assistant-turn").last();

test.describe("chat with Dr. Wu", () => {
  test.beforeEach(async ({ request }) => resetMock(request));

  test("consent, example message, chips into the profile, sessions, safety", async ({ page }) => {
    await signInAs(page, "alice");
    await deleteAccount(page);
    await page.context().clearCookies();
    await signInAs(page, "alice", "/chat");
    const problems = trackProblems(page);
    const urls = trackUrls(page);
    try {
      await page.getByTestId("chatgpt-plan-notice").getByRole("button", { name: "Got it" }).click();
      await passWelcome(page);
      await expect(page).toHaveURL(/\/chat$/);

      // First message: consent first, nothing sent before it.
      await sendMessage(page, STORY);
      const dialog = page.getByTestId("consent-dialog");
      await expect(dialog).toBeVisible();
      await expect(page.getByTestId("user-message")).toHaveCount(0);
      // "Not now" keeps the text and sends nothing.
      await dialog.getByRole("button", { name: "Not now" }).click();
      await expect(page.getByTestId("composer").getByRole("textbox")).toHaveValue(STORY);
      await page.getByTestId("composer").getByRole("textbox").press("Enter");
      await expect(dialog).toBeVisible();
      await dialog.getByRole("radio", { name: "A child I care for" }).check();
      await dialog.getByRole("checkbox", { name: /parental responsibility/ }).check();
      await dialog.getByRole("checkbox", { name: /explicitly consent/ }).check();
      await dialog.getByRole("button", { name: /I agree/ }).click();

      await expect(page.getByTestId("user-message")).toContainText("daughter");
      const turn = lastTurn(page);
      await expect(turn).toHaveAttribute("data-phase", "done", { timeout: 60_000 });
      await expect(turn.getByTestId("summary")).not.toBeEmpty();
      await expect(turn).toContainText(/Checked the atlas in \d+ steps?/);
      await expect(turn.getByText("AI-generated · Dr. Wu")).toBeVisible();
      await shot(page, "chat-reply", { fullPage: true });

      // Confirm the first matched chip; the profile takes the consent's child answer.
      const chip = turn.getByTestId("chip").filter({ has: page.getByRole("button", { name: /^Confirm / }) }).first();
      await expect(chip).toBeVisible();
      await chip.getByRole("button", { name: /^Confirm / }).click();
      await expect(turn.getByTestId("chip").filter({ hasText: "In profile" }).first()).toBeVisible();
      // The consent already asked whose data this is: no second question.
      await expect(turn.getByTestId("child-offer")).toHaveCount(0);
      const profile = await (await page.request.get(`${API}/profile`)).json();
      expect(profile.about_child).toBe(true);
      expect(profile.parental_responsibility_confirmed).toBe(true);

      // Profile hints (age etc.) can be confirmed into the profile.
      const hint = turn.getByTestId("profile-hint").first();
      if (await hint.count()) {
        await hint.getByRole("button", { name: /^Confirm / }).click();
        await expect(hint).toHaveAttribute("data-state", "confirmed");
      }

      // "Show in graph" opens the Atlas focused on the reply.
      const showInGraph = turn.getByTestId("show-in-graph");
      if (await showInGraph.count()) {
        await expect(showInGraph).toHaveAttribute("href", /^\/atlas\?focus=/);
      }

      // Session list, reopen, delete.
      const sessions = page.getByTestId("session-item");
      await expect(sessions).toHaveCount(1);
      await page.getByRole("button", { name: /New conversation/ }).click();
      await expect(page.getByTestId("user-message")).toHaveCount(0);
      await sessions.first().getByRole("button").first().click();
      await expect(page.getByTestId("user-message")).toContainText("daughter");

      // Emergency language: emergency services, no graph answer.
      await page.getByRole("button", { name: /New conversation/ }).click();
      await sendMessage(page, "My son is having a seizure right now and it won't stop for 6 minutes");
      const emergency = lastTurn(page).getByTestId("emergency");
      await expect(emergency).toBeVisible({ timeout: 30_000 });
      await expect(emergency).toContainText(/emergency/i);
      await expect(lastTurn(page).getByTestId("cards")).toHaveCount(0);

      // A diagnosis request is declined, graph context still offered.
      await page.getByRole("button", { name: /New conversation/ }).click();
      await sendMessage(page, "He has fever seizures. Can you diagnose him? Is it Dravet syndrome?");
      await expect(lastTurn(page)).toHaveAttribute("data-phase", "done", { timeout: 60_000 });
      await expect(lastTurn(page)).toContainText(/can't say if this is the diagnosis|not a diagnosis/i);
      await shot(page, "chat-diagnosis");

      // Delete every conversation.
      for (let n = await sessions.count(); n > 0; n--) {
        await sessions.first().getByRole("button", { name: /Delete/ }).click();
        const confirm = page.getByRole("alertdialog");
        if (await confirm.count()) await confirm.getByRole("button", { name: /Delete/ }).click();
        await expect(sessions).toHaveCount(n - 1);
      }

      expect(urls.some((u) => /daughter|seizure|Dravet/i.test(decodeURIComponent(u)))).toBe(false);
      expect(await storageDump(page)).not.toMatch(/daughter|seizure/i);
      expect(problems()).toEqual([]);
    } finally {
      await deleteAccount(page);
    }
  });
});
