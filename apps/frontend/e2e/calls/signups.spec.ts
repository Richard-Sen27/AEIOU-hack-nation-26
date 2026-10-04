import { expect, test, type Page } from "@playwright/test";

import { expectNoHealthDataInBrowser } from "../account/fixtures";
import { errorEnvelope, mockApi, setTheme, signedInSession, trackConsoleErrors } from "../helpers";

/**
 * Connect stage 4: signing up to calls, my sign-ups, the publisher's list,
 * suggestions and the bell. Mocked API only. Screenshots: set SIGNUPS_SHOTS_DIR.
 */

const SHOTS = process.env.SIGNUPS_SHOTS_DIR;
const T0 = "2026-10-03T09:00:00Z";
const DRAVET = "MONDO:0100135";
const CALL_ID = "11111111-1111-4111-8111-111111111111";
const ADULT_ID = "22222222-2222-4222-8222-222222222222";
const SIGNUP_ID = "aaaaaaaa-0000-4000-8000-000000000001";
const THREAD_ID = "cccccccc-0000-4000-8000-000000000001";
const RECIPIENT = "Dr. Ada Example, Example University Hospital";
const AUTH_TEXT = `You are sending the following to ${RECIPIENT}, who runs this call: {items}. After sending, Dr. Ada Example is responsible for this information under their ethics approval. You can withdraw here at any time; that deletes it from Amber but cannot undo what the team has already noted. Signing up does not mean you are eligible: only the study team can decide.`;
const GUARDIAN = `A parent or guardian knows about this and agrees that I share it with ${RECIPIENT}.`;
const MINOR_LABEL = "Participant is 16 or 17; a parent or guardian agreed (self-declared)";
const FOR_ADULTS = "For adults: this call does not take sign-ups from people aged 16 or 17.";
const SENTENCE = "Suggested because your profile lists Dravet syndrome and SCN1A. This is not an eligibility check; only the study team decides.";
const NOTE = "My son is 9 and we live near Vienna.";

type Req = { url: string; method: string; body: unknown };

const card = {
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
};

function call(id: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    kind: "survey",
    title: "Survey on sleep in Dravet syndrome",
    summary: "A short online survey about sleep.",
    participation: "About 20 minutes online, once.",
    eligibility_text: null,
    diseases: [{ id: DRAVET, label: "Dravet syndrome" }],
    genes: [{ id: "HGNC:10585", label: "SCN1A" }],
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
    external_url: null,
    opens_at: null,
    closes_at: "2027-03-31",
    max_signups: 50,
    requested_fields: ["diagnosis", "genetic_findings", "age_range"],
    publisher: card,
    published_at: "2026-10-01T09:00:00Z",
    demo: false,
    self_published: true,
    review_badge: "Published by the expert. Not reviewed by the Amber team.",
    notice: "Ask your doctor whether this trial or study could apply to you.",
    ...extra,
  };
}

const SURVEY = call(CALL_ID);
const ADULT = call(ADULT_ID, { kind: "study", title: "Natural history study in adults", min_age: 18, adults_only: true, children_ok: false });
const CALLS = [SURVEY, ADULT];

const OPTIONS = [
  { key: `diagnosis:${DRAVET}`, kind: "diagnosis", label: "Dravet syndrome", detail: null, preselected: true },
  { key: "gene:HGNC:10585", kind: "gene", label: "SCN1A", detail: null, preselected: false },
  { key: "age_range", kind: "age_range", label: "Age range 6-12", detail: null, preselected: false },
];

function mySignup(extra: Record<string, unknown> = {}) {
  return {
    id: SIGNUP_ID,
    call_id: CALL_ID,
    call_title: SURVEY.title,
    call_open: true,
    recipient: RECIPIENT,
    display_name: "Leo's mum",
    shared: { diagnoses: [{ id: DRAVET, label: "Dravet syndrome", detail: null }], genes: [], variants: [], symptoms: [], age_range: null, country: null },
    note: NOTE,
    status: "active",
    about_child: true,
    authorization_version: "signup-authorization-2026-10-04",
    authorized_at: T0,
    guardian_agreed_at: null,
    guardian_text_version: null,
    created_at: T0,
    withdrawn_at: null,
    declined_at: null,
    call_ended_at: null,
    delete_after: null,
    thread_id: null,
    ...extra,
  };
}

