import { expect, test } from "@playwright/test";

import { mockApi, setTheme, shot, trackConsoleErrors } from "../helpers";
import { graphMocks } from "./fixtures";

test.describe("guided tour", () => {
  test("starts from ?tour=1, is keyboard operable and skippable", async ({ page }) => {
    await mockApi(page, graphMocks());
    const errors = trackConsoleErrors(page);
    await page.goto("/atlas?tour=1");
    const tour = page.getByTestId("atlas-tour");
    await expect(tour).toBeVisible();
    await expect(tour).toContainText("1 of 5");
    await expect(tour).toContainText("Every dot is one thing");
    await expect(page.getByTestId("tour-next")).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(tour).toContainText("Solid");
    await expect(tour).toContainText("Dashed");
    await page.keyboard.press("ArrowRight");
    await expect(tour).toContainText("How sure are we?");
    await expect(tour.getByTestId("confidence-badge")).toHaveCount(3);
    await page.keyboard.press("ArrowLeft");
    await expect(tour).toContainText("2 of 5");
    await page.getByTestId("tour-skip").click();
    await expect(tour).toBeHidden();
    await expect(page).not.toHaveURL(/tour=1/);
    expect(errors()).toEqual([]);
  });

  test("runs to the end and mentions sign-in; Escape closes", async ({ page }) => {
    await mockApi(page, graphMocks());
    await page.goto("/atlas");
    await page.getByTestId("tour-start").click();
    const tour = page.getByTestId("atlas-tour");
    for (let i = 0; i < 4; i++) await page.getByTestId("tour-next").click();
    await expect(tour).toContainText("5 of 5");
    await expect(tour).toContainText("Dr. Wu");
    await page.getByTestId("tour-next").click();
    await expect(tour).toBeHidden();
    await page.getByTestId("tour-start").click();
    await expect(tour).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(tour).toBeHidden();
  });

  test("screenshots", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockApi(page, graphMocks());
    for (const theme of ["light", "dark"] as const) {
      await setTheme(page, theme);
      await page.goto("/atlas?tour=1");
      await expect(page.getByTestId("atlas-tour")).toBeVisible();
      await page.waitForTimeout(400);
      await shot(page, `tour-1-${theme}-desktop`);
      await page.getByTestId("tour-next").click();
      await page.waitForTimeout(300);
      await shot(page, `tour-2-${theme}-desktop`);
    }
  });
});

test("tour on a phone @mobile", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockApi(page, graphMocks());
  await page.goto("/atlas?tour=1");
  await expect(page.getByTestId("atlas-tour")).toBeVisible();
  await page.getByTestId("tour-next").click();
  await page.waitForTimeout(300);
  await shot(page, "tour-mobile");
});
