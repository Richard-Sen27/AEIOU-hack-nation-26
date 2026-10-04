import { expect, test, type Page } from "@playwright/test";

import { errorEnvelope, guestSession, hit, mockApi, setTheme, signedInSession, trackConsoleErrors } from "../helpers";
import { expectNoHealthDataInBrowser } from "../account/fixtures";
import { graphMocks } from "../graph/fixtures";

/**
 * Calls (connect stage 3): browsing published surveys, studies and trials,
 * and the expert's own calls with the create-and-edit form. Mocked API only.
 * Screenshots: set CALLS_SHOTS_DIR.
 */

const SHOTS = process.env.CALLS_SHOTS_DIR;
const STXBP1 = "MONDO:9900007";
const DRAVET = "MONDO:0100135";
const BADGE = "Reviewed by the Amber team for wording, ethics and registry numbers, not for scientific quality";
const SELF_BADGE = "Published by the author without review by the Amber team";
const NOTICE = "Ask your doctor whether this trial or study could apply to you. This is not an eligibility check: only the study team decides who can take part.";

type Req = { url: string; method: string; body: unknown };

const card = (extra: Record<string, unknown> = {}) => ({
  card_id: "card-0001",
  role: "researcher",
  role_self_declared: true,
  name: "Dr. Ada Example",
  name_source: "orcid",
  institutions: [{ node_id: null, label: "Example University Hospital" }],
  orcid_id: "0000-0002-1825-0097",
  orcid_url: "https://orcid.org/0000-0002-1825-0097",
  atlas_node_id: null,
  atlas_node_label: null,
  headline: null,
  accepts_patient_messages: false,
  verification: { method: "orcid", label: "ORCID iD confirmed", simulated: false },
  ...extra,
});

function call(id: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    kind: "survey",
    title: "Survey on sleep and daily routines",
    summary: "A short online survey about sleep.",
    participation: "About 20 minutes online, once. No visits.",
    eligibility_text: null,
    diseases: [{ id: DRAVET, label: "Dravet syndrome" }],
    genes: [],
    phenotypes: [],
    min_age: null,
    max_age: null,
    adults_only: false,
    children_ok: true,
    countries: ["DE", "AT"],
    remote: true,
    run_by_label: "Example University Hospital",
    run_by_node: null,
    ethics_body: null,
    ethics_reference: null,
    registry_id: null,
    registry_url: null,
    external_url: "https://example.org/survey",
    opens_at: null,
    closes_at: "2027-03-31",
    max_signups: null,
    requested_fields: ["diagnosis"],
    publisher: card(),
    published_at: "2026-10-01T09:00:00Z",
    demo: false,
    review_badge: BADGE,
    notice: NOTICE,
    ...extra,
  };
}

const SURVEY = call("11111111-1111-4111-8111-111111111111", { title: "Demo: Survey on sleep in Dravet syndrome", demo: true });
const STUDY = call("22222222-2222-4222-8222-222222222222", {
  kind: "study",
  title: "Natural history study of STXBP1 disorders",
  diseases: [{ id: STXBP1, label: "STXBP1 encephalopathy" }],
  genes: [{ id: "HGNC:11444", label: "STXBP1" }],
  ethics_body: "Example ethics committee",
  ethics_reference: "EC-2026-002",
  min_age: 18,
  adults_only: true,
  children_ok: false,
  remote: false,
  external_url: null,
});
const TRIAL = call("33333333-3333-4333-8333-333333333333", {
  kind: "trial",
  title: "Observational trial for SCN1A-related epilepsy",
  diseases: [
    { id: DRAVET, label: "Dravet syndrome" },
    { id: STXBP1, label: "STXBP1 encephalopathy" },
  ],
  ethics_body: "Example ethics committee",
  ethics_reference: "EC-2026-001",
  registry_id: "NCT01234567",
  registry_url: "https://clinicaltrials.gov/study/NCT01234567",
  min_age: 2,
  max_age: 17,
  review_badge: SELF_BADGE,
});
const CALLS = [SURVEY, STUDY, TRIAL];

function own(id: string, status: string, extra: Record<string, unknown> = {}) {
  return {
    ...call(id, { publisher: null, published_at: status === "published" ? "2026-10-02T09:00:00Z" : null }),
    status,
    review_note: null,
    submitted_at: status === "draft" ? null : "2026-10-02T08:00:00Z",
    reviewed_at: null,
    closed_at: null,
    created_at: "2026-10-01T08:00:00Z",
    updated_at: "2026-10-01T08:00:00Z",
    expired: false,
    editable: ["draft", "pending_review", "rejected"].includes(status),
    wording_issues: [],
    ...extra,
  };
}

