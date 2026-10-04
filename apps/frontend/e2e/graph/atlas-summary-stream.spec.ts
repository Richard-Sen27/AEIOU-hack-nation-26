import { expect as baseExpect, test, type Page } from "@playwright/test";

import { guestSession, mockApi, setTheme, signedInSession } from "../helpers";
import { atlasTreePayload, summaryMock } from "./fixtures";

/**
 * "Write a summary" streamed: a delayed, chunked POST /explain (a fetch
 * override, since route.fulfill cannot stream) checks that the indicator shows
 * at once, steps change in place, the checked text grows over time, errors
 * offer a retry, cancel stops the request and reduced motion shows text at once.
 */

type Event = { type: string } & Record<string, unknown>;
/** A frame waits `ms`, or with "gate" until the test calls `release(page)`. */
type Frame = [number | "gate", Event];
type Script = { status?: number; code?: string; frames?: Frame[] };

const TEXT =
  "STXBP1 encephalopathy is caused by changes in the STXBP1 gene [e_e5f778ac8a21]. " +
  "It is grouped with similar conditions that share a mechanism, and some links are still hypotheses " +
  "that researchers are checking [e_3b8845b635b8]. The atlas lists the genes, symptoms and people " +
  "connected to it, strongest links first [e_e5f778ac8a21].";

const final = (text: string, cached: boolean): Event => ({
  type: "final",
  path_id: "p_fixture",
  text,
  citations: ["e_e5f778ac8a21", "e_3b8845b635b8"],
  cached,
  role: "patient",
  language: "en",
  data_version: "fixture",
});

/**
 * Steps live, then the checked text in small deltas, then the final event. With
 * `gated` each step and the first delta wait for `release(page)`.
 */
function fresh(text = TEXT, { gated = false, stepMs = 200, deltaMs = 20 } = {}): Script {
  const wait = gated ? ("gate" as const) : stepMs;
  const words = text.match(/\S+\s*/g)!;
  const deltas: Frame[] = [];
  for (let i = 0; i < words.length; i += 6) {
    deltas.push([i === 0 ? wait : deltaMs, { type: "delta", text: words.slice(i, i + 6).join("") }]);
  }
  return {
    frames: [
      [wait, { type: "status", step: "reading", message: "Reading 2 links" }],
      [wait, { type: "status", step: "writing", message: "Writing" }],
      [wait, { type: "status", step: "checking", message: "Checking the sources" }],
      ...deltas,
      [deltaMs, final(text, false)],
    ],
  };
}

/** Let the next gated frame through. */
async function release(page: Page) {
  await page.waitForFunction(() => (window as unknown as { __explain: { waiting: boolean } }).__explain.waiting);
  await page.evaluate(() => (window as unknown as { __explain: { release: () => void } }).__explain.release());
}

async function streamExplain(page: Page, scripts: Script[]) {
  await page.addInitScript((scripts: Script[]) => {
    const w = window as unknown as {
      __explain: { calls: unknown[]; aborted: number; waiting: boolean; release: () => void };
    };
    let open: (() => void) | null = null;
    w.__explain = {
      calls: [],
      aborted: 0,
      waiting: false,
      release: () => {
        w.__explain.waiting = false;
        open?.();
      },
    };
    const gate = () =>
      new Promise<void>((resolve) => {
        open = resolve;
        w.__explain.waiting = true;
      });
    const original = window.fetch.bind(window);
    window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (new URL(url, location.href).pathname !== "/explain") return original(input, init);
      const n = w.__explain.calls.length;
      w.__explain.calls.push(JSON.parse(String(init?.body ?? "null")));
      const s = scripts[Math.min(n, scripts.length - 1)];
      if (s.status) {
        return new Response(JSON.stringify({ error: { code: s.code, message: s.code } }), {
          status: s.status,
          headers: { "content-type": "application/json" },
        });
      }
      const signal = init?.signal;
      signal?.addEventListener("abort", () => w.__explain.aborted++, { once: true });
      const enc = new TextEncoder();
      const body = new ReadableStream<Uint8Array>({
        async start(ctrl) {
          for (const [delay, ev] of s.frames ?? []) {
            await (delay === "gate" ? gate() : new Promise((r) => setTimeout(r, delay)));
            if (signal?.aborted) return;
            try {
              ctrl.enqueue(enc.encode(`event: ${ev.type}\ndata: ${JSON.stringify(ev)}\n\n`));
            } catch {
              return;
            }
          }
          try {
            ctrl.close();
          } catch {
            /* cancelled */
          }
        },
      });
      return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
    };
  }, scripts);
}