function received(id: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    display_name: "Leo's mum",
    shared: { diagnoses: [{ id: DRAVET, label: "Dravet syndrome", detail: null }], genes: [{ id: "HGNC:10585", label: "SCN1A", detail: null }], variants: [], symptoms: [], age_range: "6-12", country: null },
    note: NOTE,
    status: "active",
    about_child: true,
    minor: false,
    minor_label: null,
    authorization_version: "signup-authorization-2026-10-04",
    authorized_at: T0,
    created_at: T0,
    withdrawn_at: null,
    declined_at: null,
    thread_id: THREAD_ID,
    ...extra,
  };
}

type Opts = {
  role?: "patient" | "doctor" | "researcher";
  /** connect consent: none, old (messaging-only text) or current. */
  consent?: "none" | "old" | "current";
  ageGroup?: "18_plus" | "16_17" | null;
  signupError?: () => unknown;
  suggestionsOn?: boolean;
  mine?: Array<Record<string, unknown>>;
};

function mocks(opts: Opts = {}) {
  const log: Req[] = [];
  const state = {
    consent: opts.consent ?? "current",
    ageGroup: opts.ageGroup === undefined ? ("18_plus" as string | null) : opts.ageGroup,
    signedUp: false,
    suggestions: opts.suggestionsOn ?? false,
    mine: opts.mine ?? ([] as Array<Record<string, unknown>>),
    received: [received("r1"), received("r2", { display_name: "Sam", about_child: false, minor: true, minor_label: MINOR_LABEL, note: null, thread_id: null }), received("r3", { display_name: "Kim", status: "withdrawn", shared: { diagnoses: [], genes: [], variants: [], symptoms: [], age_range: null, country: null }, note: null, thread_id: null })] as Array<Record<string, unknown>>,
  };
  const rec = (r: Req) => (log.push(r), r);
  const consents = () => (state.consent === "none" ? ["health_data"] : ["health_data", "connect"]);
  const current = () => state.consent === "current";
  const connectStatus = () => ({
    consent_active: state.consent !== "none",
    consent_current: current(),
    age_group: state.ageGroup,
    age_group_set_at: state.ageGroup ? T0 : null,
    guardian_text: "A parent or guardian knows about this and agrees that I share it with {recipient}.",
    guardian_text_version: "guardian-2026-10-04",
    report_authorization_text: "x",
    report_authorization_version: "report-2026-10-04",
  });
  const idOf = (url: string, i: number) => decodeURIComponent(new URL(url).pathname.split("/")[i]);
  const availability = (c: typeof SURVEY) => {
    if (opts.role && opts.role !== "patient") return { can_sign_up: false, blocked_by: "not_patient", label: null, signup_id: null };
    if (state.signedUp && c.id === CALL_ID) return { can_sign_up: false, blocked_by: "already_signed_up", label: null, signup_id: SIGNUP_ID };
    if (c.adults_only && state.ageGroup === "16_17") return { can_sign_up: false, blocked_by: "for_adults", label: FOR_ADULTS, signup_id: null };
    return { can_sign_up: true, blocked_by: null, label: null, signup_id: null };
  };
  const suggestionSettings = () => ({ enabled: state.suggestions, enabled_at: state.suggestions ? T0 : null, consent_active: current(), notice: "n" });

  const table: Record<string, unknown> = {
    "GET /auth/session": () => ({ json: signedInSession({ role: opts.role ?? "patient", consents: consents() }) }),
    "GET /notifications/unread-count": { count: 1 },
    "GET /notifications": {
      unread_count: 1,
      items: [
        { id: "n1", kind: "call_match", disease_id: DRAVET, disease_label: "Dravet syndrome", item_id: CALL_ID, call_id: CALL_ID, item_type: null, item_label: SURVEY.title, registry_id: null, year: null, gone: false, data_version: null, created_at: T0, read_at: null },
      ],
    },
    "POST /notifications/read": { count: 0 },
    "GET /me/threads/unread-count": { count: 0, requests_waiting: 0 },
    "POST /consents": (r: Req) => {
      rec(r);
      state.consent = "current";
      return { status: 201, json: { id: "c-connect", consent_type: "connect", active: true, granted_at: T0 } };
    },
    "GET /me/connect": (r: Req) => (rec(r), { json: connectStatus() }),
    "PUT /me/connect/age-group": (r: Req) => {
      rec(r);
      state.ageGroup = (r.body as { age_group: string }).age_group;
      return { json: connectStatus() };
    },
    "GET /calls": (r: Req) => (rec(r), { json: { heading: "Find trials and studies looking for participants", items: CALLS } }),
    "GET /calls/suggested": (r: Req) => {
      rec(r);
      const on = state.suggestions && current();
      return {
        json: {
          consent_active: current(),
          enabled: state.suggestions,
          notice: "n",
          items: on
            ? [{ call: SURVEY, score: 5, reasons: [{ kind: "disease", items: [{ id: DRAVET, label: "Dravet syndrome" }], via_variant: false }], sentence: SENTENCE, age_fits: true, country_listed: false, signup: availability(SURVEY) }]
            : [],
        },
      };
    },
    "GET /me/connect/suggestions": (r: Req) => (rec(r), { json: suggestionSettings() }),
    "PUT /me/connect/suggestions": (r: Req) => {
      rec(r);
      const on = (r.body as { enabled: boolean }).enabled;
      if (on && !current()) return errorEnvelope(403, "consent_required");
      state.suggestions = on;
      return { json: suggestionSettings() };
    },
    "GET /calls/*/signup": (r: Req) => {
      rec(r);
      const c = CALLS.find((x) => x.id === idOf(r.url, 2))!;
      const ok = current();
      return {
        json: {
          call_id: c.id,
          call_title: c.title,
          recipient: RECIPIENT,
          recipient_name: "Dr. Ada Example",
          options: ok ? OPTIONS : [],
          authorization_text: AUTH_TEXT,
          authorization_version: "signup-authorization-2026-10-04",
          consent_active: ok,
          age_group_needed: !state.ageGroup,
          guardian_required: state.ageGroup === "16_17",
          guardian_text: GUARDIAN,
          guardian_text_version: "guardian-2026-10-04",
          about_child: ok,
          availability: availability(c),
          max_note: 1000,
        },
      };
    },
    "POST /calls/*/signup": (r: Req) => {
      rec(r);
      if (opts.signupError) return opts.signupError();
      if (!current()) return errorEnvelope(403, "consent_required");
      const b = r.body as { guardian_agreed: boolean; open_conversation: boolean; display_name: string; note: string | null };
      if (state.ageGroup === "16_17" && !b.guardian_agreed) return errorEnvelope(403, "guardian_agreement_required");
      state.signedUp = true;
      const s = mySignup({ display_name: b.display_name, note: b.note, thread_id: b.open_conversation ? THREAD_ID : null });
      state.mine = [s, ...state.mine];
      return { status: 201, json: s };
    },
    "GET /calls/*": (r: Req) => {
      rec(r);
      const c = CALLS.find((x) => x.id === idOf(r.url, 2));
      return c ? { json: c } : errorEnvelope(404, "not_found");
    },
    "GET /me/signups": (r: Req) => (rec(r), { json: { items: state.mine } }),
    "DELETE /me/signups/*": (r: Req) => {
      rec(r);
      const id = idOf(r.url, 3);
      state.mine = state.mine.map((s) => (s.id === id ? { ...s, status: "withdrawn", shared: { diagnoses: [], genes: [], variants: [], symptoms: [], age_range: null, country: null }, note: null, delete_after: "2026-11-03T09:00:00Z" } : s));
      return { status: 204, body: "" };
    },
    "GET /me/calls": (r: Req) => (
      rec(r),
      {
        json: {
          items: [{ ...SURVEY, publisher: null, status: "published", review_note: null, submitted_at: T0, reviewed_at: null, closed_at: null, created_at: T0, updated_at: T0, expired: false, editable: false, wording_issues: [] }],
          can_publish: true,
          open_limit: 10,
        },
      }
    ),
    "GET /me/calls/*/signups": (r: Req) => (
      rec(r), { json: { call_id: CALL_ID, call_title: SURVEY.title, active_count: state.received.filter((s) => s.status === "active").length, max_signups: 50, items: state.received } }
    ),
    "POST /me/calls/*/signups/*/decline": (r: Req) => {
      rec(r);
      const id = idOf(r.url, 5);
      state.received = state.received.map((s) => (s.id === id ? { ...s, status: "declined", note: null, shared: { diagnoses: [], genes: [], variants: [], symptoms: [], age_range: null, country: null } } : s));
      return { json: state.received.find((s) => s.id === id) };
    },
  };
  return { table, log, state };
}