const expert = signedInSession({ role: "researcher", role_verified: true, name: "Ada Example" });
const patient = signedInSession({ role: "patient" });

/** Routes for both sides, with a log of every API request (to check URLs and bodies). */
function callsMocks(opts: { session?: unknown; mine?: unknown[]; canPublish?: boolean; review?: boolean; submit?: (r: Req) => unknown } = {}) {
  const log: Req[] = [];
  const state = { mine: [...(opts.mine ?? [])] as Array<Record<string, unknown>> };
  const rec = (r: Req) => (log.push(r), r);
  const byId = (url: string) => decodeURIComponent(new URL(url).pathname.split("/")[3]);
  const mocks = {
    "GET /auth/session": opts.session ?? patient,
    "GET /calls": (r: Req) => (rec(r), { json: { heading: "Find trials and studies looking for participants", items: CALLS } }),
    "GET /calls/*": (r: Req) => {
      rec(r);
      const c = CALLS.find((x) => x.id === decodeURIComponent(new URL(r.url).pathname.split("/")[2]));
      return c ? { json: c } : errorEnvelope(404, "not_found", "No such call.");
    },
    "GET /me/calls": (r: Req) => (
      rec(r), { json: { items: state.mine, can_publish: opts.canPublish ?? true, open_limit: 10, ...(opts.review !== undefined ? { review_required: opts.review } : {}) } }
    ),
    "GET /me/calls/*": (r: Req) => {
      rec(r);
      const c = state.mine.find((x) => x.id === byId(r.url));
      return c ? { json: c } : errorEnvelope(404, "not_found", "No such call.");
    },
    "POST /me/calls": (r: Req) => {
      rec(r);
      const c = own("44444444-4444-4444-8444-444444444444", "draft", { ...(r.body as object), diseases: [{ id: STXBP1, label: "STXBP1 encephalopathy" }] });
      state.mine = [c, ...state.mine];
      return { status: 201, json: c };
    },
    "PUT /me/calls/*": (r: Req) => {
      rec(r);
      const id = byId(r.url);
      const prev = state.mine.find((x) => x.id === id)!;
      const c = { ...prev, ...(r.body as object), status: "draft" };
      state.mine = state.mine.map((x) => (x.id === id ? c : x));
      return { json: c };
    },
    "POST /me/calls/*/submit": (r: Req) => {
      rec(r);
      if (opts.submit) return opts.submit(r);
      const id = byId(r.url);
      const c = { ...state.mine.find((x) => x.id === id)!, status: opts.review ? "pending_review" : "published", editable: !!opts.review, published_at: opts.review ? null : "2026-10-04T09:00:00Z", submitted_at: "2026-10-04T09:00:00Z" };
      state.mine = state.mine.map((x) => (x.id === id ? c : x));
      return { json: c };
    },
    "POST /me/calls/*/close": (r: Req) => {
      rec(r);
      const id = byId(r.url);
      const prev = state.mine.find((x) => x.id === id)!;
      const c = { ...prev, status: prev.status === "published" ? "closed" : "withdrawn", editable: false, closed_at: "2026-10-04T10:00:00Z" };
      state.mine = state.mine.map((x) => (x.id === id ? c : x));
      return { json: c };
    },
    "DELETE /me/calls/*": (r: Req) => {
      rec(r);
      state.mine = state.mine.filter((x) => x.id !== byId(r.url));
      return { status: 204, body: "" };
    },
    "GET /search": ({ url }: { url: string }) => {
      const types = new URL(url).searchParams.getAll("types");
      if (types.includes("disease")) return { json: { results: [hit(STXBP1, "disease", "STXBP1 encephalopathy")] } };
      if (types.includes("gene")) return { json: { results: [hit("HGNC:11444", "gene", "STXBP1")] } };
      return { json: { results: [] } };
    },
  };
  return { mocks, log, state };
}

const of = (log: Req[], method: string, path: string) => log.filter((r) => r.method === method && new URL(r.url).pathname === path);

