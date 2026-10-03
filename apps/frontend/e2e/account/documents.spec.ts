import { expect, test } from "@playwright/test";

import { errorEnvelope, guestSession, mockApi, setTheme, shot, signedInSession, sseBody, trackConsoleErrors } from "../helpers";
import { expectNoHealthDataInBrowser } from "./fixtures";

const DOC_ID = "11111111-2222-3333-4444-555555555555";
const PDF = { name: "Report Maria Example.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 test") };

const DOC = {
  id: DOC_ID,
  status: "ready",
  doc_type: "genetic_report",
  page_count: 3,
  created_at: "2026-10-04T09:00:00Z",
  raw_deleted_at: "2026-10-04T09:00:20Z",
};

const FINDINGS = [
  {
    id: "f1",
    document_id: DOC_ID,
    type: "gene",
    value: "STXBP1",
    normalized_id: "HGNC:11444",
    page: 1,
    snippet: "Sequencing identified a variant in STXBP1 in [NAME].",
    confirmed: null,
    payload: { label: "STXBP1" },
  },
  {
    id: "f2",
    document_id: DOC_ID,
    type: "variant",
    value: "NM_003165.6:c.1631G>A",
    normalized_id: null,
    page: 2,
    snippet: "Variant NM_003165.6:c.1631G>A (heterozygous), classified as a variant of uncertain significance.",
    confirmed: null,
    payload: { hgvs: "NM_003165.6:c.1631G>A", zygosity: "heterozygous", classification: "uncertain_significance", test_date: "2026-08-12" },
    vus_notice: "This result is uncertain. Discuss it with a genetic counselor before acting on it.",
  },
  {
    id: "f3",
    document_id: DOC_ID,
    type: "phenotype",
    value: "Seizure",
    normalized_id: "HP:0001250",
    page: 1,
    snippet: "Frequent seizures since infancy.",
    confirmed: null,
    payload: { label: "Seizure" },
  },
];

const JOB_EVENTS = [
  { type: "progress", job_id: "j1", stage: "extracting_text", percent: 20 },
  { type: "progress", job_id: "j1", stage: "redacting", percent: 40 },
  { type: "progress", job_id: "j1", stage: "classifying", percent: 60 },
  { type: "progress", job_id: "j1", stage: "extracting_findings", percent: 80 },
  { type: "done", job_id: "j1", document_id: DOC_ID, finding_count: 3 },
];

function mocks(extra: Record<string, unknown> = {}) {
  return {
    "GET /auth/session": signedInSession({ consents: ["upload"] }),
    "GET /documents": [DOC],
    "GET /documents/*/findings": FINDINGS,
    "POST /documents": { status: 202, json: { job_id: "j1", document_id: DOC_ID } },
    "GET /jobs/*": sseBody(JOB_EVENTS),
    ...extra,
  };
}

