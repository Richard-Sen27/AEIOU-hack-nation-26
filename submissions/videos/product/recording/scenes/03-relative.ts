// Scene 3, guest version (replaces the Dr. Wu take): on the PRP node page,
// the computed link to "psoriasis 2" and its explanation.
// Narration: "The graph surfaces a relative under another name: a psoriasis
// caused by the same gene. Shared mechanism? Not established."

import { url } from "../lib/browser.ts";
import type { SceneTake } from "../lib/scene.ts";

const SLOT = 270;

export const relative: SceneTake = {
  id: "relative",
  recording: "recordings/03-relative.mp4",
  frames: SLOT,
  signedIn: false,
  run: async ({ page, rec, pointer }) => {
    const panel = page.getByTestId("node-panel");
    const sources = panel
      .getByRole("button", { name: /^Sources for psoriasis 2/ })
      .first();
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
      await sources.waitFor({ state: "attached" });
      await page.waitForTimeout(2500);
      await pointer.jump({ x: 860, y: 420 });
    });
    // The side panel (an <aside>) scrolls.
    const aside = panel.locator("xpath=ancestor::aside[1]");
    const asideBox = await aside.boundingBox();
    if (!asideBox) throw new Error("Side panel not visible");
    await rec.holdUntil(500);
    await pointer.moveTo(
      {
        x: asideBox.x + asideBox.width * 0.5,
        y: asideBox.y + asideBox.height * 0.6,
      },
      { duration: 700 },
    );
    // Bring the psoriasis 2 row to the middle of the panel.
    const row = sources.locator("xpath=..");
    const rowBox = await row.boundingBox();
    if (!rowBox) throw new Error("psoriasis 2 row not found");
    await pointer.wheel(rowBox.y - (asideBox.y + asideBox.height * 0.4), {
      duration: 1100,
    });
    rec.mark("psoriasis 2 row in view");
    await rec.hold(700);
    await pointer.click(sources, { duration: 700, dwell: 220 });
    const edge = page.getByTestId("edge-panel");
    await rec.cut(async () => {
      await edge
        .getByText(/whether they share a mechanism is not established/)
        .waitFor();
    });
    if (await page.getByText("[object Object]").count()) {
      throw new Error('"[object Object]" is on screen in the edge panel.');
    }
    rec.mark("explanation on screen");
    // Rest beside the badges, clear of the explanation.
    const edgeBox = await edge.boundingBox();
    if (!edgeBox) throw new Error("Edge panel not visible");
    await pointer.moveTo(
      { x: edgeBox.x + edgeBox.width * 0.85, y: edgeBox.y + 175 },
      { duration: 800 },
    );
    await rec.holdUntil(SLOT * (1000 / 30) + 200);
  },
};
