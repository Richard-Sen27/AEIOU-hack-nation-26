import { expect, test, type Page } from "@playwright/test";

import { API_URL, errorEnvelope, hit, mockApi, setTheme, shot, signedInSession, trackConsoleErrors } from "../helpers";
import { graphMocks } from "./fixtures";

const DRAVET = "/node/MONDO%3A0100135";
const SCN2A_LATE = "/node/MONDO%3A9900005"; // has the contradicted seizure edge
const SCN2A_EARLY = "/node/MONDO%3A9900003"; // counterexample + similar symptoms

/** The lens follows the signed-in role from settings: sign in with that role and reload. */
async function signInAs(page: Page, role: string, extra: Record<string, unknown> = {}) {
  await mockApi(page, graphMocks({ ...extra, "GET /auth/session": signedInSession({ role }) }));
  await page.reload();
}

test.describe("node view", () => {
  test("shows the neighbourhood, summary and grouped connections", async ({ page }) => {
    await mockApi(page, graphMocks());
    const errors = trackConsoleErrors(page);
    await page.goto(DRAVET);
    await expect(page.getByRole("heading", { level: 1, name: "Dravet syndrome" })).toBeVisible();
    await expect(page.getByTestId("node-counts")).toContainText("items");
    await expect(page.getByTestId("node-graph").locator("canvas").first()).toBeVisible({ timeout: 30_000 });
    const panel = page.getByTestId("node-panel");
    await expect(panel).toContainText("Severe childhood epilepsy");
    await expect(panel).toContainText("Also called:");
    await expect(panel.getByTestId("node-cluster-link")).toHaveAttribute("href", "/node/CLUSTER%3A2");
    await expect(panel.getByTestId("relation-group").first()).toBeVisible();
    await expect(page.getByTestId("family-chip-symptoms")).toContainText(/\d+/);
    await expect(page.getByTestId("open-in-atlas")).toHaveAttribute("href", "/atlas?focus=MONDO%3A0100135");
    expect(errors()).toEqual([]);
  });

  test("the role's lens changes wording but not the nodes or edges", async ({ page }) => {
    const roles: string[] = [];
    const neighborhood = {
      "GET /neighborhood/*": (req: { url: string }) => {
        roles.push(new URL(req.url).searchParams.get("role") ?? "");
        return (graphMocks()["GET /neighborhood/*"] as (r: { url: string }) => unknown)(req) as never;
      },
    };
    await mockApi(page, graphMocks(neighborhood));
    await page.goto(DRAVET);
    const counts = page.getByTestId("node-counts");
    await expect(counts).toContainText("connections");
    const before = await counts.textContent();
    const headings = page.getByTestId("relation-heading");
    await expect(headings.filter({ hasText: "can cause" })).toHaveCount(1);
    await page.getByRole("radio", { name: "List" }).click();
    const rowsBefore = await page.getByTestId("node-list-row").count();

    await signInAs(page, "researcher", neighborhood);
    await page.getByRole("radio", { name: "List" }).click();
    await expect(headings.filter({ hasText: "has_phenotype" })).toHaveCount(1);
    await expect(headings.filter({ hasText: "can cause" })).toHaveCount(0);
    await expect(counts).toHaveText(before!);
    await expect(page.getByTestId("node-list-row")).toHaveCount(rowsBefore);
    expect(roles).toContain("researcher");

    await signInAs(page, "doctor", neighborhood);
    await expect(headings.filter({ hasText: "presents with" })).toHaveCount(1);
    await expect(counts).toHaveText(before!);
  });

  test("edge evidence: contradiction side by side and the confidence breakdown", async ({ page }) => {
    await mockApi(page, graphMocks());
    const errors = trackConsoleErrors(page);
    await page.goto(SCN2A_LATE);
    await page.getByRole("button", { name: "Sources for Seizure" }).click();
    const edge = page.getByTestId("edge-panel");
    await expect(edge.getByTestId("edge-relation")).toHaveText("can cause");
    await expect(edge.getByTestId("contradiction-note")).toContainText("1 source contradicts");
    const list = edge.getByTestId("evidence-list");
    await expect(list.locator('[data-polarity="contradicts"]')).toHaveCount(1);
    await expect(list.locator('[data-polarity="supports"]')).toHaveCount(2);
    const breakdown = edge.getByTestId("confidence-breakdown");
    await expect(breakdown).toContainText("Support from sources");
    await expect(breakdown).toContainText("Contradicting sources (1 × 0.15)");
    await expect(edge.getByTestId("origin-badge")).toHaveAttribute("data-origin", "observed");
    await edge.getByRole("button", { name: "Back" }).click();
    await expect(page.getByTestId("node-panel")).toBeVisible();
    expect(errors()).toEqual([]);
  });

  test("counterexample and similar-symptoms features are explained", async ({ page }) => {
    await mockApi(page, graphMocks());
    await page.goto(SCN2A_EARLY);
    await page.getByRole("button", { name: /^Sources for SCN2A-related neurodevelopmental disorder/ }).first().click();
    const edge = page.getByTestId("edge-panel");
    await expect(edge.getByTestId("counterexample")).toContainText("same gene, different mechanism");
    await expect(edge.getByTestId("origin-badge")).toHaveAttribute("data-origin", "inferred");
    await edge.getByRole("button", { name: "Back" }).click();
    await page.getByRole("button", { name: "Sources for STXBP1 encephalopathy" }).first().click();
    const relation = page.getByTestId("edge-relation");
    if ((await relation.textContent())?.includes("similar")) {
      await expect(page.getByTestId("similar-symptoms-note")).toContainText("possibly different cause");
      await expect(page.getByTestId("edge-features")).toContainText("Shared symptoms");
      await expect(page.getByTestId("edge-features").getByTestId("node-chip").first()).toBeVisible();
    }
  });

  test("variant of uncertain significance shows the VUS notice", async ({ page }) => {
    await mockApi(page, graphMocks());
    await page.goto("/node/CLINVAR%3AFX0004");
    await expect(page.getByTestId("vus-notice").first()).toContainText(
      "This result is uncertain. Discuss it with a genetic counselor before acting on it.",
    );
  });

  test("flagging as a guest asks to sign in", async ({ page }) => {
    let posted = false;
    await mockApi(page, graphMocks({ "POST /edges/*/flag": () => ((posted = true), { json: {} }) }));
    await page.goto(SCN2A_LATE);
    await page.getByRole("button", { name: "Sources for Seizure" }).click();
    await page.getByTestId("flag-edge").click();
    await expect(page.getByTestId("sign-in-dialog")).toBeVisible();
    await expect(page.getByTestId("flag-dialog")).toBeHidden();
    expect(posted).toBe(false);
  });

  test("flagging signed in marks the edge under review", async ({ page }) => {
    let body: unknown = null;
    await mockApi(
      page,
      graphMocks({
        "GET /auth/session": signedInSession(),
        "POST /edges/*/flag": (req: { body: unknown; url: string }) => {
          body = req.body;
          return { json: { edge_id: "e_9a6ff6e0e247", status: "under_review", open_flags: 1 } };
        },
      }),
    );
    const errors = trackConsoleErrors(page);
    await page.goto(SCN2A_LATE);
    await page.getByRole("button", { name: "Sources for Seizure" }).click();
    await page.getByTestId("flag-edge").click();
    const dialog = page.getByTestId("flag-dialog");
    await expect(dialog).toBeVisible();
    await dialog.getByRole("textbox").fill("The review cited says seizures are not typical here.");
    await dialog.getByTestId("flag-submit").click();
    await expect(dialog).toBeHidden();
    expect(body).toEqual({ reason: "The review cited says seizures are not typical here." });
    await expect(page.getByTestId("edge-panel").getByTestId("status-flag")).toContainText("Under review");
    await page.getByRole("button", { name: "Back" }).click();
    await expect(page.getByTestId("node-panel").getByTestId("status-flag").first()).toContainText("Under review");
    expect(errors()).toEqual([]);
  });

  test("flag conflicts and personal-data rejections are explained", async ({ page }) => {
    let n = 0;
    await mockApi(
      page,
      graphMocks({
        "GET /auth/session": signedInSession(),
        "POST /edges/*/flag": () =>
          ++n === 1 ? errorEnvelope(422, "validation_error", "Looks like personal data") : errorEnvelope(409, "conflict"),
      }),
    );
    await page.goto(SCN2A_LATE);
    await page.getByRole("button", { name: "Sources for Seizure" }).click();
    await page.getByTestId("flag-edge").click();
    const dialog = page.getByTestId("flag-dialog");
    await dialog.getByRole("textbox").fill("My son Max has this and no seizures");
    await dialog.getByTestId("flag-submit").click();
    await expect(dialog.getByRole("alert")).toContainText("personal details");
    await dialog.getByTestId("flag-submit").click();
    await expect(dialog).toBeHidden();
    await expect(page.getByText("You already flagged this connection")).toBeVisible();
  });

  test("export links point at the subgraph download", async ({ page }) => {
    await mockApi(page, graphMocks());
    await page.goto(DRAVET);
    await page.getByTestId("export").click();
    await expect(page.getByTestId("export-csv")).toHaveAttribute(
      "href",
      `${API_URL}/export/graph?node=MONDO%3A0100135&depth=1&format=csv`,
    );
    await expect(page.getByTestId("export-graphml")).toHaveAttribute("href", /format=graphml/);
  });

  test("find a path picks a target and opens /path", async ({ page }) => {
    await mockApi(page, graphMocks({ "GET /search": { results: [hit("MONDO:9900007", "disease", "STXBP1 encephalopathy")] } }));
    await page.goto(DRAVET);
    await page.getByTestId("find-path").click();
    await page.getByRole("combobox", { name: "Path end point" }).fill("STXBP1");
    await page.getByRole("option", { name: /STXBP1 encephalopathy/ }).click();
    await expect(page).toHaveURL(/\/path\?from=MONDO%3A0100135&to=MONDO%3A9900007$/);
  });

  test("list view is a full alternative and links to neighbours", async ({ page }) => {
    await mockApi(page, graphMocks());
    await page.goto(DRAVET);
    await page.getByRole("radio", { name: "List" }).click();
    const rows = page.getByTestId("node-list-row");
    await expect(rows.first()).toBeVisible();
    await page.getByTestId("family-chip-symptoms").click();
    await expect(page.getByTestId("family-chip-symptoms")).toHaveAttribute("aria-pressed", "false");
    await page.getByTestId("node-list").getByRole("link", { name: /^SCN1A/ }).first().click();
    await expect(page).toHaveURL(/\/node\/HGNC%3A10585$/);
    await expect(page.getByRole("heading", { level: 1, name: "SCN1A" })).toBeVisible();
  });

  test("patient organisation shows actionable fields", async ({ page }) => {
    await mockApi(page, graphMocks());
    await page.goto("/node/ORG%3Afx-dravet-families");
    const attrs = page.getByTestId("node-attrs");
    await expect(attrs).toContainText("What it is");
    await expect(attrs).toContainText("Country");
  });

  test("unknown node and API down show clear states", async ({ page }) => {
    await mockApi(page, graphMocks());
    await page.goto("/node/MONDO%3A404");
    await expect(page.getByTestId("node-error")).toContainText("not in the atlas");
    await mockApi(page, { "GET /auth/session": { user: null } });
    await page.goto(DRAVET);
    await expect(page.getByTestId("node-error")).toContainText("can't be reached");
  });

  test("neighbourhood not implemented still shows the summary", async ({ page }) => {
    await mockApi(page, graphMocks({ "GET /neighborhood/*": errorEnvelope(501, "not_implemented") }));
    await page.goto(DRAVET);
    await expect(page.getByTestId("hood-error")).toContainText("not available yet");
    await expect(page.getByTestId("node-panel")).toContainText("Severe childhood epilepsy");
  });

  for (const viewport of [{ width: 1440, height: 900 }, { width: 1280, height: 720 }]) {
    test(`desktop ${viewport.width}x${viewport.height}: the page does not scroll, each column scrolls inside`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await mockApi(page, graphMocks());
      await page.goto(DRAVET);
      await expect(page.getByTestId("node-graph").locator("canvas").first()).toBeVisible({ timeout: 30_000 });
      const side = page.getByTestId("node-panel").locator("xpath=ancestor::aside[@id='node-side']");
      await expect(side).toBeVisible();
      for (const view of ["Graph", "List"]) {
        await page.getByRole("radio", { name: view }).click();
        const m = await page.evaluate(() => {
          const se = document.scrollingElement!;
          const aside = document.getElementById("node-side")!;
          const list = document.querySelector<HTMLElement>('[data-testid="node-list"]');
          return {
            docOverflow: se.scrollHeight - se.clientHeight,
            asideBottom: aside.getBoundingClientRect().bottom,
            asideOverflowY: getComputedStyle(aside).overflowY,
            listBottom: list?.getBoundingClientRect().bottom ?? 0,
          };
        });
        expect(m.docOverflow, `${view}: page scroll`).toBeLessThanOrEqual(1);
        expect(m.asideBottom).toBeLessThanOrEqual(viewport.height);
        expect(m.asideOverflowY).toBe("auto");
        expect(m.listBottom).toBeLessThanOrEqual(viewport.height);
      }
      // The side card scrolls within itself when its content is taller than the column.
      const scrolled = await side.evaluate((el) => {
        if (el.scrollHeight <= el.clientHeight) return "fits";
        el.scrollTop = 120;
        return el.scrollTop > 0 ? "scrolled" : "stuck";
      });
      expect(["fits", "scrolled"]).toContain(scrolled);
      expect(await page.evaluate(() => window.scrollY)).toBe(0);
    });
  }

  test("the map key is collapsed until opened and closes with Escape", async ({ page }) => {
    await mockApi(page, graphMocks());
    await page.goto(DRAVET);
    await expect(page.getByTestId("node-graph").locator("canvas").first()).toBeVisible({ timeout: 30_000 });
    const toggle = page.getByRole("button", { name: /^Key/ });
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByTestId("graph-legend")).toHaveCount(0);
    await toggle.focus();
    await page.keyboard.press("Enter");
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByTestId("graph-legend")).toContainText("Line style");
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("graph-legend")).toHaveCount(0);
    await expect(toggle).toBeFocused();
  });

  test("a five-node graph keeps labels and nodes in proportion to the page", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    // Dravet syndrome with only four neighbours.
    const small = {
      "GET /neighborhood/*": (req: { url: string }) => {
        const full = (graphMocks()["GET /neighborhood/*"] as (r: { url: string }) => { json: { nodes: { id: string }[]; edges: { source_id: string; target_id: string }[]; center: { id: string } } })(req).json;
        const keep = new Set([full.center.id, ...full.nodes.filter((n) => n.id !== full.center.id).slice(0, 4).map((n) => n.id)]);
        return { json: { ...full, nodes: full.nodes.filter((n) => keep.has(n.id)), edges: full.edges.filter((e) => keep.has(e.source_id) && keep.has(e.target_id)) } };
      },
    };
    await mockApi(page, graphMocks(small));
    await page.goto(DRAVET);
    await expect(page.getByTestId("node-counts")).toContainText("5 items");
    const graph = page.getByTestId("node-graph");
    await expect(graph.locator("canvas").first()).toBeVisible({ timeout: 30_000 });
    await page.waitForTimeout(800);
    const m = await graph.evaluate((el) => {
      type N = { id: () => string; style: (k: string) => string; renderedWidth: () => number; renderedBoundingBox: (o: object) => { x1: number; x2: number; y1: number; y2: number } };
      const cy = (el as unknown as { _cyreg: { cy: { zoom: () => number; nodes: () => { toArray: () => N[] } } } })._cyreg.cy;
      const zoom = cy.zoom();
      const nodes = cy.nodes().toArray();
      const labels = nodes.map((n) => n.renderedBoundingBox({ includeNodes: false, includeEdges: false, includeLabels: true }));
      let overlaps = 0;
      for (let i = 0; i < labels.length; i++)
        for (let j = i + 1; j < labels.length; j++) {
          const a = labels[i], b = labels[j];
          if (a.x1 < b.x2 && b.x1 < a.x2 && a.y1 < b.y2 && b.y1 < a.y2) overlaps++;
        }
      return {
        zoom,
        labelPx: nodes.map((n) => parseFloat(n.style("font-size")) * zoom),
        nodePx: nodes.map((n) => n.renderedWidth()),
        overlaps,
      };
    });
    expect(m.zoom).toBeLessThanOrEqual(1.1 + 1e-6);
    for (const px of m.labelPx) {
      expect(px).toBeGreaterThanOrEqual(9);
      expect(px).toBeLessThanOrEqual(15);
    }
    expect(Math.max(...m.nodePx)).toBeLessThanOrEqual(48);
    expect(m.overlaps).toBe(0);
  });

  test("screenshots: light and dark", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockApi(page, graphMocks());
    for (const theme of ["light", "dark"] as const) {
      await setTheme(page, theme);
      await page.goto(SCN2A_EARLY);
      await expect(page.getByTestId("node-graph").locator("canvas").first()).toBeVisible({ timeout: 30_000 });
      await page.waitForTimeout(600);
      await shot(page, `node-${theme}-desktop`);
      await page.goto(SCN2A_LATE);
      await page.getByRole("button", { name: "Sources for Seizure" }).click();
      await expect(page.getByTestId("evidence-list")).toBeVisible();
      await page.waitForTimeout(400);
      await shot(page, `node-edge-${theme}-desktop`);
    }
    await signInAs(page, "researcher");
    await page.goto(SCN2A_EARLY);
    await expect(page.getByTestId("node-graph").locator("canvas").first()).toBeVisible({ timeout: 30_000 });
    await page.waitForTimeout(800);
    await shot(page, "node-researcher-dark-desktop");
  });
});

test("node view on a phone @mobile", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockApi(page, graphMocks());
  const errors = trackConsoleErrors(page);
  await page.goto(DRAVET);
  await expect(page.getByTestId("node-graph").locator("canvas").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(600);
  await shot(page, "node-mobile");
  await shot(page, "node-mobile-full", { fullPage: true });
  expect(errors()).toEqual([]);
});