test("upload: consent gate, real stages, then findings review with confirm and reject", async ({ page }) => {
  let uploadedName = "";
  let session = signedInSession({ consents: [] });
  const decisions: string[] = [];
  await mockApi(
    page,
    mocks({
      "GET /auth/session": () => ({ json: session }),
      "POST /consents": (req: { body: unknown }) => {
        session = signedInSession({ consents: ["upload"] });
        return { status: 201, json: { id: "c1", ...(req.body as object), granted_at: new Date().toISOString(), active: true } };
      },
      "POST /documents": async (req: { request: import("@playwright/test").Request }) => {
        const body = req.request.postDataBuffer()?.toString("latin1") ?? "";
        uploadedName = body.match(/filename="([^"]+)"/)?.[1] ?? "";
        return { status: 202, json: { job_id: "j1", document_id: DOC_ID } };
      },
      "POST /findings/*/confirm": (req: { url: string }) => {
        decisions.push(`confirm ${req.url.split("/").at(-2)}`);
        return { json: {} };
      },
      "POST /findings/*/reject": (req: { url: string }) => {
        decisions.push(`reject ${req.url.split("/").at(-2)}`);
        return { json: {} };
      },
    }),
  );
  const errors = trackConsoleErrors(page);
  await page.goto("/documents");
  await page.getByTestId("file-input").setInputFiles(PDF);

  // Consent first.
  const consent = page.getByTestId("consent-content-upload");
  await expect(consent).toBeVisible();
  await consent.getByRole("radio", { name: "My own" }).click();
  await consent.getByRole("checkbox", { name: /explicitly consent/ }).click();
  await consent.getByRole("button", { name: "I agree, continue" }).click();

  const item = page.getByTestId("upload-item");
  await expect(item).toHaveAttribute("data-status", "done");
  await expect(item).toContainText("3 findings to review");
  await expect(item).toContainText("original file deleted");
  for (const stage of ["extracting_text", "redacting", "classifying", "extracting_findings"]) {
    await expect(item.locator(`[data-stage="${stage}"]`)).toHaveAttribute("data-state", "done");
  }
  // The file name (which can contain a patient's name) is never sent.
  expect(uploadedName).toBe("document.pdf");

  await item.getByRole("link", { name: "Review findings" }).click();
  await expect(page).toHaveURL(new RegExp(`/documents/${DOC_ID}$`));
  await expect(page.getByTestId("doc-type")).toHaveText("Genetic report");
  await expect(page.getByTestId("raw-deleted")).toContainText("Deleted");
  await expect(page.getByTestId("review-notice")).toContainText("Nothing is used until you confirm it.");
  await expect(page.getByTestId("review-notice")).toContainText("redacted text");
  await expect(page.getByTestId("review-notice")).toContainText("AI-generated");

  const cards = page.getByTestId("finding");
  await expect(cards).toHaveCount(3);
  await expect(cards.nth(0).getByTestId("finding-snippet").locator("mark")).toHaveText("STXBP1");
  await expect(cards.nth(0)).toContainText("Page 1");
  await expect(cards.nth(1).getByTestId("vus-notice")).toContainText(
    "This result is uncertain. Discuss it with a genetic counselor before acting on it.",
  );
  await expect(page.getByTestId("review-done")).toHaveCount(0);

  await cards.nth(0).getByRole("button", { name: /^Confirm/ }).click();
  await expect(cards.nth(0)).toHaveAttribute("data-state", "confirmed");
  await cards.nth(1).getByRole("button", { name: /^Reject/ }).click();
  await expect(cards.nth(1)).toHaveAttribute("data-state", "rejected");
  await cards.nth(2).getByRole("button", { name: /^Confirm/ }).click();
  await expect(page.getByTestId("review-progress")).toHaveText("3 of 3 reviewed");

  const done = page.getByTestId("review-done");
  await expect(done).toContainText("2 findings are now in your profile");
  await expect(done.getByRole("link", { name: /See my profile/ })).toHaveAttribute("href", "/profile");
  await expect(done.getByRole("link", { name: /Ask Dr. Wu/ })).toHaveAttribute("href", "/chat");
  expect(decisions).toEqual(["confirm f1", "reject f2", "confirm f3"]);

  await expectNoHealthDataInBrowser(page, ["STXBP1", "NM_003165", "Seizure", "Maria Example"]);
  expect(errors()).toEqual([]);
});

test("upload: job failure shows the reason by error code", async ({ page }) => {
  await mockApi(
    page,
    mocks({
      "GET /jobs/*": sseBody([
        { type: "progress", job_id: "j1", stage: "extracting_text", percent: 20 },
        { type: "error", job_id: "j1", code: "payload_too_large", message: "The document has more than 30 pages." },
      ]),
    }),
  );
  await page.goto("/documents");
  await page.getByTestId("file-input").setInputFiles(PDF);
  const err = page.getByTestId("upload-error");
  await expect(err).toHaveAttribute("data-code", "payload_too_large");
  await expect(err).toContainText("more than 30 pages");
});

test("upload: rate limit message", async ({ page }) => {
  await mockApi(page, mocks({ "POST /documents": errorEnvelope(429, "rate_limited", "Too many requests") }));
  await page.goto("/documents");
  await page.getByTestId("file-input").setInputFiles(PDF);
  await expect(page.getByTestId("upload-error")).toContainText("10 documents in the last hour");
});

test("upload: unsupported type and too-large files are stopped before sending", async ({ page }) => {
  let posted = 0;
  await mockApi(page, mocks({ "POST /documents": () => ((posted += 1), { status: 202, json: { job_id: "j1", document_id: DOC_ID } }) }));
  await page.goto("/documents");
  await page.getByTestId("file-input").setInputFiles({ name: "x.exe", mimeType: "application/x-msdownload", buffer: Buffer.from("MZ") });
  await expect(page.getByTestId("upload-error")).toHaveAttribute("data-code", "unsupported_media_type");
  await page.getByTestId("file-input").setInputFiles({ name: "big.pdf", mimeType: "application/pdf", buffer: Buffer.alloc(21 * 1024 * 1024) });
  await expect(page.getByTestId("upload-error").nth(1)).toHaveAttribute("data-code", "payload_too_large");
  expect(posted).toBe(0);
});

