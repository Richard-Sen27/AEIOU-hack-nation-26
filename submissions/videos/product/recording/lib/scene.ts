// What a scene script provides, and how one take is run.

import path from "node:path";
import type { Page } from "playwright";
import { SCENES, type SceneId } from "../../src/content.ts";
import { assertGpuWebgl, openSession } from "./browser.ts";
import { PROJECT_DIR } from "./config.ts";
import { Pointer } from "./cursor.ts";
import { Recorder } from "./recorder.ts";

export type TakeContext = {
  readonly page: Page;
  readonly rec: Recorder;
  readonly pointer: Pointer;
};

export type SceneTake = {
  readonly id: SceneId;
  // The scene's slot in src/ProductVideo.tsx; the clip is never shorter.
  readonly frames: number;
  readonly signedIn: boolean;
  // A take that records only part of the scene says so here.
  readonly note?: string;
  // Starts with the recorder paused: load the first page inside `rec.cut`,
  // then play the beats. The clip ends when `run` returns.
  readonly run: (ctx: TakeContext) => Promise<void>;
};

export async function recordTake(take: SceneTake): Promise<string> {
  const scene = SCENES[take.id];
  const outFile = path.join(PROJECT_DIR, "public", scene.recording);
  const { browser, page } = await openSession({ signedIn: take.signedIn });
  try {
    const rec = new Recorder(page, take.id);
    const pointer = new Pointer(page, { x: 720, y: 405 });
    await rec.start();
    await take.run({ page, rec, pointer });
    const renderer = await assertGpuWebgl(page);
    const kept = rec.elapsed();
    const { frames, captured } = await rec.finish(outFile, {
      minFrames: take.frames,
    });
    console.log(
      `${take.id}: ${path.relative(PROJECT_DIR, outFile)} · ${frames} frames (${(frames / 30).toFixed(2)} s, slot ${take.frames}) · kept ${(kept / 1000).toFixed(2)} s · ${captured} distinct captured frames · WebGL ${renderer}`,
    );
    for (const m of rec.marks)
      console.log(`  ${(m.ms / 1000).toFixed(2)} s  ${m.label}`);
    return outFile;
  } finally {
    await browser.close();
  }
}