const bodies = (log: Req[], method: string, re: RegExp) => log.filter((r) => r.method === method && re.test(new URL(r.url).pathname)).map((r) => r.body);

/** Nothing shared or health-related in any request URL, the page URL, the title or browser storage. */
async function expectNothingLeaked(page: Page, log: Req[]) {
  for (const r of log) expect(r.url, `request URL ${r.url}`).not.toMatch(/MONDO|HGNC|HP%3A|HP:|Dravet|Leo|Vienna/);
  await expectNoHealthDataInBrowser(page, ["MONDO", "Dravet", "SCN1A", "Leo", "Vienna"]);
  expect(await page.title()).not.toMatch(/Dravet|SCN1A|Leo/);
}

async function grantConsent(page: Page) {
  const consent = page.getByTestId("consent-content-connect");
  await expect(consent).toBeVisible();
  await expect(consent).toContainText("sign up to studies, surveys and trials");
  await consent.getByRole("checkbox").click();
  await consent.getByRole("button", { name: "I agree, continue" }).click();
}

async function chooseAge(page: Page, label: "18 or older" | "16 or 17") {
  const age = page.getByTestId("age-group-dialog");
  await expect(age).toBeVisible();
  await age.getByText(label).click();
  await age.getByTestId("age-group-continue").click();
}