test("upload: 501 degrades gracefully", async ({ page }) => {
  await mockApi(page, mocks({ "POST /documents": errorEnvelope(501, "not_implemented", "Not implemented"), "GET /documents": errorEnvelope(501, "not_implemented") }));
  await page.goto("/documents");
  await expect(page.getByText("Your documents list is not available yet.")).toBeVisible();
  await page.getByTestId("file-input").setInputFiles(PDF);
  await expect(page.getByTestId("upload-error")).toContainText("not available yet");
});

test("pending uploads from the landing page are picked up", async ({ page }) => {
  let posted = 0;
  await mockApi(page, mocks({ "POST /documents": () => ((posted += 1), { status: 202, json: { job_id: "j1", document_id: DOC_ID } }) }));
  await page.goto("/");
  await page.getByTestId("hero-file-input").setInputFiles(PDF);
  await expect(page).toHaveURL(/\/documents$/);
  await expect(page.getByTestId("upload-item")).toHaveAttribute("data-status", "done");
  expect(posted).toBe(1);
});

test("document list: status and delete", async ({ page }) => {
  let deleted = "";
  await mockApi(
    page,
    mocks({
      "GET /documents": () => ({ json: deleted ? [] : [DOC, { ...DOC, id: "d2", status: "failed", doc_type: null }] }),
      "DELETE /documents/*": (req: { url: string }) => {
        deleted = req.url.split("/").pop()!;
        return { status: 204, body: "" };
      },
    }),
  );
  await page.goto("/documents");
  const rows = page.getByTestId("document-row");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText("Ready to review");
  await expect(rows.nth(1)).toContainText("Could not be read");
  await rows.nth(0).getByTestId("delete-document").click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByText("No documents yet.")).toBeVisible();
  expect(deleted).toBe(DOC_ID);
});

test("guest sees a sign-in prompt on documents and findings", async ({ page }) => {
  await mockApi(page, { "GET /auth/session": guestSession });
  const errors = trackConsoleErrors(page);
  await page.goto("/documents");
  await expect(page.getByTestId("sign-in-prompt")).toContainText("Sign in to upload a report");
  await page.goto(`/documents/${DOC_ID}`);
  await expect(page.getByTestId("sign-in-prompt")).toContainText("Sign in to review findings");
  expect(errors()).toEqual([]);
});

test("screenshots: documents and review, light and dark", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockApi(
    page,
    mocks({
      "GET /documents/*/findings": [{ ...FINDINGS[0], confirmed: true }, FINDINGS[1], FINDINGS[2]],
      "GET /jobs/*": sseBody(JOB_EVENTS.slice(0, 3)),
    }),
  );
  for (const theme of ["light", "dark"] as const) {
    await setTheme(page, theme);
    await page.goto("/documents");
    await expect(page.getByTestId("document-row")).toHaveCount(1);
    await shot(page, `account-documents-${theme}`, { fullPage: true });
    await page.goto(`/documents/${DOC_ID}`);
    await expect(page.getByTestId("finding")).toHaveCount(3);
    await shot(page, `account-review-${theme}`, { fullPage: true });
  }
});

test("upload progress screenshot", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  // The job stream never answers, so the progress view stays on screen.
  await mockApi(page, mocks({ "GET /jobs/*": () => new Promise(() => {}) }));
  await page.goto("/documents");
  await page.getByTestId("file-input").setInputFiles(PDF);
  await expect(page.getByTestId("upload-item")).toHaveAttribute("data-status", "processing");
  await shot(page, "account-upload-progress");
});

test("documents and review on a phone @mobile", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockApi(page, mocks());
  await page.goto("/documents");
  await expect(page.getByTestId("document-row")).toHaveCount(1);
  await shot(page, "account-documents-mobile", { fullPage: true });
  await page.goto(`/documents/${DOC_ID}`);
  await expect(page.getByTestId("finding")).toHaveCount(3);
  await shot(page, "account-review-mobile", { fullPage: true });
});
