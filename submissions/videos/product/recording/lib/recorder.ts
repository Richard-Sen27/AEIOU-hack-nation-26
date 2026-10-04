// Captures a take with the Chrome DevTools screencast and cuts out the waits.
//
// The screencast runs for the whole take and every frame keeps its timestamp.
// The take is made of "kept" segments of wall-clock time: `cut()` pauses the
// keep around page loads and network or model waits, so they never reach the
// clip. `finish()` resamples the kept time at a constant 30 fps (each output
// frame shows the newest captured frame at that moment) and encodes H.264.

import { spawn } from "node:child_process";
import { mkdirSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import path from "node:path";
import type { CDPSession, Page } from "playwright";
import { FFMPEG, FPS, KEEP_FRAMES, OUTPUT, WORK_DIR } from "./config.ts";

type Frame = { readonly t: number; readonly file: string };
type Segment = { start: number; end: number | null };

const sleep = (ms: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, Math.max(0, ms)));

// Waits until the page has painted what it shows now (two animation frames)
// plus a short margin for the screencast to deliver that frame.
export async function painted(page: Page, extraMs = 150): Promise<void> {
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  );
  await sleep(extraMs);
}

export class Recorder {
  readonly page: Page;
  readonly name: string;
  private readonly dir: string;
  private cdp: CDPSession | null = null;
  private readonly frames: Frame[] = [];
  private readonly segments: Segment[] = [];
  private pending: Promise<unknown>[] = [];
  readonly marks: { label: string; ms: number }[] = [];

  constructor(page: Page, name: string) {
    this.page = page;
    this.name = name;
    this.dir = path.join(WORK_DIR, name);
  }

  // Starts capturing (nothing is kept until `resume()`).
  async start(): Promise<void> {
    rmSync(this.dir, { recursive: true, force: true });
    mkdirSync(path.join(this.dir, "raw"), { recursive: true });
    const cdp = await this.page.context().newCDPSession(this.page);
    this.cdp = cdp;
    cdp.on("Page.screencastFrame", (event) => {
      const t = (event.metadata.timestamp ?? Date.now() / 1000) * 1000;
      const file = path.join(
        this.dir,
        "raw",
        `${String(this.frames.length).padStart(6, "0")}.png`,
      );
      writeFileSync(file, Buffer.from(event.data, "base64"));
      this.frames.push({ t, file });
      this.pending.push(
        cdp
          .send("Page.screencastFrameAck", { sessionId: event.sessionId })
          .catch(() => {}),
      );
    });
    await cdp.send("Page.startScreencast", {
      format: "png",
      maxWidth: OUTPUT.width,
      maxHeight: OUTPUT.height,
      everyNthFrame: 1,
    });
  }

  resume(): void {
    const last = this.segments[this.segments.length - 1];
    if (last && last.end === null) return;
    this.segments.push({ start: Date.now(), end: null });
  }

  pause(): void {
    const last = this.segments[this.segments.length - 1];
    if (last && last.end === null) last.end = Date.now();
  }

  // Runs `wait` with the recorder paused, so whatever it waits for is cut.
  // When it returns, the new state is on screen before keeping resumes.
  async cut(
    wait: () => Promise<unknown>,
    { settleMs = 150 }: { settleMs?: number } = {},
  ): Promise<void> {
    this.pause();
    await wait();
    await painted(this.page, settleMs);
    this.resume();
  }

  // Kept time so far, in ms.
  elapsed(): number {
    const now = Date.now();
    return this.segments.reduce(
      (sum, s) => sum + ((s.end ?? now) - s.start),
      0,
    );
  }

  // Notes where a beat lands in the clip (printed after the take).
  mark(label: string): void {
    this.marks.push({ label, ms: this.elapsed() });
  }

  async hold(ms: number): Promise<void> {
    await sleep(ms);
  }

  // Waits until the kept time reaches `ms` (a beat's place in the clip).
  async holdUntil(ms: number): Promise<void> {
    await sleep(ms - this.elapsed());
  }

  // Stops capturing and writes the clip: at least `minFrames` frames at 30 fps.
  async finish(
    outFile: string,
    { minFrames }: { minFrames: number },
  ): Promise<{ frames: number; captured: number }> {
    this.pause();
    if (this.cdp) {
      await this.cdp.send("Page.stopScreencast").catch(() => {});
      await Promise.all(this.pending);
      this.pending = [];
      await this.cdp.detach().catch(() => {});
      this.cdp = null;
    }
    if (this.frames.length === 0)
      throw new Error(`${this.name}: no frames were captured.`);
    const frames = [...this.frames].sort((a, b) => a.t - b.t);
    const keptMs = this.elapsed();
    const count = Math.max(minFrames, Math.ceil((keptMs / 1000) * FPS));

    // Output frame k shows the newest captured frame at its moment of kept time.
    const seqDir = path.join(this.dir, "seq");
    rmSync(seqDir, { recursive: true, force: true });
    mkdirSync(seqDir, { recursive: true });
    const used = new Set<number>();
    let cursor = 0;
    for (let k = 0; k < count; k++) {
      const wall = this.wallTimeAt((k / FPS) * 1000);
      while (cursor + 1 < frames.length && frames[cursor + 1].t <= wall)
        cursor++;
      symlinkSync(
        frames[cursor].file,
        path.join(seqDir, `${String(k).padStart(5, "0")}.png`),
      );
      used.add(cursor);
    }
    // How many different captured frames made it in (a still page sends none).
    const captured = used.size;

    mkdirSync(path.dirname(outFile), { recursive: true });
    await run(FFMPEG, [
      "-y",
      "-hide_banner",
      "-loglevel",
      "error",
      "-framerate",
      String(FPS),
      "-i",
      path.join(seqDir, "%05d.png"),
      "-vf",
      `scale=${OUTPUT.width}:${OUTPUT.height}:flags=lanczos,format=yuv420p`,
      "-c:v",
      "libx264",
      "-preset",
      "slow",
      "-crf",
      "15",
      "-tune",
      "film",
      "-r",
      String(FPS),
      "-an",
      "-movflags",
      "+faststart",
      outFile,
    ]);
    if (KEEP_FRAMES) {
      writeFileSync(
        path.join(this.dir, "timeline.json"),
        JSON.stringify({
          segments: this.segments,
          frames: frames.map((f) => ({ t: f.t, file: path.basename(f.file) })),
        }),
      );
    } else {
      rmSync(this.dir, { recursive: true, force: true });
    }
    return { frames: count, captured };
  }

  // Maps kept time (ms from the start of the clip) to wall-clock time.
  private wallTimeAt(keptMs: number): number {
    let left = keptMs;
    for (const s of this.segments) {
      const length = (s.end ?? Date.now()) - s.start;
      if (left <= length) return s.start + left;
      left -= length;
    }
    const last = this.segments[this.segments.length - 1];
    return last ? (last.end ?? Date.now()) : Date.now();
  }
}

function run(cmd: string, args: string[]): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { stdio: ["ignore", "inherit", "inherit"] });
    child.on("error", reject);
    child.on("exit", (code) =>
      code === 0 ? resolve() : reject(new Error(`${cmd} exited with ${code}`)),
    );
  });
}
