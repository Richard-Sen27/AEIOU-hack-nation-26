import { expect, test } from "@playwright/test";

import { errorEnvelope, guestSession, hit, mockApi, setTheme, shot, signedInSession, trackConsoleErrors } from "../helpers";
import { consentRecord, expectNoHealthDataInBrowser } from "./fixtures";

const PROFILE = {
  diseases: [{ id: "MONDO:0100135", label: "STXBP1 encephalopathy", source: "chat", confirmed_at: "2026-10-01T10:00:00Z" }],
  genes: [{ id: "HGNC:11444", label: "STXBP1", source: "document", finding_id: "f1" }],
  variants: [
    {
      source: "document",
      finding_id: "f2",
      hgvs: "NM_003165.6:c.1631G>A",
      gene_id: "HGNC:11444",
      zygosity: "heterozygous",
      classification: "uncertain_significance",
      test_date: "2026-08-12",
    },
  ],
  phenotypes: [
    { id: "HP:0001250", label: "Seizure", source: "chat", excluded: false },
    { id: "HP:0011968", label: "Feeding difficulties", source: "chat", excluded: true },
  ],
  age_years: 2,
  updated_at: "2026-10-02T09:00:00Z",
};

function baseMocks(extra: Record<string, unknown> = {}) {
  return {
    "GET /auth/session": signedInSession({ consents: ["health_data"] }),
    "GET /profile": PROFILE,
    "GET /consents": [consentRecord("health_data"), consentRecord("contribute", { id: "old", active: false, revoked_at: "2026-10-02T10:00:00Z", granted_at: "2026-09-20T10:00:00Z" })],
    "GET /contributions": [],
    "GET /search": (req: { url: string }) => {
      const q = new URL(req.url).searchParams.get("q") ?? "";
      if (/dravet/i.test(q)) return { json: { results: [hit("MONDO:0100310", "disease", "Dravet syndrome")] } };
      if (/ataxia/i.test(q)) return { json: { results: [hit("HP:0001251", "phenotype", "Ataxia")] } };
      return { json: { results: [] } };
    },
    ...extra,
  };
}

test("profile: shows sources, edits, adds and removes items, saves with updated_at", async ({ page }) => {
  let put: Record<string, unknown> | null = null;
  await mockApi(
    page,
    baseMocks({
      "PUT /profile": (req: { body: unknown }) => {
        put = req.body as Record<string, unknown>;
        return { json: { ...put, updated_at: "2026-10-04T12:00:00Z" } };
      },
    }),
  );
  const errors = trackConsoleErrors(page);
  await page.goto("/profile");
  const editor = page.getByTestId("profile-editor");
  await expect(editor.getByTestId("profile-disease")).toContainText("STXBP1 encephalopathy");
  await expect(editor.getByTestId("profile-disease").getByTestId("source-badge")).toHaveText("From chat");
  await expect(editor.getByTestId("profile-gene").getByTestId("source-badge")).toHaveText("From a document");
  await expect(editor.getByTestId("profile-variant").getByTestId("vus-notice")).toBeVisible();
  await expect(editor.getByRole("list", { name: "Not present" })).toContainText("Feeding difficulties");

  // No identifying fields.
  for (const label of [/name/i, /birth/i, /address/i, /patient id/i]) {
    await expect(editor.getByRole("textbox", { name: label })).toHaveCount(0);
  }

  // Add a diagnosis via search.
  await page.getByTestId("picker-disease").getByRole("combobox").fill("Dravet");
  await page.getByRole("option", { name: /Dravet syndrome/ }).click();
  await expect(editor.getByTestId("profile-disease")).toHaveCount(2);

  // Add an excluded symptom.
  await editor.getByRole("radio", { name: "Add as not present" }).or(editor.getByRole("button", { name: "Add as not present" })).click();
  await page.getByTestId("picker-phenotype").getByRole("combobox").fill("ataxia");
  await page.getByRole("option", { name: /Ataxia/ }).click();
  await expect(editor.getByRole("list", { name: "Not present" })).toContainText("Ataxia");

  // Remove the gene, correct the variant classification.
  await editor.getByRole("button", { name: "Remove STXBP1", exact: true }).click();
  await editor.getByTestId("profile-variant").getByLabel("Classification").selectOption("likely_pathogenic");
  await expect(editor.getByTestId("profile-variant").getByTestId("vus-notice")).toHaveCount(0);

  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Profile saved").first()).toBeVisible();
  expect(put).not.toBeNull();
  const body = put as unknown as typeof PROFILE;
  expect(body.updated_at).toBe("2026-10-02T09:00:00Z");
  expect(body.genes).toEqual([]);
  expect(body.diseases.map((d) => d.id)).toEqual(["MONDO:0100135", "MONDO:0100310"]);
  expect(body.diseases[1].source).toBe("manual");
  expect(body.phenotypes.find((p) => p.id === "HP:0001251")?.excluded).toBe(true);
  expect(body.variants[0].classification).toBe("likely_pathogenic");

  await expectNoHealthDataInBrowser(page, ["STXBP1", "Dravet", "Ataxia", "NM_003165", "Seizure"]);
  expect(errors()).toEqual([]);
});