async function atlas(page: Page, scripts: Script[], session: unknown = signedInSession({ consents: ["health_data"] })) {
  await mockApi(page, {
    "GET /auth/session": session,
    "GET /atlas/tree.json": atlasTreePayload(),
    "GET /atlas/summary/*": summaryMock(),
    "GET /chat/sessions": [],
  });
  await streamExplain(page, scripts);
  await page.goto("/atlas?focus=MONDO:9900007");
}

const panel = (page: Page) => page.getByTestId("atlas-panel");
const calls = (page: Page) => page.evaluate(() => (window as unknown as { __explain: { calls: unknown[] } }).__explain.calls);
/** Start collecting each distinct length of the summary text as the page renders it. */
async function recordTextLengths(page: Page) {
  await page.evaluate(() => {
    const w = window as unknown as { __lengths: number[] };
    w.__lengths = [];
    new MutationObserver(() => {
      const n = document.querySelector('[data-testid="atlas-summary-text"]')?.textContent?.length;
      if (n !== undefined && n !== w.__lengths[w.__lengths.length - 1]) w.__lengths.push(n);
    }).observe(document.body, { subtree: true, childList: true, characterData: true });
  });
}
const textLengths = (page: Page) => page.evaluate(() => (window as unknown as { __lengths: number[] }).__lengths);
// The machine may be busy; gates, not timings, decide what the page shows.
test.describe.configure({ timeout: 120_000 });
const expect = baseExpect.configure({ timeout: 30_000 });
const SHOTS = process.env.SHOT_DIR;

