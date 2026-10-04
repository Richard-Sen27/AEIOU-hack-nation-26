import { expect, test, type Page } from "@playwright/test";

import { mockApi, setTheme, trackConsoleErrors } from "../helpers";
import { graphMocks } from "./fixtures";

/**
 * The Clusters page and a cluster's own page at the wide data set's shape
 * (2026-10-04.24: 148 groups of two or more, 24 of them on the map, and 77
 * single-disease clusters).
 */

type Cluster = {
  id: string;
  label: string;
  mechanism_summary: string;
  member_count: number;
  focus_member_count: number;
  on_map: boolean;
  attrs: Record<string, unknown>;
  origin: "inferred";
};

function cluster(n: number, members: number, focus: number, label = `Group ${n} disorders · GENE${n}`): Cluster {
  return {
    id: `CLUSTER:${n}`,
    label,
    mechanism_summary: members > 1 ? `Shared loss of function in pathway ${n}, with seizures and delay.` : "Mostly loss of function (1 of 1 gene-disease pairs with a known mechanism)",
    member_count: members,
    focus_member_count: focus,
    on_map: focus > 0,
    attrs: { top_genes: [`GENE${n}`] },
    origin: "inferred",
  };
}

/** API order: on the map first, then by size, then by number. */
function wideClusters(): Cluster[] {
  const out: Cluster[] = [];
  for (let n = 1; n <= 148; n++) {
    const members = n === 1 ? 185 : n === 10 ? 98 : 2 + ((n * 37) % 60);
    const focus = n === 10 ? 12 : n <= 24 && n !== 1 ? 1 + (n % 5) : 0;
    out.push(cluster(n, members, focus, n === 10 ? "Epileptic encephalopathies · SCN1A" : undefined));
  }
  for (let n = 149; n <= 225; n++) out.push(cluster(n, 1, 0, `cataract ${n} with adult phenotype`));
  // Shuffle a little: the page orders them itself as well.
  return out.reverse();
}

const SHOT_DIR = process.env.SHOT_DIR ?? "test-results";

async function openClusters(page: Page) {
  await mockApi(page, graphMocks({ "GET /clusters": wideClusters() }));
  await page.goto("/clusters");
  await expect(page.getByTestId("cluster-card").first()).toBeVisible();
}

test.describe("clusters page on the wide data set", () => {
  test("groups of two or more by default, on the map first, then by size", async ({ page }) => {
    const errors = trackConsoleErrors(page);
    await openClusters(page);
    const cards = page.getByTestId("cluster-card");
    await expect(cards).toHaveCount(148);
    await expect(page.getByTestId("clusters-count")).toHaveText("148 of 148 groups");
    // 24 on the map first (largest first), then the rest by size.
    const ids = await cards.locator("span.font-mono").allTextContents();
    expect(ids[0]).toBe("CLUSTER:10");
    const onMap = new Set(wideClusters().filter((c) => c.on_map).map((c) => c.id));
    expect(ids.slice(0, 23).every((id) => onMap.has(id))).toBe(true);
    expect(ids[23]).toBe("CLUSTER:1"); // the biggest one has no focus disease
    expect(ids.slice(23).every((id) => !onMap.has(id))).toBe(true);
    await expect(page.getByTestId("cluster-single")).toHaveCount(0);
    expect(errors()).toEqual([]);
  });

  test("Map only where the cluster is on the map", async ({ page }) => {
    await openClusters(page);
    await expect(page.getByTestId("cluster-map-link")).toHaveCount(23);
    const focus = page.getByTestId("cluster-card").first();
    await expect(focus).toContainText("98 members · 12 on the map");
    await expect(focus.getByTestId("cluster-map-link")).toHaveAttribute("href", "/atlas?focus=CLUSTER%3A10");
    const big = page.getByTestId("cluster-card").filter({ has: page.getByText("CLUSTER:1", { exact: true }) });
    await expect(big.getByTestId("cluster-map-link")).toHaveCount(0);
    await expect(big.getByRole("link", { name: /Group 1 disorders/ })).toHaveAttribute("href", "/node/CLUSTER%3A1");
  });

  test("single-disease clusters wait behind a toggle", async ({ page }) => {
    await openClusters(page);
    const toggle = page.getByTestId("clusters-singles-toggle");
    await expect(toggle).toHaveText("Show 77 single-disease groups");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await toggle.click();
    await expect(toggle).toHaveText("Hide 77 single-disease groups");
    const singles = page.getByTestId("cluster-single");
    await expect(singles).toHaveCount(77);
    await expect(singles.first().getByRole("link")).toHaveAttribute("href", /\/node\/CLUSTER%3A\d+$/);
    await toggle.click();
    await expect(singles).toHaveCount(0);
  });

  test("the filter works across groups and single-disease clusters", async ({ page }) => {
    await openClusters(page);
    const filter = page.getByPlaceholder("Filter by name, gene or mechanism");
    await filter.fill("SCN1A");
    await expect(page.getByTestId("cluster-card")).toHaveCount(1);
    await expect(page.getByTestId("clusters-count")).toHaveText("1 of 148 groups");
    await expect(page.getByTestId("clusters-singles-toggle")).toHaveCount(0);
    await filter.fill("cataract 15");
    await expect(page.getByTestId("cluster-card")).toHaveCount(0);
    await expect(page.getByText("No group matches.")).toBeVisible();
    const toggle = page.getByTestId("clusters-singles-toggle");
    await expect(toggle).toHaveText("Show 10 single-disease groups"); // cataract 150 … 159
    await toggle.click();
    await expect(page.getByTestId("cluster-single")).toHaveCount(10);
  });

  for (const theme of ["light", "dark"] as const) {
    for (const width of [1440, 390]) {
      test(`screenshots ${theme} ${width}`, async ({ page }) => {
        await page.emulateMedia({ reducedMotion: "reduce" });
        await page.setViewportSize({ width, height: 900 });
        await setTheme(page, theme);
        await openClusters(page);
        await page.screenshot({ path: `${SHOT_DIR}/clusters-wide-${theme}-${width}-default.png`, animations: "disabled" });
        await page.getByTestId("clusters-singles-toggle").click();
        await page.getByTestId("clusters-singles").scrollIntoViewIfNeeded();
        await page.getByTestId("clusters-singles-toggle").scrollIntoViewIfNeeded();
        await page.screenshot({ path: `${SHOT_DIR}/clusters-wide-${theme}-${width}-singles.png`, animations: "disabled" });
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        expect(overflow).toBeLessThanOrEqual(0);
      });
    }
  }
});