test("profile: a 409 conflict reloads the latest version", async ({ page }) => {
  let gets = 0;
  await mockApi(
    page,
    baseMocks({
      "GET /profile": () => {
        gets += 1;
        return { json: gets === 1 ? PROFILE : { ...PROFILE, age_years: 3, updated_at: "2026-10-04T08:00:00Z" } };
      },
      "PUT /profile": { status: 409, json: { error: { code: "conflict", message: "Profile changed" } } },
    }),
  );
  await page.goto("/profile");
  await page.getByLabel("Age in years").fill("5");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Your profile changed elsewhere")).toBeVisible();
  await expect(page.getByLabel("Age in years")).toHaveValue("3");
});

test("profile: child profile needs parental responsibility before saving", async ({ page }) => {
  await mockApi(page, baseMocks({ "PUT /profile": (req: { body: unknown }) => ({ json: req.body }) }));
  await page.goto("/profile");
  await page.getByRole("checkbox", { name: /describes a child/ }).click();
  await expect(page.getByRole("button", { name: "Save changes" })).toBeDisabled();
  await page.getByRole("checkbox", { name: /parental responsibility/ }).click();
  await expect(page.getByRole("button", { name: "Save changes" })).toBeEnabled();
});

test("settings: role, language and expert mode save immediately", async ({ page }) => {
  const patches: unknown[] = [];
  await mockApi(
    page,
    baseMocks({
      "PATCH /me/settings": (req: { body: unknown }) => {
        patches.push(req.body);
        return { json: signedInSession().user };
      },
    }),
  );
  await page.goto("/profile");
  const settings = page.locator("#settings");
  await settings.getByRole("radio", { name: "Researcher" }).click();
  await settings.getByRole("combobox", { name: /^Language/ }).selectOption("fr");
  await settings.getByRole("switch").click();
  await expect.poll(() => patches.length).toBe(3);
  expect(patches).toEqual([{ role: "researcher" }, { language: "fr" }, { expert_mode: true }]);
});

