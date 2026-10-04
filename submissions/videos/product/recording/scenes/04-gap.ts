// Scene 4 "The honest gap", first half (guest): a path from PRP to psoriasis 2
// (a cited route via CARD14), then the "Shared research" filter, which finds
// no supported route and shows what it checked; the take ends with the
// cursor on "Run gap search", not clicked (gap search needs sign-in).
// Narration (voiceover/04-gap.mp3): "Amber doesn't guess. No supported
// research route," 0–2.8 s · "and here is what it checked." 3.0–4.3 s ·
// "Then an agent searches PubMed and ClinicalTrials.gov" 4.5–7.9 s · "and
// returns quoted evidence for review." 8.1–10.2 s. The guest flow reaches
// "No supported route" at about 5 s; the signed-in second half (gap search
// running, candidates, submit) still has to be recorded and cut in.

import { url } from "../lib/browser.ts";
import type { SceneTake } from "../lib/scene.ts";

const SLOT = 324;

export const gap: SceneTake = {
  id: "gap",
  frames: SLOT,
  signedIn: false,
  note: 'partial take: the guest half of scene 4 (path, no route, cursor on "Run gap search").',
  run: async ({ page, rec, pointer }) => {
    await rec.cut(async () => {
      await page.goto(url(`/node/${encodeURIComponent("MONDO:0008251")}`));
      await page
        .getByRole("heading", {
          level: 1,
          name: /familial pityriasis rubra pilaris/i,
        })
        .waitFor();
      await page
        .getByTestId("node-graph")
        .locator("canvas")
        .first()
        .waitFor({ timeout: 60_000 });
      await page.waitForTimeout(2500);
      await pointer.jump({ x: 900, y: 300 });
    });

    // Beat 1 · 0–2.5 s: "Find a path to…", "psoriasis 2", choose it.
    await rec.holdUntil(150);
    await pointer.click(page.getByTestId("find-path"), {
      duration: 600,
      dwell: 150,
    });
    const picker = page.getByTestId("path-picker");
    await picker.getByPlaceholder("Search for the end point…").waitFor();
    await rec.hold(200);
    await pointer.type("psoriasis 2", { cps: 14 });
    const option = picker
      .getByRole("option")
      .filter({ hasText: /^psoriasis 2/ })
      .first();
    await rec.cut(async () => {
      await option.waitFor();
    });
    await rec.hold(250);
    await pointer.click(option, {
      duration: 450,
      dwell: 120,
      anchor: { x: 0.2, y: 0.5 },
    });

    // Beat 2 · ~2.5–4.6 s: the cited two-step route via CARD14.
    await rec.cut(async () => {
      await page.waitForURL(/\/path\?from=MONDO%3A0008251&to=MONDO%3A0011269/);
      await page.getByTestId("path-result").waitFor({ timeout: 60_000 });
      await page
        .getByTestId("trust-summary")
        .getByText("Only observed data.")
        .waitFor();
      await page.waitForTimeout(600);
    });
    const routeStart = rec.elapsed();
    const research = page
      .getByTestId("family-filter")
      .getByText("Shared research");
    rec.mark("cited route");
    await rec.holdUntil(routeStart + 800);
    await pointer.moveToLocator(research, { duration: 750 });
    await rec.holdUntil(routeStart + 1750);
    await pointer.click(research, { dwell: 120 });

    // Beat 3 · ~4.7 s to the end: no supported route, sources checked, the
    // question worth asking, and the cursor on "Run gap search".
    await rec.cut(async () => {
      await page.waitForURL(/family=research/);
      await page.getByTestId("no-route-statement").waitFor({ timeout: 60_000 });
      await page.getByTestId("sources-queried").waitFor();
      await page.waitForTimeout(400);
    });
    if (await page.getByText("[object Object]").count()) {
      throw new Error('"[object Object]" is on screen in the no-route report.');
    }
    const noRouteStart = rec.elapsed();
    rec.mark("no supported route");
    await pointer.moveTo({ x: 560, y: 560 }, { duration: 600 });
    await rec.holdUntil(noRouteStart + 1000);
    // Scroll so the "Sources checked" table is in full view.
    const table = page.getByTestId("coverage-report");
    const tableBox = await table.boundingBox();
    if (!tableBox) throw new Error("Coverage report not visible");
    await pointer.wheel(tableBox.y - 70, { duration: 1100 });
    rec.mark("sources checked in view");
    await rec.holdUntil(noRouteStart + 3300);
    // On to the gap search box: question and button in view.
    const button = page.getByTestId("gap-start");
    const buttonBox = await button.boundingBox();
    if (!buttonBox) throw new Error('"Run gap search" not visible');
    await pointer.wheel(buttonBox.y - 600, { duration: 800 });
    await pointer.moveToLocator(button, {
      duration: 700,
      anchor: { x: 0.9, y: 0.6 },
    });
    rec.mark("cursor on Run gap search");
    await rec.holdUntil(SLOT * (1000 / 30) + 150);
  },
};