async function shot(page: Page, name: string) {
  if (!SHOTS) return;
  await page.screenshot({ path: `${SHOTS}/signups-${name}.png`, animations: "disabled" });
}

test.describe("signing up", () => {
  test("consent and age group just in time, the authorization with the ticked items, then the confirmation", async ({ page }) => {
    const m = mocks({ consent: "none", ageGroup: null });
    const errors = trackConsoleErrors(page);
    await mockApi(page, m.table);
    await page.goto(`/calls/${CALL_ID}`);
    await page.getByTestId("signup-start").click();
    await grantConsent(page);
    await chooseAge(page, "18 or older");

    const dialog = page.getByTestId("signup-dialog");
    await expect(dialog.getByTestId("signup-recipient")).toContainText(RECIPIENT);
    // Only the backend's pre-ticked diagnosis starts ticked.
    await expect(dialog.getByTestId("signup-item-diagnosis")).toBeChecked();
    await expect(dialog.getByTestId("signup-item-gene")).not.toBeChecked();
    await expect(dialog.getByTestId("signup-item-age_range")).not.toBeChecked();
    await expect(dialog.getByTestId("signup-guardian")).toHaveCount(0);
    await expect(dialog.getByTestId("signup-authorization")).toContainText("who runs this call: Dravet syndrome. After sending");
    await dialog.getByTestId("signup-item-gene").click();
    await expect(dialog.getByTestId("signup-authorization")).toContainText("who runs this call: Dravet syndrome, SCN1A. After sending");
    await expect(dialog.getByTestId("signup-send")).toBeDisabled();
    await dialog.getByTestId("signup-name").fill("Leo's mum");
    await dialog.getByTestId("signup-note").fill(NOTE);
    await expect(dialog.getByTestId("signup-authorization")).toContainText("Dravet syndrome, SCN1A, your note.");
    await expect(dialog.getByTestId("signup-send")).toBeDisabled();
    await dialog.getByTestId("signup-authorize").click();
    await dialog.getByTestId("signup-conversation").click();
    await dialog.getByTestId("signup-send").click();

    await expect(dialog.getByTestId("signup-sent")).toContainText(`To ${RECIPIENT}`);
    await expect(dialog.getByTestId("signup-sent-mine")).toHaveAttribute("href", "/calls/signups");
    await expect(dialog.getByTestId("signup-sent-thread")).toHaveAttribute("href", `/messages/${THREAD_ID}`);
    expect(bodies(m.log, "POST", /^\/consents$/)).toEqual([expect.objectContaining({ consent_type: "connect", version: "connect-signups-2026-10-04" })]);
    expect(bodies(m.log, "PUT", /age-group/)).toEqual([{ age_group: "18_plus" }]);
    expect(bodies(m.log, "POST", /\/signup$/)).toEqual([
      {
        display_name: "Leo's mum",
        items: [`diagnosis:${DRAVET}`, "gene:HGNC:10585"],
        note: NOTE,
        authorized: true,
        authorization_version: "signup-authorization-2026-10-04",
        guardian_agreed: false,
        open_conversation: true,
      },
    ]);
    await dialog.getByTestId("signup-done").click();
    await expect(page.getByTestId("signup-blocked")).toContainText("You signed up.");
    await expectNothingLeaked(page, m.log);
    expect(errors()).toEqual([]);
  });

  test("a consent to the earlier messaging-only text is asked again", async ({ page }) => {
    const m = mocks({ consent: "old" });
    await mockApi(page, m.table);
    await page.goto(`/calls/${CALL_ID}`);
    await page.getByTestId("signup-start").click();
    await grantConsent(page);
    await expect(page.getByTestId("signup-dialog")).toBeVisible();
    await expect(page.getByTestId("age-group-dialog")).toHaveCount(0);
    expect(bodies(m.log, "POST", /^\/consents$/)).toHaveLength(1);
  });

  test("a publisher verified by a demo shortcut is marked in the list, on the call and in the sign-up", async ({ page }) => {
    const LABEL = "Demo, verification simulated (no real identity check)";
    const demoCard = { ...card, name_source: "self_declared", orcid_id: null, orcid_url: null, verification: { method: "manual_simulated", label: LABEL, simulated: true } };
    const demoCall = call(CALL_ID, { publisher: demoCard });
    const m = mocks();
    await mockApi(page, {
      ...m.table,
      "GET /calls": { heading: "Find trials and studies looking for participants", items: [demoCall, ADULT] },
      "GET /calls/*": (r: Req) => ({ json: new URL(r.url).pathname.endsWith(CALL_ID) ? demoCall : ADULT }),
    });
    await page.goto("/calls");
    const rows = page.getByTestId("call-row");
    await expect(rows.first().getByTestId("verification-label")).toHaveText("Demo, verification simulated");
    await expect(rows.first().getByTestId("verification-label")).toHaveAttribute("data-simulated", "true");
    // A really verified publisher gets no extra mark in the list.
    await expect(rows.nth(1).getByTestId("verification-label")).toHaveCount(0);

    await page.goto(`/calls/${CALL_ID}`);
    const publisher = page.getByTestId("call-publisher").getByTestId("verification-label");
    await expect(publisher).toHaveText(LABEL);
    await expect(publisher).toHaveAttribute("data-simulated", "true");
    await page.getByTestId("signup-start").click();
    const dialog = page.getByTestId("signup-dialog");
    await expect(dialog.getByTestId("verification-label")).toHaveText(LABEL);
    await expect(dialog.getByTestId("verification-label")).toHaveAttribute("data-simulated", "true");
  });

  test("a really verified publisher gets no demo mark in the sign-up", async ({ page }) => {
    const m = mocks();
    await mockApi(page, m.table);
    await page.goto(`/calls/${CALL_ID}`);
    await expect(page.getByTestId("call-publisher").getByTestId("verification-label")).not.toHaveAttribute("data-simulated", "true");
    await page.getByTestId("signup-start").click();
    await expect(page.getByTestId("signup-dialog").getByTestId("signup-recipient")).toBeVisible();
    await expect(page.getByTestId("signup-dialog").getByTestId("verification-label")).toHaveCount(0);
  });

  test("16 or 17: the guardian box is required on the sign-up", async ({ page }) => {
    const m = mocks({ ageGroup: null });
    await mockApi(page, m.table);
    await page.goto(`/calls/${CALL_ID}`);
    await page.getByTestId("signup-start").click();
    await chooseAge(page, "16 or 17");
    const dialog = page.getByTestId("signup-dialog");
    await expect(dialog.getByTestId("signup-guardian-text")).toHaveText(GUARDIAN);
    await dialog.getByTestId("signup-name").fill("Sam");
    await dialog.getByTestId("signup-authorize").click();
    await expect(dialog.getByTestId("signup-send")).toBeDisabled();
    await dialog.getByTestId("signup-guardian").click();
    await dialog.getByTestId("signup-send").click();
    await expect(dialog.getByTestId("signup-sent")).toBeVisible();
    expect(bodies(m.log, "POST", /\/signup$/)[0]).toMatchObject({ guardian_agreed: true });
  });

  test("16 or 17: a call for adults shows the label and no sign-up", async ({ page }) => {
    const m = mocks({ ageGroup: "16_17" });
    await mockApi(page, m.table);
    await page.goto(`/calls/${ADULT_ID}`);
    await expect(page.getByTestId("signup-blocked")).toHaveText(FOR_ADULTS);
    await expect(page.getByTestId("signup-start")).toHaveCount(0);
    await expect(page.getByTestId("call-adults-only")).toHaveCount(0);
  });

  test("experts see no sign-up and the options are never asked for", async ({ page }) => {
    const m = mocks({ role: "researcher" });
    await mockApi(page, m.table);
    await page.goto(`/calls/${CALL_ID}`);
    await expect(page.getByTestId("call-detail")).toBeVisible();
    await expect(page.getByTestId("call-signup-slot")).toHaveCount(0);
    expect(m.log.filter((r) => r.url.endsWith("/signup"))).toHaveLength(0);
  });

  const ERRORS: Array<[string, () => unknown, string]> = [
    ["forbidden (adults)", () => errorEnvelope(403, "forbidden", FOR_ADULTS), "This call is for adults."],
    ["forbidden (role)", () => errorEnvelope(403, "forbidden", "Only patients and caregivers can sign up to calls."), "Only patients and caregivers can sign up."],
    ["guardian", () => errorEnvelope(403, "guardian_agreement_required"), "Tick the parent or guardian box to send."],
    ["not found", () => errorEnvelope(404, "not_found", "This call is closed or does not exist."), "This call is closed or no longer listed."],
    ["expired", () => errorEnvelope(409, "conflict", "This call closed on 2026-10-01 and takes no more sign-ups."), "This call has closed."],
    ["full", () => errorEnvelope(409, "conflict", "This call has all the sign-ups it can take."), "This call is full."],
    ["duplicate", () => errorEnvelope(409, "conflict", "You have already signed up to this call."), "You have already signed up."],
    ["declined", () => errorEnvelope(409, "conflict", "The study team declined your sign-up to this call."), "The study team declined your earlier sign-up."],
    ["own call", () => errorEnvelope(409, "conflict", "You cannot sign up to your own call."), "This is your own call."],
    ["not open yet", () => errorEnvelope(409, "conflict", "Sign-ups open on 2026-11-01."), "Sign-ups have not opened yet."],
    ["card hidden", () => errorEnvelope(409, "conflict", "The team that runs this call cannot receive sign-ups at the moment."), "The study team cannot take sign-ups right now."],
    ["name", () => errorEnvelope(422, "validation_error", "Invalid request fields: display_name"), "Check your name (1 to 60 characters)."],
    ["item", () => errorEnvelope(422, "validation_error", "Invalid request fields: items.0"), "Some items can no longer be shared. Reload the page."],
    ["child", () => errorEnvelope(422, "validation_error", "Invalid request fields: parental_responsibility_confirmed"), "Confirm parental responsibility in your profile first."],
    ["conversations", () => errorEnvelope(429, "rate_limited"), "You can open 5 new conversations a day. Send without one, or try tomorrow."],
  ];
  test("every refusal has its own short message", async ({ page }) => {
    let next: () => unknown = ERRORS[0][1];
    const m = mocks({ signupError: () => next() });
    await mockApi(page, m.table);
    await page.goto(`/calls/${CALL_ID}`);
    await page.getByTestId("signup-start").click();
    const dialog = page.getByTestId("signup-dialog");
    await dialog.getByTestId("signup-name").fill("Leo's mum");
    await dialog.getByTestId("signup-authorize").click();
    await dialog.getByTestId("signup-conversation").click();
    for (const [, mock, text] of ERRORS) {
      next = mock;
      await dialog.getByTestId("signup-send").click();
      await expect(dialog.getByTestId("signup-error")).toHaveText(text);
      // A guardian refusal adds the required box: Send stays off until it is ticked.
      const guardian = dialog.getByTestId("signup-guardian");
      if ((await guardian.count()) && !(await guardian.isChecked())) {
        await expect(dialog.getByTestId("signup-send")).toBeDisabled();
        await guardian.click();
      }
    }
  });

  test("consent_required on send runs the consent again", async ({ page }) => {
    let first = true;
    const m = mocks();
    // The first send finds the consent outdated (changed elsewhere); the second goes through.
    m.table["POST /calls/*/signup"] = (r: Req) => {
      m.log.push(r);
      if (first) {
        first = false;
        m.state.consent = "old";
        return errorEnvelope(403, "consent_required");
      }
      return { status: 201, json: mySignup() };
    };
    await mockApi(page, m.table);
    await page.goto(`/calls/${CALL_ID}`);
    await page.getByTestId("signup-start").click();
    const dialog = page.getByTestId("signup-dialog");
    await dialog.getByTestId("signup-name").fill("Leo's mum");
    await dialog.getByTestId("signup-authorize").click();
    await dialog.getByTestId("signup-send").click();
    await grantConsent(page);
    await expect(dialog.getByTestId("signup-error")).toHaveText("Confirmed. Check and send again.");
    await dialog.getByTestId("signup-send").click();
    await expect(dialog.getByTestId("signup-sent")).toBeVisible();
  });
});

