// A drawn mouse cursor (headless Chromium paints none) and a pointer that
// moves it like a person: eased curved paths, a short dwell before a click,
// a small press ring, typing at a human pace and smooth wheel scrolling.

import type { Locator, Page } from "playwright";

// Runs in every document before the app's own scripts. The cursor follows the
// real mouse events Playwright dispatches, so hover states match what is drawn.
export function CURSOR_INIT_SCRIPT() {
  const w = window as unknown as {
    __recCursor?: { hide: () => void; show: () => void };
  };
  if (w.__recCursor) return;
  const arrow =
    '<svg xmlns="http://www.w3.org/2000/svg" width="22" height="30" viewBox="0 0 22 30">' +
    '<path d="M2 2 L2 23.5 L7.4 18.6 L11 27 L14.6 25.4 L11.1 17.3 L18.4 17.3 Z" ' +
    'fill="#111" stroke="#fff" stroke-width="1.8" stroke-linejoin="round"/></svg>';
  let el: HTMLDivElement | null = null;
  let hidden = false;
  let x = -100;
  let y = -100;
  const mount = () => {
    if (el || !document.documentElement) return;
    el = document.createElement("div");
    el.setAttribute("aria-hidden", "true");
    el.setAttribute("data-recording-cursor", "");
    el.innerHTML = arrow;
    el.style.cssText =
      "position:fixed;left:0;top:0;width:22px;height:30px;z-index:2147483647;" +
      "pointer-events:none;transform-origin:2px 2px;will-change:transform;" +
      "filter:drop-shadow(0 1px 1.5px rgba(0,0,0,.35));transition:scale 90ms ease-out;";
    // Outside <body>, so React never sees (or removes) it.
    document.documentElement.appendChild(el);
    place();
  };
  const place = () => {
    if (!el) return;
    el.style.transform = `translate(${x - 2}px, ${y - 2}px)`;
    el.style.display = hidden || x < 0 ? "none" : "block";
  };
  const ring = (cx: number, cy: number) => {
    if (hidden || !document.documentElement) return;
    const r = document.createElement("div");
    r.setAttribute("aria-hidden", "true");
    r.style.cssText =
      `position:fixed;left:${cx - 16}px;top:${cy - 16}px;width:32px;height:32px;border-radius:50%;` +
      "z-index:2147483646;pointer-events:none;border:2px solid rgba(17,17,17,.55);" +
      "background:rgba(245,158,11,.18);";
    document.documentElement.appendChild(r);
    r.animate(
      [
        { transform: "scale(.35)", opacity: 1 },
        { transform: "scale(1)", opacity: 0 },
      ],
      { duration: 420, easing: "cubic-bezier(.2,.7,.3,1)" },
    ).onfinish = () => r.remove();
  };
  window.addEventListener(
    "mousemove",
    (e) => {
      x = e.clientX;
      y = e.clientY;
      mount();
      place();
    },
    true,
  );
  window.addEventListener(
    "mousedown",
    (e) => {
      if (el) el.style.scale = "0.86";
      ring(e.clientX, e.clientY);
    },
    true,
  );
  window.addEventListener(
    "mouseup",
    () => {
      if (el) el.style.scale = "1";
    },
    true,
  );
  w.__recCursor = {
    hide: () => {
      hidden = true;
      place();
    },
    show: () => {
      hidden = false;
      place();
    },
  };
  if (document.documentElement) mount();
  else document.addEventListener("DOMContentLoaded", mount);
}

type Point = { x: number; y: number };

const sleep = (ms: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, Math.max(0, ms)));

// Minimum-jerk profile: how a hand accelerates and settles.
const minimumJerk = (t: number) => t * t * t * (10 - 15 * t + 6 * t * t);

// Small deterministic jitter, so retakes look the same.
function makeRandom(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 2 ** 32;
  };
}

export class Pointer {
  readonly page: Page;
  pos: Point;
  private readonly random: () => number;
  private bend = 1;