// --- a cluster's own page ----------------------------------------------------------------

const HINTS = { start_layout: "ring", label_style: "plain", highlight_family: ["symptoms", "community"], highlight_node_types: ["disease"], show_ids: false };

function apiNode(id: string, type: string, label: string, clusterId: string | null = null) {
  return { id, type, label, description: null, url: null, attrs: {}, cluster_id: clusterId, x: 0, y: 0, centrality: 0.1 };
}

/** A cluster's page as the fixed API serves it: the member diseases, linked among themselves. */
function clusterMocks(c: Cluster) {
  const center = { ...apiNode(c.id, "cluster", c.label, c.id), description: c.mechanism_summary };
  const members = Array.from({ length: c.member_count }, (_, i) => apiNode(`MONDO:${8100000 + i}`, "disease", `${c.label.split(" · ")[0]} type ${i + 1}`, c.id));
  const edges = members.slice(1).map((m, i) => ({
    id: `e_${c.id}_${i}`,
    source_id: members[i].id,
    target_id: m.id,
    relation: "similar_symptoms",
    family: "symptoms",
    confidence: 0.6,
    confidence_level: "medium",
    origin: "inferred",
    status: "active",
    features: {},
    data_version: "wide",
    evidence_count: 1,
    contradiction_count: 0,
    flagged: false,
  }));
  const summary =
    c.member_count > 1
      ? `${c.mechanism_summary} Groups ${c.member_count} conditions by shared mechanism or symptoms.`
      : `${c.mechanism_summary} Holds a single condition, so it is not a group.`;
  const detail = { node: center, synonyms: [], summary, relation_counts: [], degree: 0, cluster: c, classification: null, vus_notice: null };
  const hood = { center, nodes: [center, ...members], edges, cluster: c, hints: HINTS, data_version: "wide" };
  const isCenter = (url: string) => decodeURIComponent(new URL(url).pathname.split("/").pop()!) === c.id;
  const notFound = { status: 404, json: { error: { code: "not_found", message: "Not found" } } };
  return graphMocks({
    "GET /clusters": wideClusters(),
    "GET /node/*": ({ url }: { url: string }) => (isCenter(url) ? { json: detail } : notFound),
    "GET /neighborhood/*": ({ url }: { url: string }) => (isCenter(url) ? { json: hood } : notFound),
  });
}

test.describe("a cluster's own page on the wide data set", () => {
  const all = wideClusters();
  const cases = [
    { name: "a big cluster off the map", c: all.find((c) => c.id === "CLUSTER:1")! },
    { name: "a focus cluster", c: all.find((c) => c.id === "CLUSTER:10")! },
    { name: "a single-disease cluster", c: all.find((c) => c.id === "CLUSTER:149")! },
  ];
  for (const { name, c } of cases) {
    test(name, async ({ page }) => {
      const errors = trackConsoleErrors(page);
      await mockApi(page, clusterMocks(c));
      await page.goto(`/node/${encodeURIComponent(c.id)}`);
      await expect(page.getByRole("heading", { level: 1, name: c.label })).toBeVisible();
      await expect(page.getByTestId("node-counts")).toContainText(`${c.member_count + 1} items`);
      await expect(page.getByTestId("node-truncated")).toHaveCount(0);
      await expect(page.getByTestId("open-in-atlas")).toHaveCount(c.on_map ? 1 : 0);
      await page.getByRole("radio", { name: "List" }).click();
      // The list holds connections; a cluster of one has none (its member is listed beside it).
      await expect(page.getByTestId("node-list")).toContainText(
        c.member_count > 1 ? `${c.label.split(" · ")[0]} type 1` : "No connections in this view.",
      );
      await page.getByRole("radio", { name: "Graph" }).click();
      await page.screenshot({ path: `${SHOT_DIR}/cluster-page-${c.id.replace(":", "-")}.png`, animations: "disabled" });
      expect(errors()).toEqual([]);
    });
  }
});