test.describe("my sign-ups", () => {
  test("status, what was shared, the conversation, withdraw with one confirmation; also in the profile", async ({ page }) => {
    const m = mocks({
      mine: [
        mySignup({ thread_id: THREAD_ID }),
        mySignup({ id: "aaaaaaaa-0000-4000-8000-000000000002", call_title: "An earlier trial", status: "declined", call_open: false, shared: { diagnoses: [], genes: [], variants: [], symptoms: [], age_range: null, country: null }, note: null, delete_after: "2026-10-30T09:00:00Z" }),
      ],
    });
    const errors = trackConsoleErrors(page);
    await mockApi(page, m.table);
    await page.goto("/calls");
    await page.getByTestId("my-signups-link").click();
    await expect(page).toHaveURL(/\/calls\/signups$/);
    const items = page.getByTestId("my-signup");
    await expect(items).toHaveCount(2);
    await expect(items.first().getByTestId("my-signup-status")).toHaveText("Signed up");
    await expect(items.first().getByTestId("signup-shared")).toContainText("Dravet syndrome");
    await expect(items.first()).toContainText(NOTE);
    await expect(items.first().getByTestId("my-signup-thread")).toHaveAttribute("href", `/messages/${THREAD_ID}`);
    await expect(items.nth(1).getByTestId("my-signup-status")).toHaveText("Declined by the team");
    await expect(items.nth(1).getByTestId("my-signup-delete-after")).toHaveText("Deleted on 30 Oct 2026");
    await expect(items.nth(1).getByTestId("my-signup-withdraw")).toHaveCount(0);

    await items.first().getByTestId("my-signup-withdraw").click();
    await page.getByTestId("my-signup-confirm-action").click();
    await expect(items.first().getByTestId("my-signup-status")).toHaveText("Withdrawn");
    await expect(items.first()).not.toContainText(NOTE);
    await expect(items.first().getByTestId("my-signup-delete-after")).toBeVisible();
    expect(m.log.filter((r) => r.method === "DELETE").map((r) => new URL(r.url).pathname)).toEqual([`/me/signups/${SIGNUP_ID}`]);

    await page.goto("/profile#signups");
    await expect(page.locator("#signups").getByTestId("my-signup")).toHaveCount(2);
    await expectNothingLeaked(page, m.log);
    expect(errors()).toEqual([]);
  });
});

