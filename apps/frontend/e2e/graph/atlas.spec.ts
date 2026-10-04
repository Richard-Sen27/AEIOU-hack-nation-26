import { expect, test, type Page } from "@playwright/test";

import { errorEnvelope, mockApi, setTheme, shot, signedInSession, trackConsoleErrors } from "../helpers";
import { atlasTreePayload, graphMocks, largeAtlasTree } from "./fixtures";

/**
 * The Atlas view as a whole. Search, outline, panel, Dr. Wu dock and tour
 * have their own specs; this one covers the map, its states and its layout.
 *
 * The map is WebGL, so what is drawn is read from screenshots: the logo
 * button sits on the hub (graph 0,0) and each category label is centred on
 * its `label_x/label_y`, which gives the graph-to-screen mapping; real
 * connections are then checked by sampling pixels along the line between
 * two dots.
 */

const tree = atlasTreePayload();
const nodeById = new Map(tree.nodes.map((n) => [n.id, n]));
const CATEGORY_TEXT: Record<string, string[]> = {
  researchers: ["Researchers"],
  institutions: ["Hospitals & universities", "Hospitals"],
  literature: ["Articles, studies & funding", "Articles"],
  community: ["Patient groups & registries", "Patient groups"],
  pathways: ["Body processes", "Processes"],
  genes: ["Genes & gene changes", "Genes"],
  diseases: ["Conditions"],
  symptoms: ["Symptoms"],
  doctors: ["Doctors"],
};

// Dravet syndrome (Conditions) is linked to Seizure (Symptoms, a "symptoms" connection)
// and to SCN1A (Genes, a "dna" connection): two lines through open space on the left.
const DRAVET = "MONDO:0100135";
const SEIZURE = "HP:0001250";
const SCN1A = "HGNC:10585";

type Point = { x: number; y: number };

/** Wait until the map has drawn its overlays (logo and the nine category names). */
async function mapReady(page: Page) {
  await expect(page.getByTestId("atlas-canvas").locator("canvas").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("atlas-logo")).toBeVisible();
  await expect(page.getByTestId("atlas-category-label")).toHaveCount(9);
  await settle(page);
}

/** Two animation frames and a short pause: Sigma renders on the next frame. */
async function settle(page: Page, ms = 150) {
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
  await page.waitForTimeout(ms);
}

/** Graph → page coordinates, derived from the logo (hub) and the category labels. */
async function screenMapping(page: Page) {
  const dom = await page.evaluate(() => {
    const centre = (el: Element) => {
      const r = el.getBoundingClientRect();
      return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    };
    return {
      origin: centre(document.querySelector('[data-testid="atlas-logo"]')!),
      labels: [...document.querySelectorAll<HTMLElement>('[data-testid="atlas-category-label"]')].map((el) => ({
        id: el.dataset.category!,
        ...centre(el),
      })),
    };
  });
  const scales = dom.labels.map((l) => {
    const c = tree.categories.find((x) => x.id === l.id)!;
    return Math.hypot(l.x - dom.origin.x, l.y - dom.origin.y) / Math.hypot(c.label_x, c.label_y);
  });
  const s = scales.reduce((a, b) => a + b, 0) / scales.length;
  const toScreen = (x: number, y: number): Point => ({ x: dom.origin.x + x * s, y: dom.origin.y - y * s });
  // The mapping must reproduce every label (y up in the graph, down on screen).
  for (const l of dom.labels) {
    const c = tree.categories.find((x) => x.id === l.id)!;
    const p = toScreen(c.label_x, c.label_y);
    expect(Math.hypot(p.x - l.x, p.y - l.y), `label ${l.id} matches the mapping`).toBeLessThan(2);
  }
  return { toScreen, at: (id: string) => toScreen(nodeById.get(id)!.x, nodeById.get(id)!.y) };
}

