import { expect, test } from "@playwright/test";

import { errorEnvelope, setTheme, sseBody, trackConsoleErrors } from "../helpers";
import { DEMO_URL, E, cachedExplanation, mockPathApi, pathShot } from "./fixtures";

test.describe("/path: evidence", () => {
  test("edge evidence with a contradiction next to what it contradicts", async ({ page }) => {
    const errors = trackConsoleErrors(page);
    await setTheme(page, "light");
    await mockPathApi(page);
    await page.goto(DEMO_URL);
    await page.getByRole("radio", { name: /Route 2/ }).check({ force: true });
    await page.locator(`[data-testid="flow-edge-label"][data-edge-id="${E.scnSeizure.id}"]`).click();

    const sheet = page.getByTestId("evidence-sheet");
    await expect(sheet).toBeVisible();
    await expect(sheet.getByTestId("contradiction-notice")).toContainText("1 source contradicts");
    const list = sheet.getByTestId("evidence-list");
    await expect(list.locator('[data-polarity="supports"]')).toHaveCount(2);
    await expect(list.locator('[data-polarity="contradicts"]')).toHaveCount(1);
    await expect(list.getByRole("link", { name: /PMID:12345678/ })).toHaveAttribute("href", "https://pubmed.ncbi.nlm.nih.gov/12345678/");
    await expect(list).toContainText("Peer-reviewed");
    await expect(list).toContainText("Seizures were observed");
    await expect(list).toContainText("Retrieved");
    await expect(sheet.getByTestId("confidence-breakdown")).toContainText("Contradictions 1");
    await pathShot(page, "path-evidence-light", { fullPage: false });
    await page.keyboard.press("Escape");
    await expect(sheet).toBeHidden();
    expect(errors()).toEqual([]);
  });

  test("evidence 501 is explained, not a crash", async ({ page }) => {
    await mockPathApi(page, { "GET /edge/*/evidence": errorEnvelope(501, "not_implemented") });
    await page.goto(DEMO_URL);
    await page.getByTestId("open-evidence").first().click();
    await expect(page.getByTestId("evidence-sheet")).toContainText("not available on this server yet");
  });
});

test.describe("/path: explanation", () => {
  test("streams a cached explanation with citations that highlight the cited step", async ({ page }) => {
    const errors = trackConsoleErrors(page);
    let body: Record<string, unknown> | undefined;
    await mockPathApi(page, {
      "POST /explain": (req: { body: unknown }) => {
        body = req.body as Record<string, unknown>;
        return sseBody(cachedExplanation);
      },
    });
    await page.goto(DEMO_URL);
    const panel = page.getByTestId("explanation");
    await expect(panel.getByTestId("explanation-text")).toContainText("SCN2A Community Alliance");
    await expect(panel.getByTestId("explanation-cached")).toBeVisible();
    await expect(panel.getByText("AI-generated · Dr. Wu")).toBeVisible();
    expect(body).toMatchObject({ edge_ids: [E.similar.id, E.serves.id, E.runs.id], role: "guest", language: "en" });

    const cites = panel.getByTestId("citation");
    await expect(cites).toHaveCount(3);
    await expect(panel.getByTestId("explanation-text")).not.toContainText("[e_");
    await cites.nth(1).click();
    await expect(page.locator(`[data-testid="path-step"][data-edge-id="${E.serves.id}"]`)).toHaveAttribute("data-highlighted", "true");
    await expect(page.locator(`[data-testid="flow-edge-label"][data-edge-id="${E.serves.id}"]`)).toHaveAttribute("data-highlighted", "true");
    expect(errors()).toEqual([]);
  });

  test("re-fetches when the lens changes", async ({ page }) => {
    const roles: unknown[] = [];
    await mockPathApi(page, {
      "POST /explain": (req: { body: unknown }) => {
        roles.push((req.body as { role: string }).role);
        return sseBody(cachedExplanation);
      },
    });
    await page.goto(DEMO_URL);
    await expect(page.getByTestId("explanation-cached")).toBeVisible();
    await page.evaluate(() => {
      localStorage.setItem("amber.lens", "researcher");
      window.dispatchEvent(new StorageEvent("storage", { key: "amber.lens" }));
    });
    await expect.poll(() => roles).toContain("researcher");
    await expect(page.getByTestId("explanation")).toContainText("Researcher lens");
  });

  test("freshly written explanations say so", async ({ page }) => {
    const fresh = cachedExplanation.map((e) => (e.type === "final" ? { ...e, cached: false, role: "patient" } : e));
    await mockPathApi(page, { "POST /explain": sseBody(fresh) }, { signedIn: true });
    await page.goto(DEMO_URL);
    await expect(page.getByTestId("explanation-fresh")).toBeVisible();
  });

  test("guest without a cached explanation sees a quiet sign-in affordance", async ({ page }) => {
    const errors = trackConsoleErrors(page);
    await mockPathApi(page, { "POST /explain": errorEnvelope(401, "sign_in_required") });
    await page.goto(DEMO_URL);
    const cta = page.getByTestId("explain-sign-in");
    await expect(cta).toBeVisible();
    // No dialog popped up unasked.
    await expect(page.getByTestId("sign-in-dialog")).toBeHidden();
    await cta.getByRole("button", { name: "Sign in to have Dr. Wu explain this route" }).click();
    await expect(page.getByTestId("sign-in-dialog")).toBeVisible();
    expect(errors().filter((e) => !/401/.test(e))).toEqual([]);
  });

  test("explanation 501 degrades quietly", async ({ page }) => {
    await mockPathApi(page, { "POST /explain": errorEnvelope(501, "not_implemented") });
    await page.goto(DEMO_URL);
    await expect(page.getByTestId("explain-unavailable")).toBeVisible();
    await expect(page.getByTestId("path-steps")).toBeVisible();
  });
});
