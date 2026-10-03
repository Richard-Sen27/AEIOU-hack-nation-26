import { expect, test } from "@playwright/test";

import { errorEnvelope, setTheme, sseBody, trackConsoleErrors } from "../helpers";
import { N, NO_ROUTE_URL, mockPathApi, pathShot } from "./fixtures";

const candidate = {
  source_id: N.stxbp1.id,
  target_id: N.dravet.id,
  relation: "shared_pathway",
  quote: "Both STXBP1 and SCN1A variants impair inhibitory synaptic transmission in mouse models.",
  source_url: "https://pubmed.ncbi.nlm.nih.gov/11112222/",
  source_type: "pubmed",
  source_id_ref: "PMID:11112222",
  origin: "inferred",
  status: "pending_review",
};

const gapEvents = (stop: "completed" | "timeout" = "completed") => [
  { type: "progress", step: 1, tool: "pubmed_search", message: "Searching PubMed for STXBP1 and Dravet syndrome", elapsed_s: 2.1 },
  { type: "progress", step: 2, tool: "fetch_page", message: "Reading PMID:11112222", elapsed_s: 9.4 },
  { type: "candidate", candidate },
  { type: "progress", step: 3, tool: "clinicaltrials_search", message: "Searching ClinicalTrials.gov", elapsed_s: 14.0 },
  { type: "final", candidate_count: 1, stop_reason: stop },
];

test.describe("/path: no supported route", () => {
  test("says so plainly and shows the coverage report", async ({ page }) => {
    const errors = trackConsoleErrors(page);
    await setTheme(page, "light");
    await mockPathApi(page);
    await page.goto(NO_ROUTE_URL);

    await expect(page.getByTestId("no-route-statement")).toContainText(
      "No supported route between SYNGAP1-related intellectual disability and Dravet syndrome",
    );
    const table = page.getByTestId("sources-queried");
    await expect(table).toContainText("ClinVar");
    await expect(table).toContainText("31");
    await expect(page.getByTestId("missing-link")).toContainText("No source links STXBP1 encephalopathy to Dravet syndrome");
    await expect(page.getByTestId("suggested-question")).toContainText("same synaptic pathway");

    // Partial path: visibly incomplete; the missing link is not drawn as a link.
    const flow = page.getByTestId("path-flow");
    await expect(flow.getByTestId("flow-edge-label")).toHaveCount(1);
    await expect(flow.getByTestId("flow-missing-link")).toBeVisible();
    await expect(flow.getByTestId("flow-node")).toHaveCount(3);
    await expect(page.getByTestId("path-step-missing")).toContainText("Missing link");
    // No route result, no action view, no explanation.
    await expect(page.getByTestId("path-result")).toHaveCount(0);
    await expect(page.getByTestId("action-view")).toHaveCount(0);
    await pathShot(page, "path-no-route-light");
    expect(errors()).toEqual([]);
  });

  test("dark and phone screenshots @mobile", async ({ page }) => {
    await setTheme(page, "dark");
    await mockPathApi(page);
    await page.goto(NO_ROUTE_URL);
    await expect(page.getByTestId("coverage-report")).toBeVisible();
    await pathShot(page, "path-no-route-mobile-dark");
  });

  test("dark desktop", async ({ page }) => {
    await setTheme(page, "dark");
    await mockPathApi(page);
    await page.goto(NO_ROUTE_URL);
    await expect(page.getByTestId("coverage-report")).toBeVisible();
    await pathShot(page, "path-no-route-dark");
  });
});

