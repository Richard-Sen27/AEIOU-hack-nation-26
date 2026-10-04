import { expect, test } from "@playwright/test";

import { guestSession, mockApi, setTheme, shot, signedInSession, trackConsoleErrors } from "../helpers";

test.describe("welcome", () => {
  test("first sign-in: plan notice, role, 16+, language, continue", async ({ page }) => {
    let settings: Record<string, unknown> | null = null;
    let session = signedInSession({ role: null, age_confirmed: false });
    await mockApi(page, {
      "GET /auth/session": () => ({ json: session }),
      "PATCH /me/settings": (req: { body: unknown }) => {
        settings = req.body as Record<string, unknown>;
        session = signedInSession({ role: "doctor", age_confirmed: true, language: "de" });
        return { json: session.user };
      },
    });
    const errors = trackConsoleErrors(page);
    await page.goto("/welcome?next=%2Fprivacy");

    const notice = page.getByTestId("chatgpt-plan-notice");
    await expect(notice).toBeVisible();
    await expect(notice).toContainText("You're using your ChatGPT plan");
    await expect(notice).toContainText("Eligible usage in this app uses your ChatGPT plan. Manage usage in your ChatGPT settings.");
    await notice.getByRole("button", { name: "Got it" }).click();
    await expect(notice).toBeHidden();

    // Nothing pre-selected.
    await expect(page.getByRole("radio", { checked: true })).toHaveCount(0);
    await expect(page.getByRole("checkbox", { name: /16 or older/ })).not.toBeChecked();

    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByText("Please choose one.")).toBeVisible();
    expect(settings).toBeNull();

    await page.getByRole("radio", { name: "Doctor" }).click();
    await page.getByRole("checkbox", { name: /16 or older/ }).click();
    await page.getByLabel(/Dr. Wu answers/).selectOption("de");
    await page.getByRole("button", { name: "Continue" }).click();

    await expect(page).toHaveURL(/\/privacy$/);
    expect(settings).toEqual({ role: "doctor", language: "de", age_confirmed_16: true });
    expect(errors()).toEqual([]);
  });

  test("an incomplete account is routed to /welcome and back", async ({ page }) => {
    await mockApi(page, {
      "GET /auth/session": signedInSession({ role: "patient", age_confirmed: false }),
      "GET /documents": [],
    });
    await page.goto("/documents");
    await expect(page).toHaveURL(/\/welcome\?next=%2Fdocuments$/);
    // Not the first sign-in (role exists): no plan notice again.
    await expect(page.getByTestId("chatgpt-plan-notice")).toHaveCount(0);
    await expect(page.getByRole("radio", { name: "Patient or family" })).toBeChecked();
  });

  test("notices stay readable without completing welcome", async ({ page }) => {
    await mockApi(page, { "GET /auth/session": signedInSession({ role: null, age_confirmed: false }) });
    await page.goto("/privacy");
    await page.waitForTimeout(500);
    await expect(page).toHaveURL(/\/privacy$/);
  });

  test("guest sees a sign-in prompt", async ({ page }) => {
    await mockApi(page, { "GET /auth/session": guestSession });
    await page.goto("/welcome");
    const prompt = page.getByTestId("sign-in-prompt");
    await expect(prompt.getByRole("button", { name: "Continue with ChatGPT" })).toBeVisible();
  });

  test("under 16 can delete the account", async ({ page }) => {
    let deleted = false;
    await mockApi(page, {
      "GET /auth/session": signedInSession({ role: null, age_confirmed: false }),
      "DELETE /me": () => {
        deleted = true;
        return { status: 204, body: "" };
      },
      "POST /auth/logout": { status: 204, body: "" },
    });
    await page.goto("/welcome");
    await page.getByTestId("chatgpt-plan-notice").getByRole("button", { name: "Got it" }).click();
    await page.getByText("I am under 16").click();
    await page.getByTestId("delete-account").click();
    await page.getByRole("button", { name: "Delete everything" }).click();
    await expect(page).toHaveURL(/127\.0\.0\.1:\d+\/$/);
    expect(deleted).toBe(true);
  });
});