test.describe("the publisher", () => {
  test("sign-ups per call: count, shared items, note, the 16-17 label, about a child, decline", async ({ page }) => {
    const m = mocks({ role: "researcher" });
    const errors = trackConsoleErrors(page);
    await mockApi(page, m.table);
    await page.goto("/calls/mine");
    await expect(page.getByTestId("call-signups-count")).toHaveText("2 of 50");
    await page.getByTestId("call-signups-toggle").click();
    const rows = page.getByTestId("received-signup");
    await expect(rows).toHaveCount(3);
    await expect(rows.first()).toContainText("Leo's mum");
    await expect(rows.first().getByTestId("signup-shared")).toContainText("SCN1A");
    await expect(rows.first().getByTestId("received-note")).toHaveText(NOTE);
    await expect(rows.first().getByTestId("received-child")).toBeVisible();
    await expect(rows.first().getByTestId("received-thread")).toHaveAttribute("href", `/messages/${THREAD_ID}`);
    await expect(rows.nth(1).getByTestId("received-minor")).toHaveText(MINOR_LABEL);
    await expect(rows.nth(1).getByTestId("received-child")).toHaveCount(0);
    await expect(rows.nth(2).getByTestId("received-status")).toHaveText("Withdrew");
    await expect(rows.nth(2).getByTestId("received-decline")).toHaveCount(0);
    // Nothing that identifies an account.
    await expect(page.getByTestId("call-signups")).not.toContainText("@");

    await rows.first().getByTestId("received-decline").click();
    await page.getByTestId("received-confirm-action").click();
    await expect(rows.first().getByTestId("received-status")).toHaveText("Declined");
    await expect(page.getByTestId("call-signups-count")).toHaveText("1 of 50");
    expect(m.log.filter((r) => r.method === "POST").map((r) => new URL(r.url).pathname)).toEqual([`/me/calls/${CALL_ID}/signups/r1/decline`]);
    expect(errors()).toEqual([]);
  });
});

