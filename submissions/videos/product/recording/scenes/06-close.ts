// Scene 6 "Close": the Atlas, from close in on one tree to all nine trees.
// The video shows this take for its first 5.5 s, then the logo covers it, so
// the zoom-out fills that window and the rest holds the finished map.
// No interaction, so the cursor stays hidden.

import { url } from "../lib/browser.ts";
import {
  cameraPointAt,
  flyCamera,
  getCamera,
  setCamera,
  waitForAtlas,
} from "../lib/atlas.ts";
import type { SceneTake } from "../lib/scene.ts";

export const close: SceneTake = {
  id: "close",
  frames: 250,
  signedIn: false,
  run: async ({ page, rec, pointer }) => {
    let home = { x: 0.5, y: 0.5, ratio: 1 };
    let start = home;
    await rec.cut(async () => {
      await page.goto(url("/atlas"));
      await waitForAtlas(page);
      await pointer.hide();
      // Let the first layout and label placement finish.
      await page.waitForTimeout(1500);
      home = await getCamera(page);
      // Start over the Symptoms tree (upper left of the map), close in.
      const box = await page.getByTestId("atlas-canvas").boundingBox();
      if (!box) throw new Error("Atlas canvas not visible");
      const spot = await cameraPointAt(page, {
        x: box.width * 0.37,
        y: box.height * 0.3,
      });
      start = { x: spot.x, y: spot.y, ratio: home.ratio * 0.12 };
      await setCamera(page, start);
      // Labels and the level of detail catch up with the new camera.
      await page.waitForTimeout(1200);
    });
    await rec.holdUntil(200);
    rec.mark("zoom-out starts");
    await flyCamera(page, start, home, 5200);
    rec.mark("all nine trees, still");
    await rec.holdUntil(250 * (1000 / 30) + 150);
  },
};
