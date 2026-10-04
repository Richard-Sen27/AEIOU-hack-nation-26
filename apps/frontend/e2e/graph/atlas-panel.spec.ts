import { expect, test, type Page } from "@playwright/test";

import { errorEnvelope, guestSession, mockApi, setTheme, signedInSession, sseBody, trackConsoleErrors } from "../helpers";
import { atlasTreePayload, CORE, explainEvents, GENE_GROUP, stxbp1Summary, summaryMock, wideMocks } from "./fixtures";

type Req = { url: string; method: string; body: unknown };

async function atlas(page: Page, mocks: Record<string, unknown> = {}, session: unknown = guestSession) {
  await mockApi(page, {
    "GET /auth/session": session,
    "GET /atlas/tree.json": atlasTreePayload(),
    "GET /atlas/summary/*": summaryMock(),
    "GET /chat/sessions": [],
    ...mocks,
  });
}

const panel = (page: Page) => page.getByTestId("atlas-panel");

test.describe("atlas summary panel", () => {
  test("shows the sections of a focused entity with trust and actions", async ({ page }) => {
    await atlas(page);
    const errors = trackConsoleErrors(page);
    await page.goto("/atlas?focus=MONDO:9900007");
    const p = panel(page);
    await expect(p.getByRole("heading", { name: "STXBP1 encephalopathy" })).toBeVisible();
    await expect(p.getByTestId("atlas-panel-id-link")).toHaveText([/MONDO:9900007/]);
    await expect(p.getByTestId("atlas-summary-headline")).toContainText("Linked to 2 genes");

    // Breadcrumb from the tree: category and the cluster above it.
    await expect(p.getByTestId("atlas-crumb")).toHaveText(["Conditions", "Synaptic and potassium channel encephalopathies"]);

    const sections = p.getByTestId("atlas-summary-section");
    await expect(sections).toHaveCount(5);
    await expect(sections.getByRole("heading")).toHaveText([
      /Mechanism group\s*1/,
      /Similar conditions\s*14/,
      /Same gene\s*1/,
      /Genes\s*1/,
      /Leading researchers\s*2/,
    ]);
    await expect(p.locator('[data-section="similar_diseases"]')).toContainText("Top 2 of 14");

    // Data vs hypothesis and the review flag on items.
    const similar = p.locator('[data-section="similar_diseases"] [data-testid="atlas-summary-item"]').first();
    await expect(similar.getByTestId("origin-badge")).toHaveText("Hypothesis");
    await expect(similar.getByTestId("status-flag")).toHaveText("Under review");
    await expect(similar.getByTestId("confidence-badge")).toBeVisible();
    const gene = p.locator('[data-section="genes"] [data-testid="atlas-summary-item"]').first();
    await expect(gene.getByTestId("origin-badge")).toHaveText("Data");
    await expect(p.locator('[data-section="researchers"]')).toContainText("via 4 papers");
    await expect(p.locator('[data-section="researchers"]').getByRole("link", { name: "About this data" })).toHaveAttribute("href", "/about-data");

    // Cluster membership: via label, no confidence, no chain action.
    const member = p.locator('[data-section="clusters"] [data-testid="atlas-summary-item"]');
    await expect(member).toHaveAttribute("data-membership", "true");
    await expect(member).toContainText("Member by analysis (hypothesis)");
    await expect(member.getByTestId("confidence-badge")).toHaveCount(0);
    await expect(member.getByTestId("atlas-summary-chain")).toHaveCount(0);

    await expect(p.getByTestId("atlas-open-node")).toHaveAttribute("href", "/node/MONDO%3A9900007");

    // A chain button is there for real links; clicking an item selects it.
    await gene.getByTestId("atlas-summary-chain").click();
    await gene.getByRole("button", { name: /STXBP1/ }).first().click();
    await expect(p.getByRole("heading", { name: "STXBP1", exact: true })).toBeVisible();
    await expect(page).toHaveURL(/focus=HGNC%3A11444|focus=HGNC:11444/);
    expect(errors()).toEqual([]);
  });

  test("a focus disease: gene sources, the shared-gene section and computed links dashed", async ({ page }) => {
    await atlas(page);
    await page.goto("/atlas?focus=MONDO:9900007");
    const p = panel(page);
    await expect(p.locator('[data-section="genes"] [data-testid="atlas-summary-detail"]')).toHaveText("ClinVar · Orphanet");
    await expect(p.getByTestId("atlas-panel-id-link")).toHaveAttribute("href", "https://purl.obolibrary.org/obo/MONDO_9900007");

    const shared = p.locator('[data-section="shared_gene_diseases"] [data-testid="atlas-summary-item"]');
    await expect(shared).toHaveCount(1);
    await expect(shared).toHaveAttribute("data-computed", "true");
    await expect(shared).toHaveClass(/border-dashed/);
    await expect(shared.getByTestId("atlas-summary-via")).toHaveText("gene STXBP1");
    await expect(shared.getByTestId("origin-badge")).toHaveText("Hypothesis");
    await expect(shared.getByTestId("confidence-badge")).toBeVisible();
    await expect(shared.getByTestId("atlas-summary-explanation")).toContainText("A hypothesis, not an established fact.");
    // Not on the map: nothing to draw.
    await expect(shared.getByTestId("atlas-summary-chain")).toHaveCount(0);

    // Computed links never read as a fact ("Direct"); data links stay solid.
    const similar = p.locator('[data-section="similar_diseases"] [data-testid="atlas-summary-item"]');
    await expect(similar.getByTestId("atlas-summary-via")).toHaveText(["Computed link", "Computed link"]);
    await expect(similar.first()).toHaveClass(/border-dashed/);
    const gene = p.locator('[data-section="genes"] [data-testid="atlas-summary-item"]');
    await expect(gene).not.toHaveClass(/border-dashed/);
    // Its sources say where the link comes from; a bare "Direct" is left out.
    await expect(gene.getByTestId("atlas-summary-via")).toHaveCount(0);
  });

  test("a core-only disease: symptoms by frequency, gene sources, same gene, coverage", async ({ page }) => {
    const requested: string[] = [];
    await mockApi(page, {
      ...wideMocks(),
      "GET /chat/sessions": [],
      "GET /neighborhood/*": (req: Req) => {
        requested.push(req.url);
        return { json: {} };
      },
    });
    await page.goto(`/atlas?focus=${encodeURIComponent(CORE.fop)}`);
    const p = panel(page);
    await expect(p.getByRole("heading", { level: 2 })).toHaveText("fibrodysplasia ossificans progressiva");
    await expect(p.getByTestId("atlas-panel-id-link")).toHaveText([/MONDO:0007606/, /ORPHA:337/, /OMIM:135100/]);
    await expect(p.getByTestId("atlas-coverage")).toContainText("this one isn't one of them yet.");

    await expect(p.getByTestId("atlas-summary-section").getByRole("heading")).toHaveText([
      /Similar conditions\s*2/,
      /Same gene\s*1/,
      /Genes\s*1/,
      /Symptoms\s*52/,
    ]);
    const symptoms = p.locator('[data-section="symptoms"] [data-testid="atlas-summary-item"]');
    await expect(symptoms.getByTestId("atlas-summary-detail")).toHaveText(["Very frequent", "Frequent", "Occasional"]);
    await expect(symptoms.first()).toContainText("Ectopic ossification in muscle tissue");
    // The label as the source gives it, never an invented percentage.
    await expect(p.locator('[data-section="symptoms"]')).not.toContainText("%");
    await expect(p.locator('[data-section="genes"] [data-testid="atlas-summary-detail"]')).toHaveText("Orphanet · HPO");

    const shared = p.locator('[data-section="shared_gene_diseases"] [data-testid="atlas-summary-item"]');
    await expect(shared).toContainText("ACVR1-related fixture condition");
    await expect(shared).toHaveClass(/border-dashed/);
    await expect(shared.getByTestId("atlas-summary-via")).toHaveText("gene ACVR1");
    await expect(shared.getByTestId("atlas-summary-explanation")).toContainText("not established");
    // Frequencies and sources come with the summary: no extra requests.
    expect(requested).toEqual([]);
  });

  test("nothing selected renders no panel", async ({ page }) => {
    await atlas(page);
    await page.goto("/atlas");
    await expect(page.getByTestId("atlas-view")).toBeVisible();
    await expect(page.getByTestId("atlas-wu-dock")).toBeVisible();
    await expect(panel(page)).toHaveCount(0);
  });

  test("a long headline is clamped with a toggle", async ({ page }) => {
    const long = { ...stxbp1Summary(), headline: "A long description of the condition. ".repeat(12) };
    await atlas(page, { "GET /atlas/summary/*": summaryMock({ "MONDO:9900007": { json: long } }) });
    await page.goto("/atlas?focus=MONDO:9900007");
    const headline = panel(page).getByTestId("atlas-summary-headline");
    await expect(headline).toHaveClass(/line-clamp-3/);
    await panel(page).getByTestId("atlas-summary-more").click();
    await expect(headline).not.toHaveClass(/line-clamp-3/);
    await expect(panel(page).getByTestId("atlas-summary-more")).toHaveText("Less");
  });

  test("a crumb selects its group, which renders a local panel", async ({ page }) => {
    const requested: string[] = [];
    await atlas(page, {
      "GET /atlas/summary/*": (req: Req) => {
        requested.push(decodeURIComponent(new URL(req.url).pathname));
        return summaryMock()(req);
      },
    });
    await page.goto("/atlas?focus=HGNC:11444");
    await expect(panel(page).getByRole("heading", { name: "STXBP1", exact: true })).toBeVisible();
    await panel(page).getByTestId("atlas-crumb").filter({ hasText: "Chromosome 2" }).click();

    const p = panel(page);
    await expect(p.getByTestId("atlas-group-panel")).toBeVisible();
    await expect(p.getByRole("heading", { name: "Chromosome 2" })).toBeVisible();
    await expect(p.getByTestId("atlas-group-basis")).toContainText("Genes on chromosome 2");
    await expect(p.getByTestId("atlas-group-counts")).toContainText("6");
    await expect(p.getByTestId("atlas-group-child")).toHaveCount(6);
    // Groups never call the summary endpoint.
    expect(requested.some((r) => r.includes("T:"))).toBe(false);

    await p.getByTestId("atlas-group-child").filter({ hasText: "SCN1A" }).click();
    await expect(panel(page).getByRole("heading", { name: "SCN1A", exact: true })).toBeVisible();
  });

  test("institution groups explain the name keyword rule", async ({ page }) => {
    const tree = atlasTreePayload();
    tree.nodes.push({
      id: "T:institutions/clinical", kind: "group", label: "Clinical", parent_id: "T:institutions", category: "institutions",
      depth: 2, x: 10, y: 10, angle: 0, entity_type: null, group_basis: "institution_kind", ref_id: "clinical",
      entity_count: 0, child_count: 0, cluster_id: null, centrality: null, contributed: false,
    });
    await atlas(page, { "GET /atlas/tree.json": tree });
    await page.goto("/atlas?focus=T:institutions/clinical");
    await expect(panel(page).getByTestId("atlas-group-basis")).toContainText("keywords in the name");
  });

  test("not found and error states", async ({ page }) => {
    let fail = true;
    await atlas(page, {
      "GET /atlas/summary/*": (req: Req) => {
        const id = decodeURIComponent(new URL(req.url).pathname.split("/").pop()!);
        if (id === "HGNC:10585") return errorEnvelope(404, "not_found");
        if (fail) return errorEnvelope(500, "internal_error");
        return summaryMock()(req);
      },
    });
    await page.goto("/atlas?focus=MONDO:9900007");
    await expect(panel(page).getByTestId("atlas-summary-error")).toBeVisible();
    fail = false;
    await panel(page).getByRole("button", { name: "Retry" }).click();
    await expect(panel(page).getByTestId("atlas-summary-section").first()).toBeVisible();

    await page.goto("/atlas?focus=HGNC:10585");
    await expect(panel(page).getByTestId("atlas-summary-not-found")).toBeVisible();
    await expect(panel(page).getByTestId("atlas-open-node")).toHaveCount(0);
  });

  test("write a summary as a guest shows cached text", async ({ page }) => {
    const bodies: unknown[] = [];
    await atlas(page, {
      "POST /explain": (req: Req) => {
        bodies.push(req.body);
        return sseBody(explainEvents("STXBP1 encephalopathy is caused by changes in STXBP1 [e_e5f778ac8a21].", true));
      },
    });
    await page.goto("/atlas?focus=MONDO:9900007");
    await panel(page).getByTestId("atlas-summary-write").click();
    const written = panel(page).getByTestId("atlas-summary-written");
    await expect(written.getByTestId("atlas-summary-text")).toContainText("caused by changes in STXBP1");
    await expect(written.getByTestId("citation")).toHaveText("1");
    await expect(written.getByTestId("atlas-summary-cached")).toBeVisible();
    await expect(written.getByText("AI-generated · Dr. Wu")).toBeVisible();
    expect(bodies[0]).toEqual({
      edge_ids: ["e_e5f778ac8a21", "e_3b8845b635b8"],
      subject_node_id: "MONDO:9900007",
      role: expect.any(String),
      language: "en",
      steps: true,
    });
  });

  test("write a summary as a guest without cached text asks to sign in", async ({ page }) => {
    await atlas(page, { "POST /explain": errorEnvelope(401, "sign_in_required") });
    await page.goto("/atlas?focus=MONDO:9900007");
    await panel(page).getByTestId("atlas-summary-write").click();
    const prompt = panel(page).getByTestId("atlas-summary-sign-in");
    await expect(prompt).toBeVisible();
    await prompt.getByRole("button", { name: /Sign in/ }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
  });

  test("write a summary signed in generates fresh text", async ({ page }) => {
    await atlas(
      page,
      { "POST /explain": sseBody(explainEvents("A fresh summary of how it is connected [e_3b8845b635b8].", false)) },
      signedInSession({ consents: ["health_data"], language: "de" }),
    );
    await page.goto("/atlas?focus=MONDO:9900007");
    await panel(page).getByTestId("atlas-summary-write").click();
    const written = panel(page).getByTestId("atlas-summary-written");
    await expect(written.getByTestId("atlas-summary-fresh")).toBeVisible();
    await expect(written.getByTestId("atlas-summary-text")).toHaveAttribute("lang", "de");
    await expect(written.getByTestId("citation")).toHaveText("2");
  });

  for (const theme of ["light", "dark"] as const) {
    test(`screenshot panel ${theme}`, async ({ page }, info) => {
      await setTheme(page, theme);
      await atlas(page, { "POST /explain": sseBody(explainEvents("STXBP1 encephalopathy is caused by changes in STXBP1 [e_e5f778ac8a21].", true)) });
      await page.goto("/atlas?focus=MONDO:9900007");
      await panel(page).getByTestId("atlas-summary-write").click();
      await expect(panel(page).getByTestId("atlas-summary-cached")).toBeVisible();
      await page.screenshot({ path: info.outputPath(`atlas-panel-${theme}.png`) });
    });
  }

  // Panel details for a focus and a core-only disease; written only when SHOT_DIR is set.
  for (const [kind, id] of [
    ["focus", "MONDO:9900007"],
    ["core", CORE.fop],
  ] as const) {
    for (const theme of ["light", "dark"] as const) {
      for (const width of [1440, 390]) {
        test(`screenshot panel details ${kind} ${theme} ${width}`, async ({ page }) => {
          test.skip(!process.env.SHOT_DIR, "SHOT_DIR not set");
          await page.setViewportSize({ width, height: width > 600 ? 900 : 844 });
          await setTheme(page, theme);
          await mockApi(page, { ...wideMocks(), "GET /chat/sessions": [] });
          await page.goto(`/atlas?focus=${encodeURIComponent(id)}`);
          await expect(panel(page).getByTestId("atlas-summary-section").first()).toBeVisible();
          await page.waitForTimeout(500);
          await page.screenshot({ path: `${process.env.SHOT_DIR}/panel-details-${kind}-${theme}-${width}.png`, animations: "disabled" });
          // The panel body scrolls as one region: a second shot of its lower sections.
          await panel(page).getByTestId("atlas-panel-body").evaluate((el) => el.scrollTo(0, el.scrollHeight));
          await page.waitForTimeout(200);
          await page.screenshot({ path: `${process.env.SHOT_DIR}/panel-details-${kind}-${theme}-${width}-end.png`, animations: "disabled" });
        });
      }
    }
  }

  test("group panel for a known group id @mobile", async ({ page }) => {
    await atlas(page);
    await page.goto(`/atlas?focus=${encodeURIComponent(GENE_GROUP)}`);
    await expect(panel(page).getByTestId("atlas-group-panel")).toBeVisible();
    await expect(panel(page).getByTestId("atlas-group-child").first()).toBeVisible();
  });
});
