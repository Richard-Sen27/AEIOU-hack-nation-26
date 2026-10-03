import { expect, test } from "@playwright/test";

import { errorEnvelope, setTheme, trackConsoleErrors } from "../helpers";
import { DEMO_URL, N, mockPathApi, okResponse, pathShot } from "./fixtures";

test.describe("/path: route", () => {
  test("prefilled route renders steps in order with trust badges", async ({ page }) => {
    const errors = trackConsoleErrors(page);
    await setTheme(page, "light");
    await mockPathApi(page);
    await page.goto(DEMO_URL);

    await expect(page.getByRole("heading", { level: 1 })).toContainText("STXBP1 encephalopathy");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Sodium Channel Epilepsy Registry");

    // Flow: nodes in traversal order, edges with relation, confidence, origin.
    const flowNodes = page.getByTestId("path-flow").getByTestId("flow-node");
    await expect(flowNodes).toHaveCount(4);
    await expect(flowNodes.nth(0)).toHaveAttribute("data-node-id", N.stxbp1.id);
    await expect(flowNodes.nth(3)).toHaveAttribute("data-node-id", N.registry.id);
    const labels = page.getByTestId("flow-edge-label");
    await expect(labels).toHaveCount(3);
    await expect(labels.nth(0)).toContainText("similar experience");
    await expect(labels.nth(0)).toContainText("High");
    await expect(labels.nth(0)).toContainText("Hypothesis");
    await expect(labels.nth(0)).toHaveAttribute("data-origin", "inferred");
    await expect(labels.nth(1)).toContainText("Data");

    // Ordered list equivalent.
    const steps = page.getByTestId("path-steps").getByTestId("path-step");
    await expect(steps).toHaveCount(3);
    await expect(steps.nth(0)).toHaveAttribute("data-edge-id", "e_3b8845b635b8");
    await expect(steps.nth(2)).toHaveAttribute("data-edge-id", "e_558f7d2a940d");
    await expect(steps.nth(0).getByTestId("origin-badge")).toHaveAttribute("data-origin", "inferred");
    await expect(steps.nth(0).getByTestId("confidence-badge")).toContainText("High");

    // Plain statement of what the route rests on.
    await expect(page.getByTestId("trust-summary")).toContainText("Includes 1 hypothesis link");

    // Nodes link to /node/[id].
    await expect(flowNodes.nth(0).getByRole("link")).toHaveAttribute("href", `/node/${encodeURIComponent(N.stxbp1.id)}`);

    await pathShot(page, "path-supported-light");
    expect(errors()).toEqual([]);
  });

  test("dark theme screenshot", async ({ page }) => {
    await setTheme(page, "dark");
    await mockPathApi(page);
    await page.goto(DEMO_URL);
    await expect(page.getByTestId("flow-edge-label")).toHaveCount(3);
    await pathShot(page, "path-supported-dark");
  });

  test("selecting an alternative shows it in the flow and the list", async ({ page }) => {
    const errors = trackConsoleErrors(page);
    await mockPathApi(page);
    await page.goto(DEMO_URL);
    const options = page.getByTestId("route-option");
    await expect(options).toHaveCount(2);
    await expect(options.nth(0)).toHaveAttribute("data-selected", "true");
    await page.getByRole("radio", { name: /Route 2/ }).check({ force: true });
    await expect(options.nth(1)).toHaveAttribute("data-selected", "true");
    await expect(page.getByTestId("path-steps").getByTestId("path-step")).toHaveCount(4);
    await expect(page.getByTestId("flow-edge-label")).toHaveCount(4);
    await expect(page.getByTestId("trust-summary")).toHaveAttribute("data-observed-only", "true");
    await expect(page.getByTestId("trust-summary")).toContainText("Only observed data");
    expect(errors()).toEqual([]);
  });

  test("changing the family and swapping re-query with the new parameters", async ({ page }) => {
    const calls: string[] = [];
    await mockPathApi(page, {
      "GET /path": (req: { url: string }) => {
        calls.push(new URL(req.url).search);
        return { json: okResponse };
      },
    });
    await page.goto(DEMO_URL);
    await expect(page.getByTestId("path-result")).toBeVisible();
    await page.getByTestId("family-filter").getByText("Similar symptoms").click();
    await expect(page).toHaveURL(/family=symptoms/);
    await expect.poll(() => calls.at(-1)).toContain("family=symptoms");

    await page.getByTestId("swap").click();
    await expect(page).toHaveURL(new RegExp(`from=${encodeURIComponent(N.registry.id)}`));
    await expect
      .poll(() => calls.at(-1))
      .toContain(`from=${encodeURIComponent(N.registry.id)}&to=${encodeURIComponent(N.stxbp1.id)}`);
  });

  test("picking from and to with the entity search", async ({ page }) => {
    await mockPathApi(page);
    await page.goto("/path");
    await expect(page.getByTestId("path-empty")).toBeVisible();
    await page.getByRole("combobox", { name: "From" }).fill("STXBP1");
    const opt = page.getByRole("option", { name: /STXBP1 encephalopathy/ });
    await expect(opt).toContainText("STXBP1-DEE");
    await opt.click();
    await expect(page).toHaveURL(/from=MONDO%3A9900007/);

    // Only from: help choose a target.
    await expect(page.getByTestId("target-suggestions")).toBeVisible();
    await page.getByTestId("suggested-target").filter({ hasText: "Sodium Channel" }).click();
    await expect(page).toHaveURL(/to=REG%3Afx-sodium-channel-registry/);
    await expect(page.getByTestId("path-result")).toBeVisible();
  });

  test("ordered list is keyboard reachable and opens evidence", async ({ page }) => {
    await mockPathApi(page);
    await page.goto(DEMO_URL);
    const btn = page.getByTestId("path-steps").getByTestId("open-evidence").first();
    await btn.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("evidence-sheet")).toBeVisible();
  });

  test("501 and network errors degrade gracefully", async ({ page }) => {
    const errors = trackConsoleErrors(page);
    await mockPathApi(page, { "GET /path": errorEnvelope(501, "not_implemented") });
    await page.goto(DEMO_URL);
    await expect(page.getByTestId("path-error")).toHaveAttribute("data-code", "not_implemented");
    await expect(page.getByTestId("path-error")).toContainText("isn't available yet");
    await expect(page.getByTestId("path-error").getByRole("button", { name: "Try again" })).toBeVisible();
    expect(errors().filter((e) => !/501/.test(e))).toEqual([]);
  });

  test("404 asks to pick again", async ({ page }) => {
    await mockPathApi(page, { "GET /path": errorEnvelope(404, "not_found") });
    await page.goto(DEMO_URL);
    await expect(page.getByTestId("path-error")).toContainText("isn't in the atlas");
  });

  test("offline API", async ({ page }) => {
    await mockPathApi(page, { "GET /path": "offline" });
    await page.goto(DEMO_URL);
    await expect(page.getByTestId("path-error")).toHaveAttribute("data-code", "network_error");
  });

  test("phone layout @mobile", async ({ page }) => {
    await setTheme(page, "light");
    await mockPathApi(page);
    await page.goto(DEMO_URL);
    await expect(page.getByTestId("path-flow")).toHaveAttribute("data-orientation", "vertical");
    await pathShot(page, "path-supported-mobile");
  });

  test("phone layout dark @mobile", async ({ page }) => {
    await setTheme(page, "dark");
    await mockPathApi(page);
    await page.goto(DEMO_URL);
    await expect(page.getByTestId("flow-edge-label")).toHaveCount(3);
    await pathShot(page, "path-supported-mobile-dark");
  });
});
