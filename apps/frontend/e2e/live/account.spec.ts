/**
 * Live account journey: profile editing (consent asked on the first save),
 * consents grant and withdraw, contributions create and remove, an edge flag
 * that a second user sees as under review, data export, account deletion.
 * Start the processes as described in live-helpers.ts, then `PORT=3106 pnpm test:e2e:live`.
 */
import { expect, test, type Browser, type Page } from "@playwright/test";

import { API, deleteAccount, passWelcome, resetMock, shot, signInAs, trackProblems } from "./live-helpers";

async function freshUser(page: Page, user: "alice" | "bob" | "carol", returnTo = "/profile") {
  await signInAs(page, user);
  await deleteAccount(page);
  await page.context().clearCookies();
  await signInAs(page, user, returnTo);
  // A fresh account always passes the welcome step first.
  await expect(page).toHaveURL(/\/welcome/);
  await page.getByTestId("chatgpt-plan-notice").getByRole("button", { name: "Got it" }).click();
  await passWelcome(page);
}

async function grantInDialog(page: Page) {
  const dialog = page.getByTestId("consent-dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("radio", { name: /^My own/ }).check();
  await dialog.getByRole("checkbox", { name: /explicitly consent/ }).check();
  await dialog.getByRole("button", { name: /I agree/ }).click();
  await expect(dialog).toBeHidden();
}

test.describe("account", () => {
  test.beforeEach(async ({ request }) => resetMock(request));

  test("profile, consents, contributions, export and deletion", async ({ page }) => {
    await freshUser(page, "carol");
    const problems = trackProblems(page);
    try {
      await expect(page).toHaveURL(/\/profile$/);
      const editor = page.getByTestId("profile-editor");
      await expect(editor).toBeVisible();

      // First save asks for the health-data consent, then saves.
      await page.getByTestId("picker-disease").getByRole("combobox").fill("Dravet");
      await page.getByRole("option", { name: /Dravet syndrome/ }).first().click();
      await expect(editor.getByTestId("profile-disease")).toHaveCount(1);
      await page.getByTestId("picker-phenotype").getByRole("combobox").fill("Seizure");
      await page.getByRole("option", { name: /^Seizure/ }).first().click();
      await page.getByLabel("Age in years").fill("4");
      await page.getByRole("button", { name: "Save changes" }).click();
      await grantInDialog(page);
      // Declining nothing: the save goes through after consent (click again if
      // the dialog interrupted the first click).
      if (!(await page.getByText("Profile saved").first().isVisible().catch(() => false))) {
        await page.getByRole("button", { name: "Save changes" }).click();
      }
      await expect(page.getByText("Profile saved").first()).toBeVisible();
      await page.reload();
      await expect(page.getByTestId("profile-disease")).toContainText(/Dravet/);
      await shot(page, "account-profile", { fullPage: true });

      // Consents: health data given, contribute not; contribute via the form.
      await expect(page.getByTestId("consent-health_data-state")).toHaveText("Given");
      await expect(page.getByTestId("consent-contribute-state")).toHaveText("Not given");
      await page.getByTestId("contribute-open").click();
      await grantInDialog(page);
      const form = page.getByTestId("contribution-form");
      await expect(form).toBeVisible();
      await form.getByRole("button", { name: "Fill in from my profile" }).click();
      await form.getByRole("button", { name: "Contribute" }).click();
      const list = page.getByTestId("contribution-list");
      await expect(list.getByTestId("contribution")).toHaveCount(1);
      await expect(list.getByTestId("status-flag")).toContainText(/review/i);
      await list.getByTestId("contribution").first().getByRole("button", { name: "Remove contribution" }).click();
      await expect(list.getByTestId("contribution")).toHaveCount(0);

      // Withdraw the contribute consent (one action).
      await page.getByTestId("withdraw-contribute").click();
      const confirm = page.getByRole("alertdialog");
      if (await confirm.isVisible().catch(() => false)) await confirm.getByRole("button", { name: /Withdraw/ }).click();
      await expect(page.getByTestId("consent-contribute-state")).toHaveText("Not given");

      // Data export.
      const download = page.waitForEvent("download");
      await page.getByTestId("export-data").click();
      const file = await download;
      expect(file.suggestedFilename()).toMatch(/\.json$/);

      // Withdrawing health data deletes the profile.
      await page.getByTestId("withdraw-health_data").click();
      const confirm2 = page.getByRole("alertdialog");
      if (await confirm2.isVisible().catch(() => false)) await confirm2.getByRole("button", { name: /Withdraw/ }).click();
      await expect(page.getByTestId("consent-health_data-state")).toHaveText("Not given");
      await page.reload();
      await expect(page.getByTestId("profile-disease")).toHaveCount(0);

      // Account deletion signs out.
      await page.getByTestId("delete-account").click();
      await page.getByTestId("delete-account-dialog").getByRole("button", { name: "Delete everything" }).click();
      await expect(page).toHaveURL(/127\.0\.0\.1:\d+\/$/);
      const session = await (await page.request.get(`${API}/auth/session`)).json();
      expect(session.user).toBeNull();
      expect(problems()).toEqual([]);
    } finally {
      await deleteAccount(page);
    }
  });

  test("a flagged edge shows as under review for another user", async ({ page, browser }: { page: Page; browser: Browser }) => {
    await freshUser(page, "alice", "/node/MONDO%3A0012812");
    const problems = trackProblems(page);
    const other = await browser.newContext();
    const page2 = await other.newPage();
    try {
      await page.getByTestId("node-panel").getByRole("button", { name: /^Sources for / }).first().click();
      const edge = page.getByTestId("edge-panel");
      await edge.getByTestId("flag-edge").click();
      const dialog = page.getByTestId("flag-dialog");
      await dialog.getByRole("textbox").fill("The cited source does not seem to support this link.");
      await dialog.getByTestId("flag-submit").click();
      await expect(edge.getByTestId("status-flag")).toContainText("Under review");
      const relation = await edge.getByTestId("edge-relation").textContent();

      await freshUser(page2, "bob", "/node/MONDO%3A0012812");
      await page2.getByRole("radio", { name: "List" }).click();
      await expect(page2.getByTestId("node-panel").getByTestId("status-flag").first()).toContainText("Under review");
      expect(relation).toBeTruthy();
      expect(problems()).toEqual([]);
    } finally {
      await deleteAccount(page2).catch(() => {});
      await other.close();
      await deleteAccount(page);
    }
  });
});
