import { expect, test } from "@playwright/test";

import { API_URL, guestSession, mockApi, signedInSession } from "../helpers";

const withGoogle = { ...guestSession, sign_in_methods: ["openai", "google"] };

async function openDialog(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.getByRole("textbox", { name: /Describe the diagnosis/ }).fill("My son has seizures every night");
  await page.keyboard.press("Enter");
  const dialog = page.getByTestId("sign-in-dialog");
  await expect(dialog).toBeVisible();
  return dialog;
}

test("no Google button unless the session lists it", async ({ page }) => {
  await mockApi(page, { "GET /auth/session": guestSession });
  const dialog = await openDialog(page);
  await expect(dialog.getByRole("button", { name: "Continue with ChatGPT" })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Continue with Google" })).toHaveCount(0);
  await expect(page.getByTestId("header-sign-in")).toHaveCount(0);
});

test("Google button shows when enabled and starts the Google sign-in", async ({ page }) => {
  await mockApi(page, { "GET /auth/session": withGoogle });
  const dialog = await openDialog(page);
  await expect(dialog.getByRole("button", { name: "Continue with ChatGPT" })).toBeVisible();
  const google = dialog.getByRole("button", { name: "Continue with Google" });
  await expect(google).toBeVisible();
  await expect(dialog).toContainText("From OpenAI or Google");

  let started = "";
  await page.route(`${API_URL}/auth/google/start**`, async (route) => {
    started = route.request().url();
    await route.fulfill({ status: 200, contentType: "text/html", body: "<p>google</p>" });
  });
  await google.click();
  await expect.poll(() => started).toContain("/auth/google/start?return_to=%2F");
});

test("the header offers one Sign in button that opens the dialog when Google is enabled", async ({ page }) => {
  await mockApi(page, { "GET /auth/session": withGoogle });
  await page.goto("/atlas");
  await page.getByTestId("header-sign-in").click();
  await expect(page.getByTestId("sign-in-dialog").getByRole("button", { name: "Continue with Google" })).toBeVisible();
});

test("a Google account gets no ChatGPT-plan notice in onboarding", async ({ page }) => {
  await mockApi(page, {
    "GET /auth/session": { ...withGoogle, ...signedInSession({ role: null, age_confirmed: false, auth_provider: "google" }) },
  });
  await page.goto("/welcome");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByTestId("chatgpt-plan-notice")).toHaveCount(0);
});