test.describe("suggestions", () => {
  test("off by default; switching on asks for the consent and shows the backend's sentence; switching off hides it", async ({ page }) => {
    const m = mocks({ consent: "old" });
    const errors = trackConsoleErrors(page);
    await mockApi(page, m.table);
    await page.goto("/calls");
    const sw = page.getByTestId("suggestions-switch");
    await expect(sw).not.toBeChecked();
    await expect(page.getByTestId("suggestions-block")).toHaveCount(0);
    expect(m.log.filter((r) => new URL(r.url).pathname === "/calls/suggested")).toHaveLength(0);

    await sw.click();
    await grantConsent(page);
    await expect(sw).toBeChecked();
    const block = page.getByTestId("suggestions-block");
    await expect(block.getByRole("heading", { name: "Suggested for you" })).toBeVisible();
    await expect(block.getByTestId("suggestion-sentence")).toHaveText(SENTENCE);
    await expect(block.getByTestId("suggestion-info")).toHaveText("Your age range is within the call's ages, your country is not listed.");
    await expect(block).not.toContainText(/eligible\b(?!ility)|recommended|treatment/i);
    // Every call stays listed below.
    await expect(page.getByTestId("calls-list").getByTestId("call-row")).toHaveCount(2);
    expect(bodies(m.log, "PUT", /suggestions$/)).toEqual([{ enabled: true }]);

    await sw.click();
    await expect(sw).not.toBeChecked();
    await expect(page.getByTestId("suggestions-block")).toHaveCount(0);
    expect(bodies(m.log, "PUT", /suggestions$/)).toEqual([{ enabled: true }, { enabled: false }]);
    await expectNothingLeaked(page, m.log);
    expect(errors()).toEqual([]);
  });

  test("experts get no suggestions switch", async ({ page }) => {
    const m = mocks({ role: "doctor" });
    await mockApi(page, m.table);
    await page.goto("/calls");
    await expect(page.getByTestId("calls-browser")).toBeVisible();
    await expect(page.getByTestId("suggestions")).toHaveCount(0);
  });

  test("the bell words a match as a study that may fit and links to the call", async ({ page }) => {
    const m = mocks();
    await mockApi(page, m.table);
    await page.goto("/calls");
    await page.getByTestId("notifications-bell").click();
    const n = page.getByTestId("notification").first();
    await expect(n).toHaveText(`Study that may fit · ${SURVEY.title}(unread)`);
    await expect(n.getByRole("link")).toHaveAttribute("href", `/calls/${CALL_ID}`);
  });
});