/** 7×7 pixel windows (RGBA) around each point, read from a viewport screenshot. */
async function windows(page: Page, points: Point[]) {
  const png = (await page.screenshot({ animations: "disabled" })).toString("base64");
  return page.evaluate(
    async ({ png, points }) => {
      const img = new Image();
      img.src = `data:image/png;base64,${png}`;
      await img.decode();
      const c = document.createElement("canvas");
      c.width = img.width;
      c.height = img.height;
      const ctx = c.getContext("2d")!;
      ctx.drawImage(img, 0, 0);
      const k = img.width / window.innerWidth;
      return points.map((p) => Array.from(ctx.getImageData(Math.round(p.x * k) - 3, Math.round(p.y * k) - 3, 7, 7).data));
    },
    { png, points },
  );
}

/** How many windows differ visibly between two samples. */
function changed(a: number[][], b: number[][]) {
  return a.filter((w, i) => w.some((v, j) => j % 4 !== 3 && Math.abs(v - b[i][j]) > 40)).length;
}

/** Page scroll and scrollers nested in scrollers. */
async function scrollReport(page: Page) {
  return page.evaluate(() => {
    const scrollers = [...document.querySelectorAll<HTMLElement>("body *")].filter((el) => {
      const s = getComputedStyle(el);
      return /(auto|scroll)/.test(s.overflowY) && el.scrollHeight > el.clientHeight + 1;
    });
    const name = (el: HTMLElement) => el.dataset.testid ?? `${el.tagName.toLowerCase()}.${el.className.toString().slice(0, 60)}`;
    return {
      pageY: document.scrollingElement!.scrollHeight - window.innerHeight,
      pageX: document.scrollingElement!.scrollWidth - window.innerWidth,
      nested: scrollers.filter((el) => scrollers.some((o) => o !== el && o.contains(el))).map(name),
    };
  });
}

