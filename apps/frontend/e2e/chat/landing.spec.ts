import { expect, test, type Page } from "@playwright/test";

import { guestSession, hit, mockApi, setTheme, shot, signedInSession, trackConsoleErrors } from "../helpers";

const STORY = "My daughter is 2, diagnosed with STXBP1 last month. Lots of seizures, not walking yet, no problems with eating.";

/** Every request URL the page makes, to prove free text never leaves in a URL. */
function trackUrls(page: Page) {
  const urls: string[] = [];
  page.on("request", (r) => urls.push(r.url()));
  return urls;
}

const input = (page: Page) => page.getByRole("textbox", { name: /Describe the diagnosis/ });

test.describe("landing", () => {
  test("guest entity search opens the node", async ({ page }) => {
    const searched: string[] = [];
    await mockApi(page, {
      "GET /auth/session": guestSession,
      "GET /search": (req: { url: string }) => {
        searched.push(new URL(req.url).searchParams.get("q") ?? "");
        return { json: { results: [hit("MONDO:9900007", "disease", "STXBP1 encephalopathy", "Ohtahara syndrome")] } };
      },
    });
    const errors = trackConsoleErrors(page);
    await page.goto("/");
    await input(page).fill("Ohtahara syndrome");
    await expect(page.getByTestId("hero-hint")).toHaveAttribute("data-mode", "search");
    await input(page).press("Enter");
    await expect(page).toHaveURL(/\/node\/MONDO%3A9900007$/);
    expect(searched).toEqual(["Ohtahara syndrome"]);
    expect(errors()).toEqual([]);
  });

  test("guest free text offers sign-in and is sent nowhere", async ({ page }) => {
    await mockApi(page, { "GET /auth/session": guestSession, "GET /search": { results: [] } });
    const urls = trackUrls(page);
    const posts: string[] = [];
    page.on("request", (r) => {
      if (r.method() !== "GET") posts.push(r.postData() ?? "");
    });
    await page.goto("/");
    await input(page).fill(STORY);
    await expect(page.getByTestId("hero-hint")).toHaveAttribute("data-mode", "assistant");
    await page.getByRole("button", { name: "Send to Dr. Wu" }).click();
    const dialog = page.getByTestId("sign-in-dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("type it again");
    await expect(dialog.getByRole("button", { name: /Continue with ChatGPT/ })).toBeVisible();
    await page.keyboard.press("Escape");
    // Still on the page, so nothing is lost while they decide.
    await expect(input(page)).toHaveValue(STORY);
    expect(urls.filter((u) => u.includes("/search"))).toEqual([]);
    expect(urls.some((u) => u.includes("daughter") || u.includes("STXBP1"))).toBe(false);
    expect(posts.some((p) => p.includes("daughter"))).toBe(false);
    const stored = await page.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }));
    expect(stored).not.toContain("daughter");
  });

  test("signed-in free text arrives in the chat, never in the URL", async ({ page }) => {
    const bodies: unknown[] = [];
    await mockApi(page, {
      "GET /auth/session": signedInSession(),
      "GET /profile": {},
      "GET /chat/sessions": [],
      "POST /chat": (req: { body: unknown }) => {
        bodies.push(req.body);
        return {
          contentType: "text/event-stream",
          body: `event: summary_delta\ndata: ${JSON.stringify({ type: "summary_delta", text: "Thanks." })}\n\n`,
        };
      },
    });
    const urls = trackUrls(page);
    await page.goto("/");
    await input(page).fill(STORY);
    await input(page).press("Enter");
    await expect(page).toHaveURL(/\/chat$/);
    await expect(page.getByTestId("user-message").first()).toContainText("STXBP1 last month");
    await expect.poll(() => bodies.length).toBe(1);
    expect((bodies[0] as { message: string }).message).toBe(STORY);
    expect(urls.some((u) => u.includes("daughter"))).toBe(false);
  });

  test("dropping a file goes through the upload consent gate", async ({ page }) => {
    let consentPosted = false;
    await mockApi(page, {
      "GET /auth/session": () =>
        ({ json: signedInSession({ consents: consentPosted ? ["upload"] : [] }) }),
      "GET /profile": {},
      "POST /consents": () => {
        consentPosted = true;
        return { json: { consent_type: "upload", version: "1", granted_at: new Date().toISOString(), revoked_at: null } };
      },
      "GET /documents": [],
    });
    await page.goto("/");
    await expect(page.getByTestId("entry-patient")).toBeVisible();
    const dt = await page.evaluateHandle(() => {
      const d = new DataTransfer();
      d.items.add(new File(["%PDF-1.4"], "report.pdf", { type: "application/pdf" }));
      return d;
    });
    const form = page.getByTestId("hero-input");
    await form.dispatchEvent("dragenter", { dataTransfer: dt });
    await expect(form).toHaveAttribute("data-dragging", "true");
    await form.dispatchEvent("drop", { dataTransfer: dt });
    const consent = page.getByRole("dialog");
    await expect(consent).toBeVisible();
    await expect(page).toHaveURL(/\/$/);
  });

  test("guest drop asks for sign-in first", async ({ page }) => {
    await mockApi(page, { "GET /auth/session": guestSession });
    await page.goto("/");
    await page.getByTestId("hero-file-input").setInputFiles({ name: "r.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF") });
    await expect(page.getByTestId("sign-in-dialog")).toBeVisible();
  });

  test("role entry points and demo shortcut", async ({ page }) => {
    await mockApi(page, { "GET /auth/session": { ...guestSession, demo_mode: true } });
    await page.goto("/");
    await expect(page.getByTestId("demo-journey")).toBeVisible();
    // Guests see the tour first.
    await expect(page.getByTestId("entry-guest")).toContainText("Your view");
    await page.getByTestId("entry-researcher").click();
    await expect(page).toHaveURL(/\/clusters$/);
    await page.goBack();
    await page.getByTestId("entry-guest").click();
    await expect(page).toHaveURL(/\/atlas\?tour=1$/);
  });

  for (const theme of ["light", "dark"] as const) {
    test(`screenshot ${theme}`, async ({ page }) => {
      await setTheme(page, theme);
      await mockApi(page, { "GET /auth/session": { ...guestSession, demo_mode: true } });
      await page.goto("/");
      await expect(page.getByTestId("entry-guest")).toBeVisible();
      await input(page).fill(STORY);
      await shot(page, `chat-landing-${theme}`, { fullPage: true });
    });
  }

  test("screenshot phone @mobile", async ({ page }) => {
    await mockApi(page, { "GET /auth/session": guestSession });
    await page.goto("/");
    await expect(page.getByTestId("entry-guest")).toBeVisible();
    await shot(page, "chat-landing-mobile", { fullPage: true });
  });
});