test.describe("phone", () => {
  test("sign-up screen, my sign-ups and suggestions fit a phone @mobile", async ({ page }) => {
    const m = mocks({ suggestionsOn: true, mine: [mySignup({ thread_id: THREAD_ID })] });
    await mockApi(page, m.table);
    const noOverflow = async () => expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    await page.goto("/calls");
    await expect(page.getByTestId("suggestion-sentence")).toBeVisible();
    await noOverflow();
    await page.goto("/calls/signups");
    await expect(page.getByTestId("my-signup")).toBeVisible();
    await noOverflow();
    await page.goto(`/calls/${CALL_ID}`);
    await page.getByTestId("signup-start").click();
    await expect(page.getByTestId("signup-dialog")).toBeVisible();
    await noOverflow();
    const box = await page.getByTestId("signup-dialog").boundingBox();
    expect(box!.height).toBeLessThanOrEqual(page.viewportSize()!.height);
  });
});

/** Screenshots for review: light and dark, 1440 and 390 px. */
test.describe("screenshots", () => {
  test.skip(!SHOTS, "set SIGNUPS_SHOTS_DIR");
  for (const theme of ["light", "dark"] as const) {
    for (const width of [1440, 390]) {
      test(`signups screens ${theme} ${width}`, async ({ page }) => {
        const tag = `${width}-${theme}`;
        await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
        await setTheme(page, theme);

        let m = mocks({ suggestionsOn: true });
        await mockApi(page, m.table);
        await page.goto("/calls");
        await expect(page.getByTestId("suggestion-sentence")).toBeVisible();
        await shot(page, `suggestions-${tag}`);

        await page.goto(`/calls/${CALL_ID}`);
        await page.getByTestId("signup-start").click();
        const dialog = page.getByTestId("signup-dialog");
        await dialog.getByTestId("signup-name").fill("Leo's mum");
        await dialog.getByTestId("signup-authorize").click();
        await shot(page, `screen-${tag}`);

        await page.unrouteAll();
        m = mocks({ ageGroup: "16_17" });
        await mockApi(page, m.table);
        await page.goto(`/calls/${CALL_ID}`);
        await page.getByTestId("signup-start").click();
        await expect(page.getByTestId("signup-guardian")).toBeVisible();
        await shot(page, `screen-minor-${tag}`);

        await page.unrouteAll();
        m = mocks({ mine: [mySignup({ thread_id: THREAD_ID }), mySignup({ id: "x2", call_title: "An earlier trial", status: "withdrawn", call_open: false, shared: { diagnoses: [], genes: [], variants: [], symptoms: [], age_range: null, country: null }, note: null, delete_after: "2026-10-30T09:00:00Z" })] });
        await mockApi(page, m.table);
        await page.goto("/calls/signups");
        await expect(page.getByTestId("my-signup")).toHaveCount(2);
        await shot(page, `mine-${tag}`);

        await page.unrouteAll();
        m = mocks({ role: "researcher" });
        await mockApi(page, m.table);
        await page.goto("/calls/mine");
        await page.getByTestId("call-signups-toggle").click();
        await expect(page.getByTestId("received-signup")).toHaveCount(3);
        await shot(page, `publisher-${tag}`);
      });
    }
  }
});
