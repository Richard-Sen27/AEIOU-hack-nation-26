/**
 * Live document journey: a synthetic genetic report (fake personal data) is
 * dropped on the landing page after the welcome step, consent is asked just in
 * time, the job runs on the real API with scripted model answers, and
 * the findings are reviewed (snippets, VUS notice, confirm, reject, correct).
 * Start the processes as described in live-helpers.ts, then `PORT=3106 pnpm test:e2e:live`.
 */
import { expect, test } from "@playwright/test";

import {
  API,
  GENETIC_REPORT,
  GENETIC_REPORT_SCRIPT,
  deleteAccount,
  queueModel,
  resetMock,
  shot,
  signInAs,
  storageDump,
  syntheticPdf,
  trackProblems,
  trackUrls,
} from "./live-helpers";

test.describe("documents", () => {
  test.beforeEach(async ({ request }) => resetMock(request));

  test("landing drop, just-in-time consent, upload and review", async ({ page, request }) => {
    await signInAs(page, "bob");
    await deleteAccount(page);
    await page.context().clearCookies();
    await signInAs(page, "bob", "/");
    const problems = trackProblems(page);
    const urls = trackUrls(page);
    try {
      // A first sign-in lands on the welcome step; the report is dropped on
      // the landing page afterwards and handed over to the documents page.
      await page.goto("/");
      await expect(page).toHaveURL(/\/welcome/);
      await page.getByTestId("chatgpt-plan-notice").getByRole("button", { name: "Got it" }).click();
      await page.getByRole("radio", { name: /Patient or family/ }).check();
      await page.getByRole("checkbox", { name: /16 or older/ }).check();
      await page.getByRole("button", { name: /^Continue/ }).click();
      await expect(page).toHaveURL(/\/$/);
      await page.getByTestId("hero-file-input").setInputFiles({
        name: "report.pdf",
        mimeType: "application/pdf",
        buffer: syntheticPdf(GENETIC_REPORT),
      });

      // Just-in-time consent, then the upload starts with the handed-over file.
      await queueModel(request, ...GENETIC_REPORT_SCRIPT);
      const dialog = page.getByTestId("consent-dialog");
      await expect(dialog).toBeVisible();
      await dialog.getByRole("radio", { name: "My own" }).check();
      await dialog.getByRole("checkbox", { name: /explicitly consent/ }).check();
      await dialog.getByRole("button", { name: /I agree/ }).click();
      await expect(page).toHaveURL(/\/documents$/);

      const item = page.getByTestId("upload-item");
      await expect(item).toHaveAttribute("data-status", "done", { timeout: 60_000 });
      await expect(item).toContainText(/\d+ findings to review/);
      await expect(item).toContainText(/original file deleted/i);
      await shot(page, "documents-done");
      await item.getByRole("link", { name: "Review findings" }).click();

      await expect(page.getByTestId("doc-type")).toHaveText("Genetic report");
      const cards = page.getByTestId("finding");
      await expect(cards.first()).toBeVisible();
      await shot(page, "documents-review", { fullPage: true });
      // Variant cards list their HGVS; gene cards share the same snippet line.
      const variants = cards.filter({ hasText: "HGVS" });
      const stxbp1 = variants.filter({ hasText: "c.1162C>T" });
      const scn2a = variants.filter({ hasText: "c.2558G>A" });
      await expect(stxbp1.getByTestId("finding-snippet")).toContainText("c.1162C>T");
      await expect(scn2a.getByTestId("vus-notice")).toContainText("Discuss it with a genetic counselor");
      // Redaction: the fake name never reaches the review screen.
      await expect(page.locator("main")).not.toContainText("Testperson");

      await stxbp1.getByRole("button", { name: /^Confirm/ }).click();
      await expect(stxbp1).toHaveAttribute("data-state", "confirmed");
      await scn2a.getByRole("button", { name: /^Reject/ }).click();
      await expect(scn2a).toHaveAttribute("data-state", "rejected");
      await expect(page.getByTestId("review-progress")).toContainText(/2 of \d+ reviewed/);

      // A wrongly extracted gene is corrected through the entity search.
      const geneCard = cards.filter({ hasNotText: "HGVS" }).filter({ hasText: "SCN2A" });
      await geneCard.getByRole("button", { name: /^Correct / }).click();
      await geneCard.getByTestId("chip-correct").getByRole("textbox").fill("SCN1A");
      await geneCard.getByTestId("chip-correct").getByRole("button", { name: /^SCN1A\b/ }).first().click();
      await expect(geneCard.getByTestId("finding-corrected")).toContainText("SCN1A");

      // The confirmed and the corrected findings are in the profile.
      const profile = await (await page.request.get(`${API}/profile`)).json();
      expect(profile.variants.map((v: { hgvs: string }) => v.hgvs)).toEqual(["c.1162C>T"]);
      await page.goto("/profile");
      await expect(page.getByTestId("profile-variant").getByRole("textbox").first()).toHaveValue("c.1162C>T");
      await expect(page.getByTestId("profile-gene").filter({ hasText: "SCN1A" })).toHaveCount(1);

      expect(urls.some((u) => /STXBP1|Testperson|1162/i.test(decodeURIComponent(u)))).toBe(false);
      expect(await storageDump(page)).not.toMatch(/STXBP1|Testperson/);
      expect(problems()).toEqual([]);
    } finally {
      await deleteAccount(page);
    }
  });
});
