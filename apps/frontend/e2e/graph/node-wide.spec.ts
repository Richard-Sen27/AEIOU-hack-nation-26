import { expect, test } from "@playwright/test";

import { mockApi, signedInSession, trackConsoleErrors } from "../helpers";
import { clusters, graphMocks, neighborhood, nodeDetail } from "./fixtures";

// Attributes as the wide data set (2026-10-04.24) carries them on clusters and diseases.
const CLUSTER_ATTRS = {
  members: ["MONDO:9900003", "MONDO:9900006", "MONDO:0000001"],
  lineage: [{ id: "HP:0000707", label: "Abnormality of the nervous system" }],
  inferred: true,
  top_genes: ["SCN8A", "SCN2A"],
  mechanisms: { gain_of_function: 3 },
  model_label: "Sodium channel gain-of-function epilepsies",
  label_origin: "llm",
  top_phenotypes: ["Seizure"],
  top_pathways: [],
  distinctive_phenotypes: ["Seizure"],
};
const DISEASE_ATTRS = {
  rare: true,
  tier: "focus",
  xrefs: ["DOID:0050709", "GARD:0006309"],
  exact_matches: ["OMIM:607208"],
  orphanet_prevalence: [
    { type: "Point prevalence", class: "1-9 / 100 000", source: "PMID:1", geographic: "Europe" },
    { type: "Annual incidence", class: "1-9 / 100 000", source: "PMID:2", geographic: "Worldwide" },
  ],
};

function withAttrs(id: string, attrs: Record<string, unknown>) {
  const lastSegment = (url: string) => decodeURIComponent(new URL(url).pathname.split("/").pop()!);
  const base = graphMocks();
  return graphMocks({
    "GET /node/*": ({ url }: { url: string }) => {
      if (lastSegment(url) !== id) return (base["GET /node/*"] as (r: { url: string }) => unknown)({ url });
      const d = nodeDetail(id)!;
      return { json: { ...d, node: { ...d.node, attrs } } };
    },
    "GET /neighborhood/*": ({ url }: { url: string }) => {
      if (lastSegment(url) !== id) return (base["GET /neighborhood/*"] as (r: { url: string }) => unknown)({ url });
      const h = neighborhood(id)!;
      return { json: { ...h, center: { ...h.center, attrs } } };
    },
  });
}

test.describe("node view on the wide data set", () => {
  test("a cluster lists only its members and hides its structural attributes", async ({ page }) => {
    await mockApi(page, withAttrs("CLUSTER:1", CLUSTER_ATTRS));
    const errors = trackConsoleErrors(page);
    await page.goto("/node/CLUSTER%3A1");
    const members = page.getByTestId("cluster-members");
    await expect(members.getByRole("heading")).toHaveText("Members · 3");
    await expect(members).toContainText("SCN8A developmental");
    // In the neighbourhood, but not a member.
    await expect(members).not.toContainText("Familial hemiplegic migraine");
    await expect(page.getByTestId("cluster-members-more")).toContainText("1 more in the Atlas summary");
    const attrs = page.getByTestId("node-attrs");
    await expect(attrs).toContainText("Main genes");
    await expect(attrs).toContainText("SCN8A, SCN2A");
    for (const hidden of ["lineage", "members", "mechanisms", "label origin", "model label", "MONDO:0000001", "Main pathways"]) {
      await expect(attrs).not.toContainText(hidden);
    }
    expect(errors()).toEqual([]);
  });

  test("a disease shows its prevalence classes, not id lists or raw records", async ({ page }) => {
    await mockApi(page, withAttrs("MONDO:0100135", DISEASE_ATTRS));
    await page.goto("/node/MONDO%3A0100135");
    const attrs = page.getByTestId("node-attrs");
    await expect(attrs).toContainText("Prevalence");
    await expect(attrs).toContainText("1-9 / 100 000");
    for (const hidden of ["xrefs", "exact matches", "tier", "geographic", "PMID:1"]) {
      await expect(attrs).not.toContainText(hidden);
    }
  });
});

test("cluster cards show the lead genes of the wide data set", async ({ page }) => {
  const wide = clusters.map((c) => ({ ...c, attrs: { top_genes: ["KIF1A", "ERLIN2"], top_pathways: ["RND1 GTPase cycle"] } }));
  await mockApi(page, graphMocks({ "GET /clusters": wide, "GET /auth/session": signedInSession({ role: "researcher" }) }));
  await page.goto("/clusters");
  const first = page.getByTestId("cluster-card").first();
  await expect(first).toContainText("KIF1A");
  await expect(first).toContainText("RND1 GTPase cycle");
});
