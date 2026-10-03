import { expect, test } from "@playwright/test";

import { errorEnvelope, trackConsoleErrors } from "../helpers";
import { DEMO_URL, E, N, altPath, mockPathApi, okResponse } from "./fixtures";

const PROPOSAL = "<!doctype html><html><head><title>Proposal</title></head><body><h1>Sourced proposal</h1><p>Reuse the registry.</p></body></html>";

test.describe("/path: action view and proposal", () => {
  test("separates viable from unsupported leads", async ({ page }) => {
    await mockPathApi(page);
    await page.goto(DEMO_URL);
    const view = page.getByTestId("action-view");
    // Route 1 rests on a hypothesis link: every lead is unsupported, with the reason.
    await expect(view.getByTestId("viable-leads").getByTestId("lead")).toHaveCount(0);
    const unsupported = view.getByTestId("unsupported-leads").getByTestId("lead");
    await expect(unsupported).toHaveCount(2);
    await expect(unsupported.first()).toContainText("hypothesis");

    // Route 2 is observed data, but one link has contradicting evidence.
    await page.getByRole("radio", { name: /Route 2/ }).check({ force: true });
    await expect(view.getByTestId("unsupported-leads").getByTestId("lead").first()).toContainText("contradicting evidence");
  });

  test("viable when every link is observed, active and uncontradicted", async ({ page }) => {
    const clean = { ...E.scnSeizure, contradiction_count: 0 };
    const path2 = { ...altPath, steps: altPath.steps.map((s) => (s.edge.id === clean.id ? { ...s, edge: clean } : s)) };
    await mockPathApi(page, { "GET /path": { json: { ...okResponse, paths: [path2] } } });
    await page.goto(DEMO_URL);
    const viable = page.getByTestId("viable-leads").getByTestId("lead");
    await expect(viable).toHaveCount(2);
    await expect(viable.filter({ hasText: N.registry.label })).toHaveAttribute("data-viable", "true");
  });

  test("export proposal as a guest asks to sign in", async ({ page }) => {
    let called = false;
    await mockPathApi(page, {
      "POST /proposal": () => {
        called = true;
        return { body: PROPOSAL, contentType: "text/html" };
      },
    });
    await page.goto(DEMO_URL);
    await page.getByTestId("export-proposal").click();
    await expect(page.getByTestId("sign-in-dialog")).toBeVisible();
    expect(called).toBe(false);
  });

  test("signed in: proposal opens as print-ready HTML in a new tab", async ({ page, context }) => {
    const errors = trackConsoleErrors(page);
    let body: Record<string, unknown> | undefined;
    await mockPathApi(
      page,
      {
        "POST /proposal": (req: { body: unknown }) => {
          body = req.body as Record<string, unknown>;
          return { body: PROPOSAL, contentType: "text/html" };
        },
      },
      { signedIn: true },
    );
    await page.goto(DEMO_URL);
    const [popup] = await Promise.all([context.waitForEvent("page"), page.getByTestId("export-proposal").click()]);
    await expect(popup.getByRole("heading", { name: "Sourced proposal" })).toBeVisible();
    expect(body).toMatchObject({ edge_ids: [E.similar.id, E.serves.id, E.runs.id], role: "patient" });
    expect((body!.actions as unknown[]).length).toBe(2);
    expect(errors()).toEqual([]);
  });

  test("proposal 501 is explained", async ({ page }) => {
    await mockPathApi(page, { "POST /proposal": errorEnvelope(501, "not_implemented") }, { signedIn: true });
    await page.goto(DEMO_URL);
    await page.getByTestId("export-proposal").click();
    await expect(page.getByTestId("proposal-error")).toContainText("isn't available on this server yet");
  });
});