test.describe("atlas", () => {
  test("shows the counts, the hub, nine category names and no panel", async ({ page }) => {
    await mockApi(page, graphMocks());
    const errors = trackConsoleErrors(page);
    await page.goto("/atlas");
    await expect(page.getByRole("heading", { level: 1, name: "Atlas" })).toBeVisible();
    // N = entities, M = real connections.
    const entities = tree.nodes.filter((n) => n.kind === "entity").length;
    await expect(page.getByTestId("atlas-counts")).toHaveText(`${entities} items · ${tree.edges.length} connections`);
    await mapReady(page);

    // The logo is the hub, in the middle of the map.
    const canvas = (await page.getByTestId("atlas-canvas").boundingBox())!;
    const logo = (await page.getByTestId("atlas-logo").boundingBox())!;
    expect(Math.abs(logo.x + logo.width / 2 - (canvas.x + canvas.width / 2))).toBeLessThan(4);
    expect(Math.abs(logo.y + logo.height / 2 - (canvas.y + canvas.height / 2))).toBeLessThan(4);
    await expect(page.getByTestId("atlas-logo").locator("img")).toHaveAttribute("src", "/amber-logo-128.png");

    // Nine category names, mixed case, inside the canvas and clear of each other.
    const labels = page.getByTestId("atlas-category-label");
    const seen = await labels.evaluateAll((els) =>
      els.map((el) => {
        const r = el.getBoundingClientRect();
        return { id: (el as HTMLElement).dataset.category!, text: el.textContent ?? "", box: [r.left, r.top, r.right, r.bottom] };
      }),
    );
    expect(seen.map((l) => l.id).sort()).toEqual(Object.keys(CATEGORY_TEXT).sort());
    for (const l of seen) {
      expect(CATEGORY_TEXT[l.id], `name of ${l.id}`).toContain(l.text);
      expect(l.text).not.toBe(l.text.toUpperCase());
      expect(l.box[0]).toBeGreaterThanOrEqual(canvas.x - 1);
      expect(l.box[2]).toBeLessThanOrEqual(canvas.x + canvas.width + 1);
      for (const o of seen) {
        if (o === l) continue;
        const overlap = l.box[0] < o.box[2] && l.box[2] > o.box[0] && l.box[1] < o.box[3] && l.box[3] > o.box[1];
        expect(overlap, `${l.id} and ${o.id} overlap`).toBe(false);
      }
    }

    // Nothing selected: no panel at all.
    await expect(page.getByTestId("atlas-panel")).toHaveCount(0);
    expect(errors()).toEqual([]);
  });

  test("?focus= opens the panel; closing it clears the URL", async ({ page }) => {
    await mockApi(page, graphMocks());
    const errors = trackConsoleErrors(page);
    await page.goto(`/atlas?focus=${encodeURIComponent(DRAVET)}`);
    const panel = page.getByTestId("atlas-panel");
    await expect(panel.getByRole("heading", { level: 2, name: "Dravet syndrome" })).toBeVisible();
    await expect(panel.getByTestId("atlas-summary-section").first()).toBeVisible();
    await expect(page.getByTestId("atlas-open-node")).toHaveAttribute("href", `/node/${encodeURIComponent(DRAVET)}`);
    await panel.getByRole("button", { name: "Close summary" }).click();
    await expect(panel).toHaveCount(0);
    await expect(page).not.toHaveURL(/focus=/);
    expect(errors()).toEqual([]);
  });

  test("clicking a dot draws its connections, the filter limits them, empty canvas clears", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockApi(page, graphMocks());
    const errors = trackConsoleErrors(page);
    await page.goto("/atlas");
    await mapReady(page);
    const canvas = (await page.getByTestId("atlas-canvas").boundingBox())!;
    const before = await screenMapping(page);

    // Click the dot: it is selected, the panel opens and the camera frames it.
    const dot = before.at(DRAVET);
    await page.mouse.click(dot.x, dot.y);
    await expect(page.getByTestId("atlas-panel").getByRole("heading", { level: 2, name: "Dravet syndrome" })).toBeVisible();
    await expect(page).toHaveURL(/focus=MONDO%3A0100135/);
    const away = async () => page.mouse.move(2, 2);
    await away();
    await settle(page, 300);

    // Sample the two lines just outside the dot, in the camera's new frame.
    const { at, toScreen } = await screenMapping(page);
    const a = at(DRAVET);
    const near = (b: Point) => {
      const d = Math.hypot(b.x - a.x, b.y - a.y);
      return [34, 42, 50, 58, 66].map((r) => ({ x: a.x + ((b.x - a.x) * r) / d, y: a.y + ((b.y - a.y) * r) / d }));
    };
    const points = [...near(at(SEIZURE)), ...near(at(SCN1A))];
    const sym = (w: number[][]) => w.slice(0, 5);
    const gene = (w: number[][]) => w.slice(5);
    const selected = await windows(page, points);

    // Hide "symptoms" connections: that line goes, the gene line stays.
    await page.getByTestId("atlas-filters").click();
    await page.getByTestId("family-chip-symptoms").click();
    await expect(page.getByTestId("family-chip-symptoms")).toHaveAttribute("aria-pressed", "false");
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("atlas-filters")).toContainText("1");
    await away();
    await settle(page);
    const filtered = await windows(page, points);
    expect(changed(sym(selected), sym(filtered)), "the symptom connection was drawn and is hidden by the filter").toBeGreaterThanOrEqual(4);
    expect(changed(gene(selected), gene(filtered)), "other kinds stay drawn").toBeLessThanOrEqual(1);

    // Empty canvas (a spot far from every dot, outside the panel and the overlays) clears.
    const dots = tree.nodes.map((n) => toScreen(n.x, n.y));
    const spot = [0.08, 0.15, 0.25, 0.35]
      .flatMap((fx) => [0.35, 0.5, 0.65].map((fy) => ({ x: canvas.x + canvas.width * fx, y: canvas.y + canvas.height * fy })))
      .find((p) => dots.every((d) => Math.hypot(d.x - p.x, d.y - p.y) > 40));
    expect(spot, "an empty spot on the canvas").toBeTruthy();
    await page.mouse.click(spot!.x, spot!.y);
    await expect(page.getByTestId("atlas-panel")).toHaveCount(0);
    await expect(page).not.toHaveURL(/focus=/);
    await away();
    await settle(page);
    const cleared = await windows(page, points);
    expect(changed(gene(filtered), gene(cleared)), "the remaining connection is gone").toBeGreaterThanOrEqual(4);
    expect(changed(sym(filtered), sym(cleared)), "nothing new is drawn").toBeLessThanOrEqual(1);
    expect(errors()).toEqual([]);
  });

  test("the logo clears the selection", async ({ page }) => {
    await mockApi(page, graphMocks());
    await page.goto(`/atlas?focus=${encodeURIComponent(DRAVET)}`);
    await expect(page.getByTestId("atlas-panel")).toBeVisible();
    await mapReady(page);
    // The focus framed the dot closely; back to the whole map, then the hub.
    await page.locator('button[aria-label="Show the whole map"]:not([data-testid="atlas-logo"])').click();
    await expect(page.getByTestId("atlas-panel")).toBeVisible();
    await settle(page, 600);
    await page.getByTestId("atlas-logo").click();
    await expect(page.getByTestId("atlas-panel")).toHaveCount(0);
    await expect(page).not.toHaveURL(/focus=/);
  });

  test("?path= shows the banner for known edges and ignores unknown ids", async ({ page }) => {
    await mockApi(page, graphMocks());
    const errors = trackConsoleErrors(page);
    await page.goto("/atlas?focus=MONDO%3A9900003&path=e_3b8845b635b8,e_0af807385728,e_558f7d2a940d,e_nope");
    await expect(page.getByTestId("atlas-path-banner")).toContainText("path of 3 connections");
    await expect(page.getByTestId("atlas-panel").getByRole("heading", { level: 2 })).toContainText("SCN2A developmental");
    await mapReady(page);
    await shot(page, "atlas-path-desktop");
    await page.getByRole("button", { name: "Show everything" }).click();
    await expect(page.getByTestId("atlas-path-banner")).toBeHidden();
    await expect(page).not.toHaveURL(/path=/);
    expect(errors()).toEqual([]);
  });

  test("an unknown focus id says so", async ({ page }) => {
    await mockApi(page, graphMocks());
    await page.goto("/atlas?focus=MONDO%3A404");
    const notice = page.getByTestId("atlas-missing-focus");
    await expect(notice).toContainText("MONDO:404");
    await expect(notice.getByRole("link", { name: "Open it directly" })).toHaveAttribute("href", "/node/MONDO%3A404");
    await expect(page.getByTestId("atlas-panel")).toHaveCount(0);
  });

  test("an empty tree shows a clear state", async ({ page }) => {
    await mockApi(
      page,
      graphMocks({
        "GET /atlas/tree.json": { ...tree, categories: [], nodes: [tree.nodes[0]], edges: [], clusters: [] },
      }),
    );
    await page.goto("/atlas");
    await expect(page.getByTestId("atlas-empty")).toContainText("empty");
  });

  test("a failed load shows an error with retry", async ({ page }) => {
    let fail = true;
    await mockApi(
      page,
      graphMocks({
        "GET /atlas/tree.json": () => (fail ? errorEnvelope(500, "internal_error") : { json: tree }),
      }),
    );
    await page.goto("/atlas");
    await expect(page.getByTestId("atlas-error")).toContainText("could not be loaded");
    fail = false;
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByTestId("atlas-counts")).toContainText("69 items");
    await mapReady(page);
  });

  test("API down and not implemented degrade gracefully", async ({ page }) => {
    await mockApi(page, { "GET /auth/session": { user: null } });
    await page.goto("/atlas");
    await expect(page.getByTestId("atlas-error")).toContainText("can't be reached");
    await mockApi(page, graphMocks({ "GET /atlas/tree.json": errorEnvelope(501, "not_implemented") }));
    await page.reload();
    await expect(page.getByTestId("atlas-error")).toContainText("not available yet");
  });

  test("fits the viewport: no page scroll, no scroller inside a scroller", async ({ page }) => {
    await mockApi(page, graphMocks());
    await page.goto("/atlas");
    await mapReady(page);
    let r = await scrollReport(page);
    expect(r.pageY, "no vertical page scroll").toBeLessThanOrEqual(0);
    expect(r.pageX, "no horizontal page scroll").toBeLessThanOrEqual(0);
    expect(r.nested).toEqual([]);
    // No site footer on the Atlas.
    await expect(page.locator("footer")).toHaveCount(0);

    await page.goto(`/atlas?focus=${encodeURIComponent("MONDO:9900007")}`);
    await expect(page.getByTestId("atlas-summary-section").first()).toBeVisible();
    r = await scrollReport(page);
    expect(r.pageY).toBeLessThanOrEqual(0);
    expect(r.nested).toEqual([]);
    const panel = (await page.getByTestId("atlas-panel").boundingBox())!;
    expect(panel.y + panel.height).toBeLessThanOrEqual(page.viewportSize()!.height);

    await page.getByTestId("view-toggle").getByRole("radio", { name: "List" }).click();
    await expect(page.getByTestId("atlas-outline")).toBeVisible();
    r = await scrollReport(page);
    expect(r.pageY).toBeLessThanOrEqual(0);
    expect(r.nested).toEqual([]);
  });

  for (const c of [
    { name: "a guest's Doctor lens", stored: "doctor", category: "symptoms" },
    { name: "a guest's Patient lens", stored: "patient", category: "diseases" },
    { name: "a signed-in doctor whose session arrives late", role: "doctor", category: "symptoms" },
  ]) {
    test(`after a reload, ${c.name} starts on its tree`, async ({ page }) => {
      await page.emulateMedia({ reducedMotion: "reduce" });
      const session = c.role
        ? async () => {
            await new Promise((r) => setTimeout(r, 800));
            return { json: { ...signedInSession({ role: c.role }), data_version: "fixture" } };
          }
        : undefined;
      await mockApi(page, graphMocks(session ? { "GET /auth/session": session } : {}));
      if (c.stored) await page.addInitScript((lens) => window.localStorage.setItem("amber.lens", lens), c.stored);
      await page.goto("/atlas");
      await mapReady(page);
      // The camera frames the category's tree: the middle of its extent sits in the middle of the canvas.
      const { toScreen } = await screenMapping(page);
      const own = tree.nodes.filter((n) => n.category === c.category);
      const xs = own.map((n) => n.x);
      const ys = own.map((n) => n.y);
      const mid = toScreen((Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2);
      const canvas = (await page.getByTestId("atlas-canvas").boundingBox())!;
      expect(Math.abs(mid.x - (canvas.x + canvas.width / 2))).toBeLessThan(8);
      expect(Math.abs(mid.y - (canvas.y + canvas.height / 2))).toBeLessThan(8);
    });
  }

  test("reduced motion moves the camera without animation", async ({ page }) => {
    /** Logo widths seen while one "Zoom in" plays out (the logo scales with the camera). */
    const zoomSteps = () =>
      page.evaluate(
        () =>
          new Promise<number[]>((resolve) => {
            const logo = document.querySelector<HTMLElement>('[data-testid="atlas-logo"]')!;
            const seen: number[] = [];
            const obs = new MutationObserver(() => {
              const w = parseFloat(logo.style.width);
              if (seen[seen.length - 1] !== w) seen.push(w);
            });
            obs.observe(logo, { attributes: true, attributeFilter: ["style"] });
            document.querySelector<HTMLElement>('button[aria-label="Zoom in"]')!.click();
            setTimeout(() => {
              obs.disconnect();
              resolve(seen);
            }, 1200);
          }),
      );
    await mockApi(page, graphMocks());
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/atlas");
    await mapReady(page);
    expect((await page.getByTestId("atlas-logo").boundingBox())!.width).toBeCloseTo(44, 0);
    // 44 px at the whole map, 44 × 1.6^0.35 ≈ 52 px one step in: straight there.
    expect(await zoomSteps()).toEqual([52]);

    await page.emulateMedia({ reducedMotion: "no-preference" });
    await page.reload();
    await mapReady(page);
    const steps = await zoomSteps();
    expect(steps[steps.length - 1]).toBe(52);
    expect(steps.length, "an animated move passes through in-between sizes").toBeGreaterThan(2);
  });

  test("about 7,000 tree nodes and 17,000 connections stay interactive", async ({ page }) => {
    test.setTimeout(180_000);
    const big = largeAtlasTree(6343, 17000);
    expect(big.tree.nodes.length).toBeGreaterThan(6900);
    await mockApi(page, graphMocks({ "GET /atlas/tree.json": big.tree, "GET /atlas/summary/*": big.summary }));
    const errors = trackConsoleErrors(page);
    await page.goto("/atlas");
    await expect(page.getByTestId("atlas-counts")).toHaveText("6,343 items · 17,000 connections", { timeout: 60_000 });
    const canvas = page.getByTestId("atlas-canvas");
    await expect(canvas.locator("canvas").first()).toBeVisible({ timeout: 90_000 });
    await expect(page.getByTestId("atlas-category-label")).toHaveCount(9);
    const box = (await canvas.boundingBox())!;

    // Wheel-zoom and drag; the main thread must stay responsive.
    const t0 = Date.now();
    await page.mouse.move(box.x + box.width / 2 - 200, box.y + box.height / 2);
    await page.mouse.wheel(0, -400);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 - 80, box.y + box.height / 2 + 60, { steps: 8 });
    await page.mouse.up();
    const frame = () =>
      page.evaluate(
        () =>
          new Promise<number>((resolve) => {
            const s = performance.now();
            requestAnimationFrame(() => requestAnimationFrame(() => resolve(performance.now() - s)));
          }),
      );
    // Generous: the mocked suite renders WebGL in software (SwiftShader).
    expect(await frame()).toBeLessThan(1500);

    // Search and select: the panel opens and the node's connections are drawn.
    const input = page.getByTestId("atlas-search").getByRole("combobox", { name: "Search the map" });
    await input.fill("Synthetic item 1234");
    await expect(page.getByTestId("atlas-search").locator('[data-node-id="SYN:1234"]')).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("atlas-panel").getByRole("heading", { level: 2 })).toHaveText("Synthetic item 1234");
    expect(await frame()).toBeLessThan(1500);
    expect(Date.now() - t0).toBeLessThan(60_000);
    await settle(page, 400);
    await shot(page, "atlas-large-desktop");
    expect(errors()).toEqual([]);
  });

  test("screenshots: light and dark", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockApi(page, graphMocks());
    for (const theme of ["light", "dark"] as const) {
      await setTheme(page, theme);
      await page.goto("/atlas");
      await mapReady(page);
      await shot(page, `atlas-${theme}-desktop`);
      await page.goto("/atlas?focus=MONDO%3A9900007");
      await expect(page.getByTestId("atlas-summary-section").first()).toBeVisible();
      await mapReady(page);
      await shot(page, `atlas-focus-${theme}-desktop`);
    }
  });
});

