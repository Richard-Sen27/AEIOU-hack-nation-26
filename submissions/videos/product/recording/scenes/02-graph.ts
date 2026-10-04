// Scene 2 "The graph": Atlas overview, ⌘K search for PRP, its graph of links,
// then the sources of the link to the gene CARD14.
// Narration (voiceover/02-graph.mp3): "Amber connects it." 0–0.9 s · "One
// search places the disease among seven thousand others:" 1.5–4.4 s ·
// "symptoms, look-alike conditions," 4.6–6.2 s · "and one gene, CARD14."
// 6.5–8.4 s · "Every link shows its sources." 9.0–10.7 s.

import type { Page } from "playwright";
import { url } from "../lib/browser.ts";
import { waitForAtlas } from "../lib/atlas.ts";
import type { SceneTake } from "../lib/scene.ts";

const PRP = "MONDO:0008251";

// Screen position (CSS px) of the link between the centre and a neighbour in
// the node page's Cytoscape graph, read from the graph itself.
async function edgeMidpoint(
  page: Page,
  neighbour: string,
): Promise<{ x: number; y: number }> {
  const point = await page.evaluate((name) => {
    const host = document.querySelector('[data-testid="node-graph"]') as
      | (HTMLElement & { _cyreg?: { cy?: CyLike } })
      | null;
    type CyEdge = {
      source: () => { data: (k: string) => string };
      target: () => { data: (k: string) => string };
      renderedMidpoint: () => { x: number; y: number };
    };
    type CyLike = { edges: () => { toArray: () => CyEdge[] } };
    const cy = host?._cyreg?.cy;
    if (!host || !cy) return null;
    const edge =
      cy
        .edges()
        .toArray()
        .find(
          (e) => e.source().data("center") && e.target().data("name") === name,
        ) ??
      cy
        .edges()
        .toArray()
        .find((e) =>
          [e.source().data("name"), e.target().data("name")].includes(name),
        );
    if (!edge) return null;
    const box = host.getBoundingClientRect();
    const mid = edge.renderedMidpoint();
    return { x: box.x + mid.x, y: box.y + mid.y };
  }, neighbour);
  if (!point) throw new Error(`No link to ${neighbour} in the graph.`);
  return point;
}

// Cytoscape positions settle a moment after the canvas appears.
async function waitForGraphLayout(page: Page): Promise<void> {
  await page
    .getByTestId("node-graph")
    .locator("canvas")
    .first()
    .waitFor({ timeout: 60_000 });
  let last = "";
  for (let i = 0; i < 40; i++) {
    const now = JSON.stringify(
      await edgeMidpoint(page, "CARD14").catch(() => null),
    );
    if (now !== "null" && now === last) return;
    last = now;
    await page.waitForTimeout(250);
  }
}

export const graph: SceneTake = {
  id: "graph",
  frames: 338,
  signedIn: false,
  run: async ({ page, rec, pointer }) => {
    // Beat 1 · 0–1.5 s: the whole map.
    await rec.cut(async () => {
      await page.goto(url("/atlas"));
      await waitForAtlas(page);
      await page.waitForTimeout(1500);
      await pointer.jump({ x: 1000, y: 112 });
    });
    await rec.holdUntil(500);
    // Drift towards the header search, then use its shortcut.
    await pointer.moveToLocator(
      page.getByRole("button", { name: /Search the atlas/ }).first(),
      {
        duration: 800,
        anchor: { x: 0.35, y: 0.6 },
      },
    );
    await rec.holdUntil(1500);

    // Beat 2 · 1.5–3.3 s: ⌘K, "pityriasis", Enter on the first result.
    rec.mark("⌘K");
    await page.keyboard.press("Meta+k");
    const input = page.getByPlaceholder(
      "Disease, gene, symptom, patient group…",
    );
    await input.waitFor();
    await rec.hold(250);
    await pointer.type("pityriasis", { cps: 12 });
    const dialog = page.getByTestId("global-search");
    const first = dialog.getByRole("option").first();
    await rec.cut(async () => {
      await first
        .getByText("familial pityriasis rubra pilaris")
        .first()
        .waitFor();
    });
    rec.mark("first result: familial pityriasis rubra pilaris");
    await rec.hold(650);
    await page.keyboard.press("Enter");

    // Beat 3 · ~3.3–7 s: the graph of PRP's links, the cursor passing over
    // the symptoms (below), the look-alike conditions (above), then CARD14.
    await rec.cut(async () => {
      await page.waitForURL(/\/node\/MONDO%3A0008251/);
      await page
        .getByRole("heading", {
          level: 1,
          name: /familial pityriasis rubra pilaris/i,
        })
        .waitFor();
      await waitForGraphLayout(page);
      await page.waitForTimeout(400);
    });
    if (!page.url().includes(encodeURIComponent(PRP)))
      throw new Error(`Unexpected page ${page.url()}`);
    rec.mark("PRP graph");
    const graphBox = await page.getByTestId("node-graph").boundingBox();
    if (!graphBox) throw new Error("Graph not visible");
    const card14 = await edgeMidpoint(page, "CARD14");
    const cx = card14.x;
    await rec.holdUntil(3700);
    // Symptoms row (below the centre) at "symptoms".
    await pointer.moveTo(
      { x: cx + 150, y: graphBox.y + graphBox.height * 0.86 },
      { duration: 800 },
    );
    await pointer.moveTo(
      { x: cx - 120, y: graphBox.y + graphBox.height * 0.84 },
      { duration: 650 },
    );
    // Look-alike conditions (top block) at "look-alike conditions".
    await pointer.moveTo(
      { x: cx - 140, y: graphBox.y + graphBox.height * 0.25 },
      { duration: 850 },
    );
    await rec.holdUntil(5950);
    // "and one gene, CARD14": click the link to CARD14.
    await pointer.click(card14, { duration: 800, dwell: 220 });
    rec.mark("clicked the CARD14 link");

    // Beat 4 · ~7–11.3 s: the link's sheet, scrolled to its sources.
    const sheet = page.getByTestId("edge-panel");
    await rec.cut(async () => {
      await sheet.getByText(/Supporting · 5/).waitFor();
    });
    if (await page.getByText("[object Object]").count()) {
      throw new Error('"[object Object]" is on screen in the sources sheet.');
    }
    await rec.hold(120);
    // The side panel (an <aside>) scrolls; the sheet inside it does not.
    const panel = sheet.locator("xpath=ancestor::aside[1]");
    const panelBox = await panel.boundingBox();
    if (!panelBox) throw new Error("Side panel not visible");
    await pointer.moveTo(
      {
        x: panelBox.x + panelBox.width * 0.55,
        y: panelBox.y + panelBox.height * 0.55,
      },
      { duration: 450 },
    );
    // Bring "Sources · Supporting · 5" to the top of the panel.
    const heading = sheet.getByText(/Supporting · 5/).first();
    const headingBox = await heading.boundingBox();
    if (!headingBox) throw new Error("Sources heading not visible");
    await pointer.wheel(headingBox.y - (panelBox.y + 50), { duration: 750 });
    rec.mark("sources in view");
    // Off the chips and quotes, into the empty corner beside "Sources".
    await pointer.moveTo(
      { x: panelBox.x + panelBox.width * 0.86, y: panelBox.y + 62 },
      { duration: 600 },
    );
    await rec.holdUntil(338 * (1000 / 30) + 150);
  },
};