async function expectNoDiseaseIdInRequests(page: Page, log: Req[]) {
  for (const r of log) expect(r.url, `request URL ${r.url}`).not.toMatch(/MONDO|HGNC|HP%3A|HP:/);
  await expectNoHealthDataInBrowser(page, ["MONDO", "Dravet", "STXBP1"]);
}

async function shots(page: Page, name: string) {
  if (!SHOTS) return;
  await page.screenshot({ path: `${SHOTS}/calls-${name}.png`, fullPage: true, animations: "disabled" });
}

test.describe("browsing calls", () => {
  test("guests see the sign-in prompt and nothing is requested", async ({ page }) => {
    const { mocks, log } = callsMocks({ session: guestSession });
    await mockApi(page, mocks);
    await page.goto("/calls");
    await expect(page.getByTestId("sign-in-prompt")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Find trials and studies looking for participants" })).toBeVisible();
    await page.goto(`/calls/${TRIAL.id}`);
    await expect(page.getByTestId("sign-in-prompt")).toBeVisible();
    expect(log).toHaveLength(0);
  });

  test("the list filters by kind and by disease in the browser only", async ({ page }) => {
    const { mocks, log } = callsMocks();
    const errors = trackConsoleErrors(page);
    await mockApi(page, mocks);
    await page.goto("/calls");
    const rows = page.getByTestId("call-row");
    await expect(rows).toHaveCount(3);
    await expect(page.getByTestId("calls-count")).toHaveText("3 open");
    await expect(rows.first().getByTestId("call-demo")).toHaveText("Demo, not a real study");
    // Patients see nothing of the publishing side.
    await expect(page.getByTestId("my-calls-link")).toHaveCount(0);
    await expect(page.getByTestId("new-call-link")).toHaveCount(0);

    const kind = page.getByTestId("calls-kind-filter");
    await kind.getByRole("button", { name: "Trials" }).click();
    await expect(rows).toHaveCount(1);
    await expect(rows.first()).toContainText("Observational trial");
    await kind.getByRole("button", { name: "All" }).click();
    await expect(rows).toHaveCount(3);

    await page.getByTestId("calls-disease-filter").selectOption(STXBP1);
    await expect(rows).toHaveCount(2);
    await kind.getByRole("button", { name: "Surveys" }).click();
    await expect(page.getByTestId("calls-empty")).toContainText("Nothing open matches.");
    await page.getByRole("button", { name: "Show all" }).click();
    await expect(rows).toHaveCount(3);

    expect(of(log, "GET", "/calls")).toHaveLength(1);
    expect(new URL(of(log, "GET", "/calls")[0].url).search).toBe("");
    await expectNoDiseaseIdInRequests(page, log);
    expect(errors()).toEqual([]);
  });

  test("a call's page: survey with demo mark, study for adults, trial with registry link", async ({ page }) => {
    const { mocks, log } = callsMocks();
    const errors = trackConsoleErrors(page);
    await mockApi(page, mocks);

    await page.goto(`/calls/${SURVEY.id}`);
    const detail = page.getByTestId("call-detail");
    await expect(detail.getByRole("heading", { level: 1 })).toHaveText(SURVEY.title);
    await expect(detail.getByTestId("call-demo")).toBeVisible();
    await expect(detail.getByTestId("call-kind")).toHaveText("Survey");
    await expect(detail.getByTestId("call-notice")).toHaveText(NOTICE);
    await expect(detail.getByTestId("call-review-badge")).toHaveText(BADGE);
    await expect(detail.getByTestId("call-publisher")).toHaveAttribute("href", "/people/card-0001");
    await expect(detail.getByTestId("call-publisher")).toContainText("ORCID iD confirmed");
    await expect(detail.getByTestId("call-signup-slot")).toBeVisible();
    await expect(detail.getByTestId("call-external-link")).toHaveAttribute("href", "https://example.org/survey");
    await expect(detail.getByTestId("call-eligibility")).toContainText("Germany, Austria");
    await expect(detail.getByTestId("call-ethics")).toHaveCount(0);

    await page.goto(`/calls/${STUDY.id}`);
    await expect(detail.getByTestId("call-kind")).toHaveText("Study");
    await expect(detail.getByTestId("call-demo")).toHaveCount(0);
    await expect(detail.getByTestId("call-adults-only")).toBeVisible();
    await expect(detail.getByTestId("call-ethics")).toContainText("EC-2026-002");
    await expect(detail.getByTestId("call-registry-link")).toHaveCount(0);

    await page.goto(`/calls/${TRIAL.id}`);
    await expect(detail.getByTestId("call-kind")).toHaveText("Trial");
    await expect(detail.getByTestId("call-registry-link")).toHaveAttribute("href", "https://clinicaltrials.gov/study/NCT01234567");
    await expect(detail.getByTestId("call-registry-link")).toHaveAttribute("target", "_blank");
    await expect(detail.getByTestId("call-review-badge")).toHaveText(SELF_BADGE);
    await expect(detail.getByTestId("call-eligibility")).toContainText("Ages 2 to 17");
    await expect(detail.getByTestId("call-notice")).toHaveText(NOTICE);

    await page.goto("/calls/55555555-5555-4555-8555-555555555555");
    await expect(page.getByTestId("call-error")).toContainText("closed or no longer listed");
    await expectNoDiseaseIdInRequests(page, log);
    expect(errors()).toEqual([]);
  });

  test("experts get no sign-up slot on a call's page", async ({ page }) => {
    const { mocks } = callsMocks({ session: expert });
    await mockApi(page, mocks);
    await page.goto(`/calls/${SURVEY.id}`);
    await expect(page.getByTestId("call-detail")).toBeVisible();
    await expect(page.getByTestId("call-signup-slot")).toHaveCount(0);
  });

  test("a disease's page lists its open calls", async ({ page }) => {
    const { mocks, log } = callsMocks();
    await mockApi(page, graphMocks({ ...mocks, "GET /auth/session": patient, "GET /chat/sessions": [] }));
    await page.goto(`/node/${encodeURIComponent(STXBP1)}`);
    const section = page.getByTestId("disease-calls");
    await expect(section).toBeVisible();
    await expect(section.getByTestId("call-row")).toHaveCount(2);
    await expect(section).toContainText("Looking for participants · 2");
    await section.getByTestId("call-row").first().click();
    await expect(page).toHaveURL(new RegExp(`/calls/${STUDY.id}$`));
    for (const r of log) expect(r.url).not.toMatch(/MONDO/);
  });

  test("guests see no calls section on a disease's page", async ({ page }) => {
    const { mocks, log } = callsMocks({ session: guestSession });
    await mockApi(page, graphMocks({ ...mocks, "GET /auth/session": guestSession }));
    await page.goto(`/node/${encodeURIComponent(STXBP1)}`);
    await expect(page.getByTestId("node-panel")).toBeVisible();
    await expect(page.getByTestId("disease-calls")).toHaveCount(0);
    expect(log).toHaveLength(0);
  });
});

async function fillForm(page: Page, kind: "Survey" | "Study" | "Trial") {
  const form = page.getByTestId("call-form");
  await form.getByRole("radio", { name: kind }).click();
  await form.getByTestId("field-title").getByRole("textbox").fill("Sleep in STXBP1 disorders");
  await form.getByTestId("field-summary").getByRole("textbox").fill("We want to learn how children with STXBP1 disorders sleep.");
  await form.getByTestId("field-participation").getByRole("textbox").fill("A 20-minute online questionnaire.");
  await form.getByTestId("picker-disease").getByRole("combobox").fill("STXBP1");
  await page.getByRole("option", { name: /STXBP1 encephalopathy/ }).click();
  await expect(form.getByTestId("chip-disease")).toHaveCount(1);
}

test.describe("publishing calls", () => {
  test("an expert writes a call, the form names mistakes, and Publish puts it live at once", async ({ page }) => {
    const { mocks, log } = callsMocks({ session: expert, mine: [] });
    const errors = trackConsoleErrors(page);
    await mockApi(page, mocks);
    await page.goto("/calls");
    await expect(page.getByTestId("my-calls-link")).toBeVisible();
    await page.getByTestId("new-call-link").click();
    await expect(page).toHaveURL(/\/calls\/mine\/new$/);
    const form = page.getByTestId("call-form");
    await expect(page.getByTestId("call-submit")).toHaveText("Publish");
    await expect(form).toContainText("Publishing lists it for every signed-in user at once.");
    await expect(form).not.toContainText("The Amber team checks");

    // Empty form: every required field is named, nothing is sent.
    await page.getByTestId("call-submit").click();
    await expect(form.getByTestId("field-title").getByTestId("field-error")).toHaveText("Required.");
    await expect(form.getByTestId("field-disease_ids").getByTestId("field-error")).toHaveText("Add at least one disease.");
    expect(of(log, "POST", "/me/calls")).toHaveLength(0);

    await fillForm(page, "Trial");
    await form.getByTestId("field-registry_id").getByRole("textbox").fill("12345");
    await form.getByTestId("field-min_age").getByRole("textbox").fill("18");
    await form.getByTestId("field-max_age").getByRole("textbox").fill("4");
    await form.getByTestId("field-countries").getByRole("textbox").fill("DE, Germany");
    await form.getByTestId("field-external_url").getByRole("textbox").fill("http://example.org");
    await page.getByTestId("call-submit").click();
    await expect(form.getByTestId("field-ethics_reference").getByTestId("field-error")).toHaveText("Required for a trial.");
    await expect(form.getByTestId("field-registry_id").getByTestId("field-error")).toContainText("NCT");
    await expect(form.getByTestId("field-max_age").getByTestId("field-error")).toContainText("minimum age");
    await expect(form.getByTestId("field-countries").getByTestId("field-error")).toContainText("GERMANY");
    await expect(form.getByTestId("field-external_url").getByTestId("field-error")).toHaveText("An https:// link.");
    expect(of(log, "POST", "/me/calls")).toHaveLength(0);

    await form.getByTestId("field-ethics_reference").getByRole("textbox").fill("EC-2026-003");
    await form.getByTestId("field-registry_id").getByRole("textbox").fill("nct01234567");
    await form.getByTestId("field-max_age").getByRole("textbox").fill("");
    await form.getByTestId("field-countries").getByRole("textbox").fill("de, at");
    await form.getByTestId("field-external_url").getByRole("textbox").fill("https://example.org/study");
    await form.getByTestId("picker-gene").getByRole("combobox").fill("STXBP1");
    await page.getByRole("option", { name: /STXBP1/ }).click();
    await page.getByTestId("call-submit").click();

    await expect(page).toHaveURL(/\/calls\/mine$/);
    const posts = of(log, "POST", "/me/calls");
    expect(posts).toHaveLength(1);
    expect(posts[0].body).toMatchObject({
      kind: "trial",
      title: "Sleep in STXBP1 disorders",
      disease_ids: [STXBP1],
      gene_ids: ["HGNC:11444"],
      min_age: 18,
      max_age: null,
      countries: ["DE", "AT"],
      ethics_reference: "EC-2026-003",
      registry_id: "NCT01234567",
      external_url: "https://example.org/study",
      requested_fields: ["diagnosis"],
    });
    expect(log.filter((r) => r.url.endsWith("/submit"))).toHaveLength(1);
    const item = page.getByTestId("own-call").first();
    await expect(item.getByTestId("call-status")).toHaveText("Published");
    await expect(item.getByTestId("own-call-view")).toHaveAttribute("href", "/calls/44444444-4444-4444-8444-444444444444");
    await expectNoDiseaseIdInRequests(page, log);
    expect(errors()).toEqual([]);
  });

  test("editing a draft saves it, and a wording refusal names the field", async ({ page }) => {
    const draft = own("66666666-6666-4666-8666-666666666666", "draft", {
      title: "Draft about sleep",
      summary: "This could cure sleep problems.",
      wording_issues: [{ field: "summary", term: "cure" }],
    });
    const { mocks, log } = callsMocks({
      session: expert,
      mine: [draft],
      submit: () => errorEnvelope(422, "validation_error", "Calls describe research looking for participants and must not offer, promise or price a treatment. Rephrase: summary ('cure')"),
    });
    await mockApi(page, mocks);
    await page.goto("/calls/mine");
    const item = page.getByTestId("own-call");
    await expect(item.getByTestId("call-status")).toHaveText("Draft");
    await expect(item.getByTestId("own-call-wording")).toContainText('What it is about ("cure")');
    await item.getByTestId("own-call-edit").click();
    await expect(page).toHaveURL(/\/calls\/mine\/66666666/);

    const form = page.getByTestId("call-form");
    await expect(form.getByTestId("field-title").getByRole("textbox")).toHaveValue("Draft about sleep");
    await form.getByTestId("field-title").getByRole("textbox").fill("Sleep and daily routines");
    await page.getByTestId("call-save").click();
    await expect(page.getByText("Draft saved")).toBeVisible();
    const puts = of(log, "PUT", `/me/calls/${draft.id}`);
    expect(puts).toHaveLength(1);
    expect(puts[0].body).toMatchObject({ title: "Sleep and daily routines", disease_ids: [DRAVET] });

    await page.getByTestId("call-submit").click();
    const alert = page.getByTestId("call-form-server-error");
    await expect(alert).toContainText('Rephrase: What it is about ("cure")');
    await expect(form.getByTestId("field-summary").getByRole("textbox")).toHaveAttribute("aria-invalid", "true");
    await expect(page).toHaveURL(/\/calls\/mine\/66666666/);
  });

  test("with review switched on, the button reads Submit for review and the call waits", async ({ page }) => {
    const draft = own("77777777-7777-4777-8777-777777777777", "draft");
    const { mocks } = callsMocks({ session: expert, mine: [draft], review: true });
    await mockApi(page, mocks);
    await page.goto(`/calls/mine/${draft.id}`);
    await expect(page.getByTestId("call-submit")).toHaveText("Submit for review");
    await expect(page.getByTestId("call-form")).toContainText("The Amber team checks wording, ethics and registry number before it is listed.");
    await page.getByTestId("call-submit").click();
    await expect(page).toHaveURL(/\/calls\/mine$/);
    await expect(page.getByTestId("own-call").getByTestId("call-status")).toHaveText("In review");
    await expect(page.getByTestId("own-call")).toContainText("Waiting for review by the Amber team.");
  });

  test("from the list: publish, close and delete", async ({ page }) => {
    const draft = own("88888888-8888-4888-8888-888888888888", "draft", { title: "A draft" });
    const live = own("99999999-9999-4999-8999-999999999999", "published", { title: "A live call" });
    const rejected = own("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "rejected", { title: "A rejected call", review_note: "Please add the ethics approval reference." });
    const { mocks, log } = callsMocks({ session: expert, mine: [draft, live, rejected] });
    await mockApi(page, mocks);
    await page.goto("/calls/mine");
    const items = page.getByTestId("own-call");
    await expect(items).toHaveCount(3);
    await expect(items.nth(2).getByTestId("own-call-review-note")).toContainText("Please add the ethics approval reference.");
    await expect(items.nth(0)).not.toContainText("The Amber team reviews it");

    await items.nth(0).getByTestId("own-call-submit").click();
    await expect(items.nth(0).getByTestId("call-status")).toHaveText("Published");
    await expect(items.nth(0).getByTestId("own-call-view")).toBeVisible();

    await items.nth(1).getByTestId("own-call-close").click();
    await page.getByTestId("own-call-confirm-action").click();
    await expect(items.nth(1).getByTestId("call-status")).toHaveText("Closed");
    expect(of(log, "POST", `/me/calls/${live.id}/close`)).toHaveLength(1);

    await items.nth(2).getByTestId("own-call-delete").click();
    await expect(page.getByTestId("own-call-confirm")).toContainText("Delete this call?");
    await page.getByTestId("own-call-confirm-action").click();
    await expect(items).toHaveCount(2);
    expect(of(log, "DELETE", `/me/calls/${rejected.id}`)).toHaveLength(1);
  });

  test("an expert who cannot publish yet sees why and the card settings link", async ({ page }) => {
    const old = own("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "published", { title: "An older call" });
    const { mocks } = callsMocks({ session: signedInSession({ role: "doctor" }), mine: [old], canPublish: false });
    await mockApi(page, mocks);
    await page.goto("/calls/mine");
    await expect(page.getByTestId("calls-cannot-publish")).toContainText("get verified and switch on your public card");
    await expect(page.getByTestId("card-settings-link")).toHaveAttribute("href", "/profile#your-work");
    await expect(page.getByTestId("new-call")).toHaveCount(0);
    // Existing calls can still be closed and deleted.
    await expect(page.getByTestId("own-call").getByTestId("own-call-close")).toBeVisible();
    await page.goto("/calls/mine/new");
    await expect(page.getByTestId("calls-cannot-publish")).toBeVisible();
    await expect(page.getByTestId("call-form")).toHaveCount(0);
  });

  test("patients see none of the publishing side", async ({ page }) => {
    const { mocks, log } = callsMocks({ session: patient });
    await mockApi(page, mocks);
    await page.goto("/calls/mine");
    await expect(page.getByTestId("calls-not-publisher")).toBeVisible();
    await expect(page.getByTestId("my-calls")).toHaveCount(0);
    await page.goto("/calls/mine/new");
    await expect(page.getByTestId("calls-not-publisher")).toBeVisible();
    await expect(page.getByTestId("call-form")).toHaveCount(0);
    expect(log.filter((r) => r.url.includes("/me/calls"))).toHaveLength(0);
  });
});

test.describe("layout", () => {
  for (const session of [patient, guestSession]) {
    test(`the header fits at 1024 px with Studies (${session.user ? "signed in" : "guest"})`, async ({ page }) => {
      const { mocks } = callsMocks({ session });
      await page.setViewportSize({ width: 1024, height: 768 });
      await mockApi(page, mocks);
      await page.goto("/calls");
      const nav = page.getByRole("navigation", { name: "Primary" }).first();
      const studies = nav.getByRole("link", { name: "Studies" });
      await expect(studies).toBeVisible();
      await expect(studies).toHaveAttribute("aria-current", "page");
      const fits = await page.evaluate(() => {
        const row = document.querySelector("header > div") as HTMLElement;
        return row.scrollWidth <= row.clientWidth && document.documentElement.scrollWidth <= window.innerWidth;
      });
      expect(fits).toBe(true);
      const nb = (await studies.boundingBox())!;
      const sb = (await page.getByTestId("search-trigger").boundingBox())!;
      expect(nb.x + nb.width).toBeLessThanOrEqual(sb.x);
      if (SHOTS) await page.locator("header").first().screenshot({ path: `${SHOTS}/calls-header-1024-${session.user ? "signed-in" : "guest"}.png` });
    });
  }
});

test.describe("phone", () => {
  test("list, call page, my calls and form fit a phone @mobile", async ({ page }) => {
    const { mocks } = callsMocks({ session: expert, mine: [own("cccccccc-cccc-4ccc-8ccc-cccccccccccc", "draft")] });
    await mockApi(page, mocks);
    const noSideScroll = () => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
    for (const path of ["/calls", `/calls/${TRIAL.id}`, "/calls/mine", "/calls/mine/new"]) {
      await page.goto(path);
      await expect(page.locator("main").getByRole("heading", { level: 1 }).first()).toBeVisible();
      await page.waitForLoadState("networkidle");
      expect(await noSideScroll(), path).toBe(true);
    }
    await page.getByRole("button", { name: /Open menu/ }).click();
    await expect(page.getByRole("dialog").getByRole("link", { name: "Studies" })).toBeVisible();
  });
});

test.describe("screenshots", () => {
  test.skip(!SHOTS, "set CALLS_SHOTS_DIR");
  for (const theme of ["light", "dark"] as const) {
    for (const width of [1440, 390]) {
      test(`calls screens ${theme} ${width}`, async ({ page }) => {
        const draft = own("dddddddd-dddd-4ddd-8ddd-dddddddddddd", "draft", { title: "Sleep and daily routines in Dravet syndrome", wording_issues: [{ field: "summary", term: "cure" }] });
        const live = own("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee", "published", { kind: "trial", title: "Observational trial for SCN1A-related epilepsy" });
        const pending = own("ffffffff-ffff-4fff-8fff-ffffffffffff", "rejected", { kind: "study", title: "Natural history study", review_note: "Please add the ethics approval reference." });
        const { mocks } = callsMocks({ session: expert, mine: [draft, live, pending] });
        await setTheme(page, theme);
        await page.setViewportSize({ width, height: width > 500 ? 900 : 844 });
        await mockApi(page, { ...mocks, "GET /auth/session": patient });
        await page.goto("/calls");
        await expect(page.getByTestId("call-row")).toHaveCount(3);
        await shots(page, `list-${width}-${theme}`);
        await page.goto(`/calls/${TRIAL.id}`);
        await expect(page.getByTestId("call-detail")).toBeVisible();
        await shots(page, `call-${width}-${theme}`);
        await page.unrouteAll({ behavior: "ignoreErrors" });
        await mockApi(page, mocks);
        await page.goto("/calls/mine");
        await expect(page.getByTestId("own-call")).toHaveCount(3);
        await shots(page, `mine-${width}-${theme}`);
        await page.goto(`/calls/mine/${draft.id}`);
        await expect(page.getByTestId("call-form")).toBeVisible();
        await shots(page, `form-${width}-${theme}`);
      });
    }
  }
});