  constructor(page: Page, start: Point, seed = 7) {
    this.page = page;
    this.pos = start;
    this.random = makeRandom(seed);
  }

  // Puts the cursor back after a navigation (a new document draws none until
  // the next mouse event).
  async restore(): Promise<void> {
    await this.page.mouse.move(this.pos.x, this.pos.y);
  }

  async hide(): Promise<void> {
    await this.page.evaluate(() =>
      (
        window as unknown as { __recCursor?: { hide: () => void } }
      ).__recCursor?.hide(),
    );
  }

  // Jumps without a visible move (use only while the recorder is paused).
  async jump(to: Point): Promise<void> {
    this.pos = to;
    await this.page.mouse.move(to.x, to.y);
  }

  async moveTo(
    to: Point,
    { duration }: { duration?: number } = {},
  ): Promise<void> {
    const from = this.pos;
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const distance = Math.hypot(dx, dy);
    if (distance < 1) return;
    const ms = duration ?? Math.min(1100, 320 + distance * 0.55);
    // A gentle arc: the control point sits off the straight line, alternating sides.
    this.bend = -this.bend;
    const offset = Math.min(60, distance * 0.12) * this.bend;
    const control = {
      x: (from.x + to.x) / 2 - (dy / distance) * offset,
      y: (from.y + to.y) / 2 + (dx / distance) * offset,
    };
    const start = Date.now();
    for (;;) {
      const t = Math.min(1, (Date.now() - start) / ms);
      const s = minimumJerk(t);
      const x =
        (1 - s) * (1 - s) * from.x + 2 * (1 - s) * s * control.x + s * s * to.x;
      const y =
        (1 - s) * (1 - s) * from.y + 2 * (1 - s) * s * control.y + s * s * to.y;
      await this.page.mouse.move(x, y);
      if (t >= 1) break;
      await sleep(14);
    }
    this.pos = to;
  }

  // A point inside the element: its centre, or a fraction of its box.
  async pointOf(
    locator: Locator,
    anchor: Point = { x: 0.5, y: 0.5 },
  ): Promise<Point> {
    const box = await locator.boundingBox();
    if (!box) throw new Error(`Not visible: ${locator.toString()}`);
    return {
      x: box.x + box.width * anchor.x,
      y: box.y + box.height * anchor.y,
    };
  }

  async moveToLocator(
    locator: Locator,
    { duration, anchor }: { duration?: number; anchor?: Point } = {},
  ): Promise<void> {
    await this.moveTo(await this.pointOf(locator, anchor), { duration });
  }

  async click(
    target: Locator | Point,
    {
      duration,
      anchor,
      dwell = 170,
    }: { duration?: number; anchor?: Point; dwell?: number } = {},
  ): Promise<void> {
    const point = "x" in target ? target : await this.pointOf(target, anchor);
    await this.moveTo(point, { duration });
    await sleep(dwell);
    await this.page.mouse.down();
    await sleep(85);
    await this.page.mouse.up();
  }

  // Types into whatever has focus, at roughly `cps` characters per second.
  async type(text: string, { cps = 11 }: { cps?: number } = {}): Promise<void> {
    for (const ch of text) {
      await this.page.keyboard.type(ch);
      const base = 1000 / cps;
      await sleep(base * (0.65 + this.random() * 0.7) + (ch === " " ? 40 : 0));
    }
  }

  // Scrolls the element under the cursor by `dy` CSS pixels, eased, in many
  // small wheel steps so it reads as one smooth scroll.
  async wheel(
    dy: number,
    { duration = 900 }: { duration?: number } = {},
  ): Promise<void> {
    const start = Date.now();
    let done = 0;
    for (;;) {
      const t = Math.min(1, (Date.now() - start) / duration);
      const target = dy * minimumJerk(t);
      const step = Math.round(target - done);
      if (step !== 0) {
        await this.page.mouse.wheel(0, step);
        done += step;
      }
      if (t >= 1) break;
      await sleep(14);
    }
  }
}
