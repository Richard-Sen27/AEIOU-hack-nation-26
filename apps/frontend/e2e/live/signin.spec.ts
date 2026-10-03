/**
 * Live sign-in through the mock OpenAI: Continue with ChatGPT → mock consent →
 * welcome (plan notice, role, 16+) → back where the user was → sign out.
 * Start the processes as described in live-helpers.ts, then `PORT=3106 pnpm test:e2e:live`.
 */
import { expect, test } from "@playwright/test";

import { IDS, completeMockSignIn, deleteAccount, resetMock, shot, signInAs, trackProblems } from "./live-helpers";

test.describe("sign-in", () => {
  test.beforeEach(async ({ request }) => resetMock(request));

  test("first sign-in passes welcome and returns to the page", async ({ page }) => {
    // Start from a fresh account (a failed earlier run may have left one).
    await signInAs(page, "carol");
    await deleteAccount(page);
    await page.context().clearCookies();
    const problems = trackProblems(page);
    const nodeUrl = `/node/${encodeURIComponent(IDS.dee4)}`;
    await page.goto(nodeUrl);
    await page.getByRole("banner").getByRole("button", { name: /Continue with ChatGPT/ }).click();
    await completeMockSignIn(page, "carol");

    await expect(page).toHaveURL(/\/welcome/);
    const notice = page.getByTestId("chatgpt-plan-notice");
    await expect(notice).toBeVisible();
    await shot(page, "signin-plan-notice");
    await notice.getByRole("button", { name: "Got it" }).click();
    await page.getByRole("radio", { name: /Patient or family/ }).check();
    await page.getByRole("checkbox", { name: /16 or older/ }).check();
    await shot(page, "signin-welcome");
    await page.getByRole("button", { name: /^Continue/ }).click();
    await expect(page).toHaveURL(new RegExp(`${nodeUrl}$`));
    await expect(page.getByTestId("user-menu")).toBeVisible();

    // Signing out returns to guest mode.
    await page.getByTestId("user-menu").click();
    await page.getByRole("menuitem", { name: /Sign out/ }).click();
    await expect(page.getByRole("banner").getByRole("button", { name: /Continue with ChatGPT/ })).toBeVisible();

    // Sign-out reloads on the landing page by design; signing in again from
    // the node page skips welcome and lands back there.
    await expect(page).toHaveURL(/\/$/);
    await page.goto(nodeUrl);
    await page.getByRole("banner").getByRole("button", { name: /Continue with ChatGPT/ }).click();
    await completeMockSignIn(page, "carol");
    await expect(page).toHaveURL(new RegExp(`${nodeUrl}$`));
    await deleteAccount(page);
    expect(problems()).toEqual([]);
  });
});
