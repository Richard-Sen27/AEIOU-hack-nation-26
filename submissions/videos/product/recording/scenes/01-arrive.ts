// Scene 1 "Alex arrives", guest version: the landing page, the hero input,
// "pityriasis rubra pilaris", Enter, and the PRP node page.
// Narration: "Meet Alex. Diagnosis: pityriasis rubra pilaris, a skin disease
// found in a few people per million. What's known is scattered."

import { url } from "../lib/browser.ts";
import type { SceneTake } from "../lib/scene.ts";

const SLOT = 252;

export const arrive: SceneTake = {
  id: "arrive",
  frames: SLOT,
  signedIn: false,
  note: "guest version: landing search instead of sign-in.",
  run: async ({ page, rec, pointer }) => {
    const input = page.getByRole("textbox", { name: /Describe the diagnosis/ });
    await rec.cut(async () => {
      await page.goto(url("/"));
      await page
        .getByText("Rare diseases, connected by what they share.")
        .first()
        .waitFor();
      await input.waitFor();
      await page.waitForTimeout(1500);
      await pointer.jump({ x: 1040, y: 640 });
    });
    rec.mark("landing");
    await rec.holdUntil(1300);
    await pointer.click(input, { duration: 700, anchor: { x: 0.3, y: 0.5 } });
    rec.mark("typing");
    await rec.hold(200);
    await pointer.type("pityriasis rubra pilaris", { cps: 14 });
    await rec.hold(400);
    await page.keyboard.press("Enter");
    await rec.cut(async () => {
      await page.waitForURL(/\/node\/MONDO%3A0008251/);
      await page
        .getByRole("heading", {
          level: 1,
          name: /familial pityriasis rubra pilaris/i,
        })
        .waitFor();
      await page
        .getByText(/A rare chronic papulosquamous disorder/)
        .first()
        .waitFor();
      await page
        .getByTestId("node-graph")
        .locator("canvas")
        .first()
        .waitFor({ timeout: 60_000 });
      await page.waitForTimeout(2500);
    });
    rec.mark("PRP node page");
    // Off the title, beside the description.
    await pointer.moveTo({ x: 880, y: 300 }, { duration: 900 });
    await rec.holdUntil(SLOT * (1000 / 30) + 200);
  },
};