test.describe("consent dialog", () => {
  for (const type of ["health_data", "contribute"] as const) {
    test(`${type}: notice content, no pre-ticked boxes, child needs parental confirmation`, async ({ page }) => {
      let granted: Record<string, unknown> | null = null;
      await mockApi(page, {
        "GET /auth/session": signedInSession(),
        "GET /profile": {},
        "GET /consents": [],
        "GET /contributions": [],
        "POST /consents": (req: { body: unknown }) => {
          granted = req.body as Record<string, unknown>;
          return { status: 201, json: { id: "c1", ...granted, granted_at: new Date().toISOString(), active: true } };
        },
      });
      const errors = trackConsoleErrors(page);
      await page.goto("/profile");
      await page.getByTestId(`grant-${type}`).click();
      const dialog = page.getByTestId("consent-dialog");
      await expect(dialog).toBeVisible();

      for (const text of ["What we process", "Why", "How it is protected", "How long we keep it", "Withdrawing"]) {
        await expect(dialog.getByRole("heading", { name: text, exact: true })).toBeVisible();
      }
      await expect(dialog).toContainText("Nothing is sold or shared");
      await expect(dialog.getByRole("link", { name: "privacy notice" })).toHaveAttribute("href", "/privacy");
      if (type === "health_data") {
        await expect(dialog).toContainText("What you type to Dr. Wu");
        await expect(dialog).toContainText("removed on our server before any AI model sees your text or documents");
        await expect(dialog).toContainText("Original files are deleted right after the text is extracted");
        await expect(dialog).toContainText("unless you separately agree to contribute");
      } else {
        await expect(dialog).toContainText("labelled patient-reported");
      }

      // Nothing pre-ticked, grant disabled.
      await expect(dialog.getByRole("checkbox", { checked: true })).toHaveCount(0);
      await expect(dialog.getByRole("radio", { checked: true })).toHaveCount(0);
      const grant = dialog.getByRole("button", { name: "I agree, continue" });
      await expect(grant).toBeDisabled();

      await dialog.getByRole("radio", { name: "A child I care for" }).click();
      await dialog.getByRole("checkbox", { name: /explicitly consent/ }).click();
      await expect(grant).toBeDisabled(); // parental responsibility still missing
      await dialog.getByRole("checkbox", { name: /parental responsibility/ }).click();
      await expect(grant).toBeEnabled();
      await grant.click();
      await expect(dialog).toBeHidden();
      expect(granted).toEqual({
        consent_type: type,
        version: type === "health_data" ? "health-data-2026-10-04" : "contribute-2026-10-04",
        about_child: true,
        parental_responsibility_confirmed: true,
      });
      expect(errors()).toEqual([]);
    });
  }

  test("declining is one click and grants nothing", async ({ page }) => {
    let posted = false;
    await mockApi(page, {
      "GET /auth/session": signedInSession(),
      "GET /profile": {},
      "GET /consents": [],
      "GET /contributions": [],
      "POST /consents": () => {
        posted = true;
        return { status: 201, json: {} };
      },
    });
    await page.goto("/profile");
    await page.getByTestId("grant-health_data").click();
    const dialog = page.getByTestId("consent-dialog");
    await dialog.getByRole("button", { name: "Not now" }).click();
    await expect(dialog).toBeHidden();
    expect(posted).toBe(false);
  });

  test("screenshots: both dialogs, light and dark", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockApi(page, {
      "GET /auth/session": signedInSession(),
      "GET /profile": {},
      "GET /consents": [],
      "GET /contributions": [],
    });
    for (const theme of ["light", "dark"] as const) {
      await setTheme(page, theme);
      for (const type of ["health_data", "contribute"] as const) {
        await page.goto("/profile");
        await page.getByTestId(`grant-${type}`).click();
        await page.getByTestId("consent-dialog").getByRole("radio", { name: "A child I care for" }).click();
        await shot(page, `account-consent-${type}-${theme}`);
      }
      await page.goto("/welcome");
    }
  });
});

test("welcome and consent on a phone @mobile", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockApi(page, {
    "GET /auth/session": signedInSession({ role: null, age_confirmed: false }),
    "GET /profile": {},
    "GET /consents": [],
    "GET /contributions": [],
  });
  await page.goto("/welcome");
  await expect(page.getByTestId("chatgpt-plan-notice")).toBeVisible();
  await shot(page, "account-welcome-notice-mobile");
  await page.getByRole("button", { name: "Got it" }).click();
  await shot(page, "account-welcome-mobile", { fullPage: true });
});

test("screenshots: welcome light and dark", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockApi(page, { "GET /auth/session": signedInSession({ role: null, age_confirmed: false }) });
  for (const theme of ["light", "dark"] as const) {
    await setTheme(page, theme);
    await page.goto("/welcome");
    await expect(page.getByTestId("chatgpt-plan-notice")).toBeVisible();
    await shot(page, `account-welcome-notice-${theme}`);
    await page.getByRole("button", { name: "Got it" }).click();
    await page.getByRole("radio", { name: "Patient or family" }).click();
    await shot(page, `account-welcome-${theme}`, { fullPage: true });
  }
});