test("atlas on a phone @mobile", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockApi(page, graphMocks());
  const errors = trackConsoleErrors(page);
  await page.goto("/atlas");
  await mapReady(page);
  await expect(page.getByTestId("atlas-logo")).toBeVisible();
  await expect(page.getByTestId("atlas-panel")).toHaveCount(0);
  let r = await scrollReport(page);
  expect(r.pageY).toBeLessThanOrEqual(0);
  expect(r.pageX).toBeLessThanOrEqual(0);
  await shot(page, "atlas-map-mobile");

  // Selecting opens a short sheet over the map that expands.
  await page.goto("/atlas?focus=MONDO%3A9900007");
  const sheet = page.getByTestId("atlas-sheet");
  await expect(sheet.getByTestId("atlas-panel")).toBeVisible();
  await expect(sheet.getByTestId("atlas-summary-section").first()).toBeVisible();
  const vh = page.viewportSize()!.height;
  const short = (await sheet.boundingBox())!.height;
  expect(short).toBeLessThanOrEqual(vh * 0.41);
  const toggle = sheet.getByRole("button", { name: "Show more" });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await settle(page, 300);
  await shot(page, "atlas-mobile");
  await toggle.click();
  await expect(sheet.getByRole("button", { name: "Show less" })).toHaveAttribute("aria-expanded", "true");
  await expect.poll(async () => (await sheet.boundingBox())!.height).toBeGreaterThan(short + 40);
  expect((await sheet.boundingBox())!.height).toBeLessThanOrEqual(vh * 0.79);
  r = await scrollReport(page);
  expect(r.pageY).toBeLessThanOrEqual(0);
  expect(r.nested).toEqual([]);
  await shot(page, "atlas-mobile-expanded");

  await sheet.getByRole("button", { name: "Close summary" }).click();
  await expect(page.getByTestId("atlas-panel")).toHaveCount(0);
  await page.getByTestId("view-toggle").getByRole("radio", { name: "List" }).click();
  await expect(page.getByTestId("atlas-outline")).toBeVisible();
  await shot(page, "atlas-list-mobile");
  expect(errors()).toEqual([]);
});