test("settings: a role change sets the lens at once, without a reload", async ({ page }) => {
  let role = "patient";
  await mockApi(
    page,
    baseMocks({
      "GET /auth/session": () => ({ json: signedInSession({ role, consents: ["health_data"] }) }),
      "PATCH /me/settings": (req: { body: unknown }) => {
        role = (req.body as { role: string }).role;
        return { json: signedInSession({ role }).user };
      },
      "GET /clusters": [],
    }),
  );
  await page.goto("/profile");
  await page.evaluate(() => ((window as unknown as { __sameDocument: boolean }).__sameDocument = true));
  await page.locator("#settings").getByRole("radio", { name: "Researcher" }).click();
  await expect(page.getByText("Role saved")).toBeVisible();
  await page.getByRole("banner").getByRole("link", { name: "Clusters" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Mechanism clusters");
  expect(await page.evaluate(() => (window as unknown as { __sameDocument?: boolean }).__sameDocument)).toBe(true);
});

const LINKED = {
  node_id: "RES:0001",
  type: "researcher",
  label: "Maria Example",
  orcid_id: "0000-0002-1825-0097",
  institutions: [{ node_id: "INST:bch", label: "Boston Children's Hospital" }],
};
const WORK = {
  first_name: "Maria",
  last_name: "Example",
  institutions: [
    { node_id: "INST:bch", label: "Boston Children's Hospital" },
    { node_id: null, label: "St. Jude Research" },
  ],
  orcid_id: "0000-0002-1825-0097",
  atlas_node_id: "RES:0001",
  linked_entry: LINKED,
  linked_entry_missing: false,
  updated_at: "2026-10-03T09:00:00Z",
  suggested: { first_name: "Maria", last_name: "Example", source: "chatgpt" },
};

test("your work: shows the linked entry, edits, saves and removes", async ({ page }) => {
  let put: Record<string, unknown> | null = null;
  let deleted = false;
  const urls: string[] = [];
  page.on("request", (r) => urls.push(decodeURIComponent(r.url())));
  await mockApi(
    page,
    baseMocks({
      "GET /auth/session": signedInSession({ role: "researcher", consents: ["health_data"] }),
      "GET /me/professional": () => ({ json: deleted ? { ...WORK, first_name: null, last_name: null, institutions: [], orcid_id: null, atlas_node_id: null, linked_entry: null, updated_at: null } : WORK }),
      "PUT /me/professional": (req: { body: unknown }) => {
        put = req.body as Record<string, unknown>;
        return { json: { ...WORK, last_name: "Exampel", institutions: WORK.institutions.slice(0, 1), updated_at: "2026-10-04T12:00:00Z" } };
      },
      "DELETE /me/professional": () => {
        deleted = true;
        return { status: 204, body: "" };
      },
    }),
  );
  const errors = trackConsoleErrors(page);
  await page.goto("/profile");
  const panel = page.locator("#your-work");
  await expect(panel.getByRole("heading", { name: "Your work" })).toBeVisible();
  await expect(panel).toContainText("Private to you. Not a verification.");
  await expect(page.getByRole("navigation", { name: "Profile sections" }).getByRole("link", { name: "Your work" })).toBeAttached();
  await expect(page.getByTestId("role-switch-note")).toHaveText("Switching to Patient or family removes your work details.");

  const entry = panel.getByTestId("linked-entry");
  await expect(entry).toContainText("You said this is you");
  await expect(entry).toContainText("Maria Example");
  await expect(entry.getByRole("link", { name: "Your entry in the atlas" })).toHaveAttribute("href", "/node/RES%3A0001");
  await expect(entry.getByRole("link", { name: "Claim or correct it" })).toHaveAttribute("href", "/about-data?entry=RES%3A0001#claim");
  // Saved names are not labelled as a ChatGPT prefill.
  await expect(panel).not.toContainText("From your ChatGPT account");

  const save = panel.getByRole("button", { name: "Save", exact: true });
  await expect(save).toBeDisabled();
  await panel.getByRole("button", { name: "Remove St. Jude Research" }).click();
  await panel.getByRole("textbox", { name: "Last name" }).fill("Exampel");
  await save.click();
  await expect(page.getByText("Work details saved").first()).toBeVisible();
  expect(put).toEqual({
    first_name: "Maria",
    last_name: "Exampel",
    orcid_id: "0000-0002-1825-0097",
    institutions: [{ node_id: "INST:bch" }],
    atlas_node_id: "RES:0001",
  });

  await panel.getByTestId("remove-work-details").click();
  await expect.poll(() => deleted).toBe(true);
  await expect(panel.getByTestId("linked-entry")).toHaveCount(0);
  await expect(panel.getByRole("textbox", { name: "First name" })).toHaveValue("Maria");
  await expect(panel).toContainText("From your ChatGPT account. Edit as needed.");

  for (const name of ["Maria", "Example", "Exampel"]) {
    expect(urls.filter((u) => u.includes(name)), `URL contains ${name}`).toEqual([]);
  }
  expect(errors()).toEqual([]);
});

test("your work: unlink, and a 403 is explained", async ({ page }) => {
  let put: Record<string, unknown> | null = null;
  let forbidden = false;
  await mockApi(
    page,
    baseMocks({
      "GET /auth/session": signedInSession({ role: "doctor", consents: ["health_data"] }),
      "GET /me/professional": () => (forbidden ? errorEnvelope(403, "forbidden") : { json: WORK }),
      "PUT /me/professional": (req: { body: unknown }) => {
        put = req.body as Record<string, unknown>;
        return { json: { ...WORK, atlas_node_id: null, linked_entry: null } };
      },
    }),
  );
  await page.goto("/profile");
  const panel = page.locator("#your-work");
  await panel.getByTestId("linked-entry").getByRole("button", { name: "Unlink" }).click();
  await panel.getByRole("button", { name: "Save", exact: true }).click();
  await expect.poll(() => (put as { atlas_node_id?: unknown } | null)?.atlas_node_id).toBeNull();

  forbidden = true;
  await page.reload();
  await expect(panel.getByTestId("work-details-error")).toContainText("Work details are for doctors and researchers.");
});

test("your work: patients do not see it", async ({ page }) => {
  let fetched = false;
  await mockApi(
    page,
    baseMocks({
      "GET /me/professional": () => {
        fetched = true;
        return errorEnvelope(403, "forbidden");
      },
    }),
  );
  await page.goto("/profile");
  await expect(page.getByTestId("profile-disease")).toBeVisible();
  await expect(page.locator("#your-work")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Your work" })).toHaveCount(0);
  await expect(page.getByTestId("role-switch-note")).toHaveCount(0);
  expect(fetched).toBe(false);
});

test("consents: state, history and one-click withdraw", async ({ page }) => {
  let revoked = "";
  let session = signedInSession({ consents: ["health_data"] });
  await mockApi(
    page,
    baseMocks({
      "GET /auth/session": () => ({ json: session }),
      "DELETE /consents/*": (req: { url: string }) => {
        revoked = req.url.split("/").pop()!;
        session = signedInSession({ consents: [] });
        return { status: 204, body: "" };
      },
    }),
  );
  await page.goto("/profile");
  const upload = page.getByTestId("consent-health_data");
  await expect(page.getByTestId("consent-health_data-state")).toHaveText("Given");
  await expect(page.getByTestId("consent-contribute-state")).toHaveText("Not given");
  await expect(upload).toContainText("deletes your profile, your chats with Dr. Wu, and your documents with their findings and processing jobs");
  await page.getByText("Consent history").click();
  await expect(page.getByTestId("consent-history").getByRole("listitem")).toHaveCount(2);
  await page.getByTestId("withdraw-health_data").click();
  await expect.poll(() => revoked).toBe("health_data");
});

test("contributions: create behind contribute consent, list and remove", async ({ page }) => {
  let created: Record<string, unknown> | null = null;
  let deleted = "";
  await mockApi(
    page,
    baseMocks({
      "GET /auth/session": signedInSession({ consents: ["health_data", "contribute"] }),
      "GET /contributions": [
        { id: "k1", kind: "asset", payload: { asset_type: "registry", name: "STXBP1 family registry" }, status: "pending_review", created_at: "2026-10-01T10:00:00Z" },
      ],
      "POST /contributions": (req: { body: unknown }) => {
        created = req.body as Record<string, unknown>;
        return { status: 201, json: { id: "k2", ...created, status: "pending_review", created_at: new Date().toISOString() } };
      },
      "DELETE /contributions/*": (req: { url: string }) => {
        deleted = req.url.split("/").pop()!;
        return { status: 204, body: "" };
      },
    }),
  );
  await page.goto("/profile");
  const list = page.getByTestId("contribution-list");
  await expect(list).toContainText("STXBP1 family registry");
  await expect(list.getByTestId("status-flag")).toHaveText("Pending review");

  await page.getByTestId("contribute-open").click();
  const form = page.getByTestId("contribution-form");
  await expect(form).toContainText("patient-reported");
  await form.getByRole("button", { name: "Fill in from my profile" }).click();
  await expect(form.getByText("STXBP1 encephalopathy")).toBeVisible();
  await form.getByRole("button", { name: "Contribute" }).click();
  await expect(list.getByTestId("contribution")).toHaveCount(2);
  expect(created).toEqual({
    kind: "phenotype_profile",
    payload: { disease_id: "MONDO:0100135", phenotype_ids: ["HP:0001250"], excluded_phenotype_ids: ["HP:0011968"], age_range: null },
  });

  await list.getByTestId("contribution").last().getByRole("button", { name: "Remove contribution" }).click();
  await expect.poll(() => deleted).toBe("k1");
});

test("contributions: opening the form without consent asks for it", async ({ page }) => {
  await mockApi(page, baseMocks());
  await page.goto("/profile");
  await page.getByTestId("contribute-open").click();
  await expect(page.getByTestId("consent-content-contribute")).toBeVisible();
  await page.getByRole("button", { name: "Not now" }).click();
  await expect(page.getByTestId("contribution-form")).toHaveCount(0);
});

test("your data: export downloads JSON, delete account signs out", async ({ page }) => {
  let deleted = false;
  await mockApi(
    page,
    baseMocks({
      "GET /me/export": { exported_at: "2026-10-04T10:00:00Z", account: { id: "u1", created_at: "2026-10-01T10:00:00Z" } },
      "DELETE /me": () => {
        deleted = true;
        return { status: 204, body: "" };
      },
      "POST /auth/logout": { status: 204, body: "" },
    }),
  );
  await page.goto("/profile");
  const download = page.waitForEvent("download");
  await page.getByTestId("export-data").click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/^amber-my-data-\d{4}-\d{2}-\d{2}\.json$/);

  await page.getByTestId("delete-account").click();
  const dialog = page.getByTestId("delete-account-dialog");
  await expect(dialog).toContainText("Your documents and their findings");
  await expect(dialog).toContainText("removed from the shared atlas");
  await dialog.getByRole("button", { name: "Delete everything" }).click();
  await expect(page).toHaveURL(/127\.0\.0\.1:\d+\/$/);
  expect(deleted).toBe(true);
});

test("GPC: indicator shows the signal was received and honoured", async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(Navigator.prototype, "globalPrivacyControl", { get: () => true }));
  await mockApi(page, baseMocks({ "GET /auth/session": { ...signedInSession({ gpc_opt_out: true }), gpc: true } }));
  await page.goto("/profile");
  const gpc = page.getByTestId("gpc-status");
  await expect(gpc).toHaveAttribute("data-gpc", "on");
  await expect(gpc).toContainText("Signal received and honoured");
});