test.describe("atlas write a summary, streamed", () => {
  test("indicator at once, steps in place, text grows, one request", async ({ page }) => {
    await atlas(page, [fresh(TEXT, { gated: true })]);
    const p = panel(page);
    const write = p.getByTestId("atlas-summary-write");
    await write.dblclick(); // a double click still sends one request
    const box = p.getByTestId("atlas-summary-written");
    // Nothing has come from the server yet (the first frame is held): this is the click's own state.
    await expect(box).toHaveAttribute("data-state", "writing");
    await expect(box).toHaveAttribute("aria-busy", "true");
    await expect(p.getByTestId("atlas-summary-status")).toContainText("Dr. Wu is writing");
    await expect(p.getByTestId("atlas-summary-step")).toHaveText("Starting");
    await expect(write).toHaveCount(0);
    await expect(p.getByTestId("atlas-summary-cancel")).toBeVisible();
    await expect(box.getByText("AI-generated · Dr. Wu")).toBeVisible();
    await expect(p.getByTestId("atlas-summary-placeholder")).toBeVisible();
    const before = (await box.boundingBox())!.height;
    if (SHOTS) await p.screenshot({ path: `${SHOTS}/summary-stream-1-loading.png` });

    for (const step of ["Reading 2 links", "Writing", "Checking the sources"]) {
      await release(page);
      await expect(p.getByTestId("atlas-summary-step")).toHaveText(step);
      await expect(p.getByTestId("atlas-summary-text")).toHaveCount(0); // no text before the checks
      await expect(p.getByTestId("atlas-summary-placeholder")).toBeVisible();
    }
    if (SHOTS) await p.screenshot({ path: `${SHOTS}/summary-stream-2-checking.png` });

    // Then the checked text grows over time: record every length it shows.
    await recordTextLengths(page);
    await release(page);
    await expect(p.getByTestId("atlas-summary-step")).toHaveText("Sources checked");
    if (SHOTS) await p.screenshot({ path: `${SHOTS}/summary-stream-3-midstream.png` });

    await expect(p.getByTestId("atlas-summary-fresh")).toBeVisible();
    const lengths = await textLengths(page);
    expect(lengths.length).toBeGreaterThanOrEqual(5);
    expect(lengths).toEqual([...lengths].sort((a, b) => a - b));
    await expect(box).toHaveAttribute("data-state", "done");
    await expect(p.getByTestId("atlas-summary-cancel")).toHaveCount(0);
    await expect(p.getByTestId("citation")).toHaveCount(3);
    const after = (await box.boundingBox())!.height;
    expect(after).toBeGreaterThanOrEqual(before); // reserved space: it never shrinks back
    if (SHOTS) await p.screenshot({ path: `${SHOTS}/summary-stream-4-done.png` });

    const sent = await calls(page);
    expect(sent).toHaveLength(1);
    expect(sent[0]).toMatchObject({ subject_node_id: "MONDO:9900007", steps: true });
  });

  test("a short text does not make the block jump", async ({ page }) => {
    await atlas(page, [fresh("Short text [e_e5f778ac8a21].", { gated: true })]);
    const p = panel(page);
    await p.getByTestId("atlas-summary-write").click();
    const box = p.getByTestId("atlas-summary-written");
    await expect(p.getByTestId("atlas-summary-placeholder")).toBeVisible();
    const before = (await box.boundingBox())!.height;
    for (let i = 0; i < 4; i++) await release(page);
    await expect(p.getByTestId("atlas-summary-fresh")).toBeVisible();
    const after = (await box.boundingBox())!.height;
    expect(Math.abs(after - before)).toBeLessThanOrEqual(1);
  });

  test("an error event after steps shows the short line and a retry", async ({ page }) => {
    await atlas(page, [
      {
        frames: [
          [200, { type: "status", step: "reading", message: "Reading 2 links" }],
          [200, { type: "status", step: "writing", message: "Writing" }],
          [200, { type: "error", code: "upstream_error", message: "Dr. Wu took too long to answer. Please try again." }],
        ],
      },
      fresh(TEXT, { stepMs: 100 }),
    ]);
    const p = panel(page);
    await p.getByTestId("atlas-summary-write").click();
    const alert = p.getByTestId("atlas-summary-write-error");
    await expect(alert).toContainText("Dr. Wu took too long to answer.");
    await expect(p.getByTestId("atlas-summary-text")).toHaveCount(0);
    if (SHOTS) await p.screenshot({ path: `${SHOTS}/summary-stream-5-error.png` });
    await alert.getByRole("button", { name: "Retry" }).click();
    await expect(p.getByTestId("atlas-summary-written")).toHaveAttribute("data-state", "writing");
    await expect(p.getByTestId("atlas-summary-fresh")).toBeVisible();
    expect(await calls(page)).toHaveLength(2);
  });

  for (const [status, code, message] of [
    [429, "rate_limited", "Usage limit reached."],
    [403, "age_confirmation_required", "Confirm your age first."],
  ] as const) {
    test(`HTTP ${status} ${code} shows "${message}"`, async ({ page }) => {
      await atlas(page, [{ status, code }]);
      await panel(page).getByTestId("atlas-summary-write").click();
      const alert = panel(page).getByTestId("atlas-summary-write-error");
      await expect(alert).toContainText(message);
      await expect(alert.getByRole("button", { name: "Retry" })).toBeVisible();
    });
  }

  test("not signed in asks to sign in in the same place", async ({ page }) => {
    await atlas(page, [{ status: 401, code: "sign_in_required" }], guestSession);
    await panel(page).getByTestId("atlas-summary-write").click();
    await expect(panel(page).getByTestId("atlas-summary-sign-in")).toBeVisible();
  });

  test("cancel stops the request and brings the button back", async ({ page }) => {
    await atlas(page, [fresh(TEXT, { gated: true })]);
    const p = panel(page);
    await p.getByTestId("atlas-summary-write").click();
    await release(page);
    await expect(p.getByTestId("atlas-summary-step")).toHaveText("Reading 2 links");
    await p.getByTestId("atlas-summary-cancel").click();
    await expect(p.getByTestId("atlas-summary-write")).toBeVisible();
    await expect(p.getByTestId("atlas-summary-written")).toHaveCount(0);
    expect(await page.evaluate(() => (window as unknown as { __explain: { aborted: number } }).__explain.aborted)).toBe(1);
    await release(page); // the rest of the stream never lands
    await expect(p.getByTestId("atlas-summary-written")).toHaveCount(0);
    expect(await calls(page)).toHaveLength(1);
  });

  test("reduced motion: still dots and the checked text at once", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    // One delta holding the whole text; the final event is held back.
    await atlas(page, [
      {
        frames: [
          ["gate", { type: "status", step: "reading", message: "Reading 2 links" }],
          ["gate", { type: "delta", text: TEXT }],
          ["gate", final(TEXT, false)],
        ],
      },
    ]);
    const p = panel(page);
    await p.getByTestId("atlas-summary-write").click();
    const dot = p.locator('[data-testid="atlas-summary-status"] span[aria-hidden] span').first();
    expect(await dot.evaluate((el) => getComputedStyle(el).animationName)).toBe("none");
    await release(page);
    await recordTextLengths(page);
    await release(page);
    await expect(p.getByTestId("atlas-summary-text")).toContainText("strongest links first");
    await expect(p.getByTestId("atlas-summary-fresh")).toHaveCount(0); // still before the final event
    const full = ((await p.getByTestId("atlas-summary-text").textContent()) ?? "").length;
    expect((await textLengths(page))[0]).toBe(full); // the first render already held all of it
    await release(page);
    await expect(p.getByTestId("atlas-summary-fresh")).toBeVisible();
  });

  test("a cached summary uses the same reveal", async ({ page }) => {
    await atlas(page, [{ frames: [[50, { type: "delta", text: TEXT }], ["gate", final(TEXT, true)]] }], guestSession);
    const p = panel(page);
    await p.getByTestId("atlas-summary-write").click();
    await expect(p.getByTestId("atlas-summary-step")).toHaveText("Prepared summary");
    await release(page);
    await expect(p.getByTestId("atlas-summary-cached")).toBeVisible();
    await expect(p.getByTestId("atlas-summary-text")).toContainText("strongest links first");
  });

  for (const theme of ["light", "dark"] as const) {
    test(`screenshot writing ${theme}`, async ({ page }) => {
      test.skip(!SHOTS, "SHOT_DIR not set");
      await setTheme(page, theme);
      await atlas(page, [fresh(TEXT, { gated: true, deltaMs: 300 })]);
      const p = panel(page);
      await p.getByTestId("atlas-summary-write").click();
      await release(page);
      await release(page);
      await expect(p.getByTestId("atlas-summary-step")).toHaveText("Writing");
      await p.screenshot({ path: `${SHOTS}/summary-stream-${theme}-writing.png` });
      await release(page);
      await release(page);
      await expect(p.getByTestId("atlas-summary-text")).toContainText("STXBP1 gene");
      await p.screenshot({ path: `${SHOTS}/summary-stream-${theme}-midstream.png` });
    });
  }

  test("phone bottom sheet while writing @mobile", async ({ page }) => {
    await atlas(page, [fresh(TEXT, { gated: true, deltaMs: 300 })]);
    const p = panel(page);
    const write = p.getByTestId("atlas-summary-write");
    await write.scrollIntoViewIfNeeded();
    await write.click();
    await release(page);
    await release(page);
    await expect(p.getByTestId("atlas-summary-step")).toHaveText("Writing");
    await p.getByTestId("atlas-summary-written").scrollIntoViewIfNeeded();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/summary-stream-mobile-writing.png` });
    await release(page);
    await release(page);
    await expect(p.getByTestId("atlas-summary-text")).toContainText("STXBP1 gene");
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/summary-stream-mobile-midstream.png` });
    await expect(p.getByTestId("atlas-summary-fresh")).toBeVisible();
    const sheet = (await p.boundingBox())!;
    expect(sheet.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  });
});