test.describe("/path: gap search", () => {
  test("guests are asked to sign in and nothing is sent", async ({ page }) => {
    let called = false;
    await mockPathApi(page, {
      "POST /gap-search": () => {
        called = true;
        return sseBody(gapEvents());
      },
    });
    await page.goto(NO_ROUTE_URL);
    await page.getByTestId("gap-start").click();
    await expect(page.getByTestId("sign-in-dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    expect(called).toBe(false);
    await expect(page.getByTestId("gap-progress")).toHaveCount(0);
  });

  test("signed in: progress, candidates with pending-review label", async ({ page }) => {
    const errors = trackConsoleErrors(page);
    let body: unknown;
    await mockPathApi(
      page,
      {
        "POST /gap-search": (req: { body: unknown }) => {
          body = req.body;
          return sseBody(gapEvents());
        },
      },
      { signedIn: true },
    );
    await page.goto(NO_ROUTE_URL);
    await page.getByTestId("gap-start").click();
    expect(body).toMatchObject({ from_id: N.stxbp1.id, to_id: N.dravet.id, family: "all" });
    await expect(page.getByTestId("gap-search").getByTestId("ai-disclosure")).toBeVisible();
    await expect(page.getByTestId("gap-progress")).toContainText("Searching PubMed for STXBP1");
    await expect(page.getByTestId("gap-progress")).toContainText("ClinicalTrials.gov");
    const card = page.getByTestId("gap-candidate");
    await expect(card).toHaveCount(1);
    await expect(card.getByTestId("pending-review-label")).toHaveText("Pending review, not part of the trusted graph");
    await expect(card).toContainText("impair inhibitory synaptic transmission");
    await expect(card.getByRole("link", { name: /PMID:11112222/ })).toHaveAttribute("href", candidate.source_url);
    await expect(page.getByTestId("gap-ending")).toHaveAttribute("data-ending", "completed");
    await expect(page.getByTestId("gap-ending")).toContainText("1 candidate link found");
    await pathShot(page, "path-gap-search-light");
    expect(errors()).toEqual([]);
  });

  test("gap search dark @mobile", async ({ page }) => {
    await setTheme(page, "dark");
    await mockPathApi(page, { "POST /gap-search": sseBody(gapEvents()) }, { signedIn: true });
    await page.goto(NO_ROUTE_URL);
    await page.getByTestId("gap-start").click();
    await expect(page.getByTestId("gap-candidate")).toHaveCount(1);
    await pathShot(page, "path-gap-search-mobile-dark");
  });

  test("timeout ending is explained", async ({ page }) => {
    await mockPathApi(page, { "POST /gap-search": sseBody(gapEvents("timeout")) }, { signedIn: true });
    await page.goto(NO_ROUTE_URL);
    await page.getByTestId("gap-start").click();
    await expect(page.getByTestId("gap-ending")).toHaveAttribute("data-ending", "timeout");
    await expect(page.getByTestId("gap-ending")).toContainText("Stopped after 90 seconds");
    await expect(page.getByTestId("gap-candidate")).toHaveCount(1);
  });

  test("usage limit and 501 endings", async ({ page }) => {
    await mockPathApi(
      page,
      {
        "POST /gap-search": sseBody([
          { type: "progress", step: 1, tool: "pubmed_search", message: "Searching PubMed", elapsed_s: 1 },
          { type: "error", code: "rate_limited", message: "Too many requests" },
        ]),
      },
      { signedIn: true },
    );
    await page.goto(NO_ROUTE_URL);
    await page.getByTestId("gap-start").click();
    await expect(page.getByTestId("gap-ending")).toContainText("usage limit");

    await page.unrouteAll();
    await mockPathApi(page, { "POST /gap-search": errorEnvelope(501, "not_implemented") }, { signedIn: true });
    await page.getByTestId("gap-start").click();
    await expect(page.getByTestId("gap-ending")).toContainText("isn't available on this server yet");
  });

  test("submitting a candidate asks for contribute consent, then posts it", async ({ page }) => {
    const posted: unknown[] = [];
    await mockPathApi(
      page,
      {
        "POST /gap-search": sseBody(gapEvents()),
        "POST /consents": { id: "c1", consent_type: "contribute", version: "1", granted_at: "2026-10-04T00:00:00Z", active: true },
        "POST /contributions": (req: { body: unknown }) => {
          posted.push(req.body);
          return { status: 201, json: { id: "k1", kind: "candidate_edge", payload: {}, status: "pending_review", origin: "user_contributed", created_at: "2026-10-04T00:00:00Z" } };
        },
      },
      { signedIn: true },
    );
    await page.goto(NO_ROUTE_URL);
    await page.getByTestId("gap-start").click();
    await page.getByTestId("submit-candidate").click();
    const consent = page.getByRole("dialog");
    await expect(consent).toBeVisible();
    expect(posted).toHaveLength(0);
    await consent.screenshot({ path: "e2e/screenshots/path-consent.png" });
  });

  test("with consent the candidate is submitted for review", async ({ page }) => {
    const posted: unknown[] = [];
    await mockPathApi(
      page,
      {
        "GET /auth/session": { user: { id: "00000000-0000-0000-0000-000000000001", name: "Maria", email: "m@example.org", role: "patient", role_verified: false, language: "en", expert_mode: false, age_confirmed: true, consents: ["contribute"] }, gpc: false, demo_mode: false, data_version: "t" },
        "POST /gap-search": sseBody(gapEvents()),
        "POST /contributions": (req: { body: unknown }) => {
          posted.push(req.body);
          return { status: 201, json: { id: "k1", kind: "candidate_edge", payload: {}, status: "pending_review", origin: "user_contributed", created_at: "2026-10-04T00:00:00Z" } };
        },
      },
    );
    await page.goto(NO_ROUTE_URL);
    await page.getByTestId("gap-start").click();
    await page.getByTestId("submit-candidate").click();
    await expect(page.getByTestId("candidate-submitted")).toBeVisible();
    expect(posted[0]).toMatchObject({
      kind: "candidate_edge",
      payload: { source_id: N.stxbp1.id, target_id: N.dravet.id, relation: "shared_pathway", source_id_ref: "PMID:11112222" },
    });
  });

  test("a rejected quote shows the server's field error", async ({ page }) => {
    await mockPathApi(page, {
      "GET /auth/session": { user: { id: "u", name: "M", email: "m@example.org", role: "patient", role_verified: false, language: "en", expert_mode: false, age_confirmed: true, consents: ["contribute"] }, gpc: false, demo_mode: false, data_version: "t" },
      "POST /gap-search": sseBody(gapEvents()),
      "POST /contributions": errorEnvelope(422, "validation_error", "Invalid request fields: payload.quote."),
    });
    await page.goto(NO_ROUTE_URL);
    await page.getByTestId("gap-start").click();
    await page.getByTestId("submit-candidate").click();
    await expect(page.getByTestId("gap-candidate").getByRole("alert")).toContainText("payload.quote");
  });
});