test("GPC: no signal still says nothing is sold or shared", async ({ page }) => {
  await mockApi(page, baseMocks());
  await page.goto("/profile");
  await expect(page.getByTestId("gpc-status")).toHaveAttribute("data-gpc", "off");
  await expect(page.getByTestId("gpc-status")).toContainText("never sells or shares");
});

test("guest sees a sign-in prompt on /profile", async ({ page }) => {
  await mockApi(page, { "GET /auth/session": guestSession });
  const errors = trackConsoleErrors(page);
  await page.goto("/profile");
  await expect(page.getByTestId("sign-in-prompt")).toContainText("Sign in to see your profile");
  expect(errors()).toEqual([]);
});

test("profile degrades gracefully when the API returns 501", async ({ page }) => {
  await mockApi(page, { "GET /auth/session": signedInSession() }, { fallback: "not_implemented" });
  const errors = trackConsoleErrors(page, { ignoreApiFailures: true });
  await page.goto("/profile");
  await expect(page.getByText("not available yet").first()).toBeVisible();
  expect(errors().filter((e) => !/501/.test(e))).toEqual([]);
});

test("screenshots: profile light and dark", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockApi(page, baseMocks({ "GET /contributions": [{ id: "k1", kind: "asset", payload: { asset_type: "registry", name: "STXBP1 family registry" }, status: "pending_review", created_at: "2026-10-01T10:00:00Z" }] }));
  for (const theme of ["light", "dark"] as const) {
    await setTheme(page, theme);
    await page.goto("/profile");
    await expect(page.getByTestId("profile-disease")).toBeVisible();
    await shot(page, `account-profile-${theme}`, { fullPage: true });
  }
});

test("profile on a phone @mobile", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockApi(page, baseMocks());
  await page.goto("/profile");
  await expect(page.getByTestId("profile-disease")).toBeVisible();
  await shot(page, "account-profile-mobile", { fullPage: true });
});
