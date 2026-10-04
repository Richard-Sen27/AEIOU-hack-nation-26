import { expect, test } from "@playwright/test";

import { errorEnvelope, guestSession, hit, mockApi, setTheme, shot, signedInSession, trackConsoleErrors } from "../helpers";

test.describe("welcome", () => {
  test("first sign-in: plan notice, role, 16+, language, continue", async ({ page }) => {
    let settings: Record<string, unknown> | null = null;
    let session = signedInSession({ role: null, age_confirmed: false });
    await mockApi(page, {
      "GET /auth/session": () => ({ json: session }),
      "PATCH /me/settings": (req: { body: unknown }) => {
        settings = req.body as Record<string, unknown>;
        session = signedInSession({ role: "doctor", age_confirmed: true, language: "de" });
        return { json: session.user };
      },
    });
    const errors = trackConsoleErrors(page);
    await page.goto("/welcome?next=%2Fprivacy");

    const notice = page.getByTestId("chatgpt-plan-notice");
    await expect(notice).toBeVisible();
    await expect(notice).toContainText("You're using your ChatGPT plan");
    await expect(notice).toContainText("Eligible usage in this app uses your ChatGPT plan. Manage usage in your ChatGPT settings.");
    await notice.getByRole("button", { name: "Got it" }).click();
    await expect(notice).toBeHidden();

    // Nothing pre-selected.
    await expect(page.getByRole("radio", { checked: true })).toHaveCount(0);
    await expect(page.getByRole("checkbox", { name: /16 or older/ })).not.toBeChecked();

    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByText("Please choose one.")).toBeVisible();
    expect(settings).toBeNull();

    await page.getByRole("radio", { name: "Doctor" }).click();
    await page.getByRole("checkbox", { name: /16 or older/ }).click();
    await page.getByLabel(/Dr. Wu answers/).selectOption("de");
    await page.getByRole("button", { name: "Continue" }).click();

    // Doctors get the optional work step; skipping goes on.
    await expect(page.getByTestId("welcome-work-step")).toBeVisible();
    expect(settings).toEqual({ role: "doctor", language: "de", age_confirmed_16: true });
    await page.getByRole("button", { name: "Skip for now" }).click();
    await expect(page).toHaveURL(/\/privacy$/);
    expect(errors()).toEqual([]);
  });

  test("an incomplete account is routed to /welcome and back", async ({ page }) => {
    await mockApi(page, {
      "GET /auth/session": signedInSession({ role: "patient", age_confirmed: false }),
      "GET /documents": [],
    });
    await page.goto("/documents");
    await expect(page).toHaveURL(/\/welcome\?next=%2Fdocuments$/);
    // Not the first sign-in (role exists): no plan notice again.
    await expect(page.getByTestId("chatgpt-plan-notice")).toHaveCount(0);
    await expect(page.getByRole("radio", { name: "Patient or family" })).toBeChecked();
  });

  test("notices stay readable without completing welcome", async ({ page }) => {
    await mockApi(page, { "GET /auth/session": signedInSession({ role: null, age_confirmed: false }) });
    await page.goto("/privacy");
    await page.waitForTimeout(500);
    await expect(page).toHaveURL(/\/privacy$/);
  });

  test("guest sees a sign-in prompt", async ({ page }) => {
    await mockApi(page, { "GET /auth/session": guestSession });
    await page.goto("/welcome");
    const prompt = page.getByTestId("sign-in-prompt");
    await expect(prompt.getByRole("button", { name: "Continue with ChatGPT" })).toBeVisible();
  });

  test("under 16 can delete the account", async ({ page }) => {
    let deleted = false;
    await mockApi(page, {
      "GET /auth/session": signedInSession({ role: null, age_confirmed: false }),
      "DELETE /me": () => {
        deleted = true;
        return { status: 204, body: "" };
      },
      "POST /auth/logout": { status: 204, body: "" },
    });
    await page.goto("/welcome");
    await page.getByTestId("chatgpt-plan-notice").getByRole("button", { name: "Got it" }).click();
    await page.getByText("I am under 16").click();
    await page.getByTestId("delete-account").click();
    await page.getByRole("button", { name: "Delete everything" }).click();
    await expect(page).toHaveURL(/127\.0\.0\.1:\d+\/$/);
    expect(deleted).toBe(true);
  });
});

const SUGGESTED = { first_name: "Maria", last_name: "Example", source: "chatgpt" };
const EMPTY_WORK = { first_name: null, last_name: null, institutions: [], orcid_id: null, atlas_node_id: null, linked_entry: null, linked_entry_missing: false, updated_at: null, suggested: SUGGESTED };
const CANDIDATES = [
  { node_id: "RES:0001", type: "researcher", label: "Maria Example", orcid_id: "0000-0002-1825-0097", institutions: [{ node_id: "INST:bch", label: "Boston Children's Hospital" }], matched_by: "orcid" },
  { node_id: "DOC:0002", type: "doctor", label: "Maria Example", orcid_id: null, institutions: [], matched_by: "name" },
];

/** First sign-in up to the work step, with every API URL recorded. */
async function toWorkStep(page: import("@playwright/test").Page, role: "Doctor" | "Researcher" | "Patient or family", mocks: Record<string, unknown> = {}) {
  let session = signedInSession({ role: null, age_confirmed: false });
  const urls: string[] = [];
  page.on("request", (r) => urls.push(decodeURIComponent(r.url())));
  await mockApi(page, {
    "GET /auth/session": () => ({ json: session }),
    "PATCH /me/settings": (req: { body: unknown }) => {
      const body = req.body as { role: string };
      session = signedInSession({ role: body.role, age_confirmed: true });
      return { json: session.user };
    },
    "GET /me/professional": EMPTY_WORK,
    "GET /search": (req: { url: string }) => {
      const url = new URL(req.url);
      if (url.searchParams.getAll("types").join() !== "institution") return { json: { results: [] } };
      return /boston/i.test(url.searchParams.get("q") ?? "") ? { json: { results: [hit("INST:bch", "institution", "Boston Children's Hospital")] } } : { json: { results: [] } };
    },
    ...mocks,
  });
  await page.goto("/welcome?next=%2Fprivacy");
  await page.getByTestId("chatgpt-plan-notice").getByRole("button", { name: "Got it" }).click();
  await page.getByRole("radio", { name: role }).click();
  await page.getByRole("checkbox", { name: /16 or older/ }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  return urls;
}

test.describe("welcome: work details", () => {
  test("doctor: prefilled names, institutions, ORCID, candidates, Save sends the body", async ({ page }) => {
    let matchBody: Record<string, unknown> | null = null;
    let put: Record<string, unknown> | null = null;
    const errors = trackConsoleErrors(page);
    const urls = await toWorkStep(page, "Doctor", {
      "POST /me/professional/matches": (req: { body: unknown }) => {
        matchBody = req.body as Record<string, unknown>;
        return { json: { candidates: CANDIDATES } };
      },
      "PUT /me/professional": (req: { body: unknown }) => {
        put = req.body as Record<string, unknown>;
        return { json: { ...EMPTY_WORK, first_name: "Maria", last_name: "Exampel", updated_at: "2026-10-04T12:00:00Z" } };
      },
    });
    const step = page.getByTestId("welcome-work-step");
    await expect(step.getByRole("heading", { name: "About your work (optional)" })).toBeFocused();
    await expect(step).toContainText("Private to you. Not a verification.");
    await expect(step.getByRole("textbox", { name: "First name" })).toHaveValue("Maria");
    await expect(step.getByRole("textbox", { name: "Last name" })).toHaveValue("Example");
    await expect(step).toContainText("From your ChatGPT account. Edit as needed.");
    await expect(step).toContainText("Used to find your entry in the atlas.");

    // An atlas institution, then one the search never sees ("St. Jude" reads like a sentence).
    await page.getByTestId("picker-institution").getByRole("combobox").fill("Boston");
    await page.getByRole("option", { name: /Boston Children's Hospital/ }).click();
    await page.getByTestId("picker-institution").getByRole("combobox").fill("St. Jude Research");
    await page.getByRole("option", { name: "Use “St. Jude Research” as typed" }).click();
    await expect(step.getByTestId("work-institution")).toHaveCount(2);

    // A pasted ORCID link is accepted and shortened; a bad check digit is flagged.
    const orcid = step.getByRole("textbox", { name: "ORCID iD" });
    await orcid.fill("0000-0002-1825-0098");
    await orcid.blur();
    await expect(step.getByText("Not a valid ORCID iD.")).toBeVisible();
    await orcid.fill("https://orcid.org/0000-0002-1825-0097");
    await orcid.blur();
    await expect(orcid).toHaveValue("0000-0002-1825-0097");
    await expect(step.getByText("Not a valid ORCID iD.")).toHaveCount(0);

    await step.getByRole("button", { name: "Find me in the atlas" }).click();
    const list = step.getByTestId("candidates");
    await expect(list.getByTestId("candidate")).toHaveCount(2);
    await expect(list.getByTestId("candidate").first()).toContainText("Same ORCID iD");
    await expect(list.getByRole("radio", { name: "None of these" })).toBeChecked();
    expect(matchBody).toEqual({
      first_name: "Maria",
      last_name: "Example",
      orcid_id: "0000-0002-1825-0097",
      institutions: [{ node_id: "INST:bch" }, { label: "St. Jude Research" }],
    });
    await list.getByTestId("candidate").first().click();
    await expect(list.getByRole("radio", { name: "Maria Example" }).first()).toBeChecked();

    await step.getByRole("textbox", { name: "Last name" }).fill("Exampel");
    await step.getByRole("button", { name: "Save" }).click();
    await expect(page).toHaveURL(/\/privacy$/);
    expect(put).toEqual({
      first_name: "Maria",
      last_name: "Exampel",
      orcid_id: "0000-0002-1825-0097",
      institutions: [{ node_id: "INST:bch" }, { label: "St. Jude Research" }],
      atlas_node_id: "RES:0001",
    });
    // Names only ever travel in request bodies.
    for (const name of ["Maria", "Example", "Exampel"]) {
      expect(urls.filter((u) => u.includes(name)), `URL contains ${name}`).toEqual([]);
    }
    expect(errors()).toEqual([]);
  });

  test("researcher: Skip for now saves nothing and goes on", async ({ page }) => {
    let put = false;
    await toWorkStep(page, "Researcher", {
      "PUT /me/professional": () => {
        put = true;
        return { json: EMPTY_WORK };
      },
    });
    await expect(page.getByTestId("welcome-work-step")).toBeVisible();
    await page.getByRole("button", { name: "Skip for now" }).click();
    await expect(page).toHaveURL(/\/privacy$/);
    expect(put).toBe(false);
  });

  test("patient: no work step", async ({ page }) => {
    let fetched = false;
    await toWorkStep(page, "Patient or family", {
      "GET /me/professional": () => {
        fetched = true;
        return errorEnvelope(403, "forbidden");
      },
    });
    await expect(page).toHaveURL(/\/privacy$/);
    await expect(page.getByTestId("welcome-work-step")).toHaveCount(0);
    expect(fetched).toBe(false);
  });

  test("no candidates, then the rate limit, are said plainly", async ({ page }) => {
    let calls = 0;
    await toWorkStep(page, "Doctor", {
      "POST /me/professional/matches": () => (++calls === 1 ? { json: { candidates: [] } } : errorEnvelope(429, "rate_limited")),
    });
    const step = page.getByTestId("welcome-work-step");
    await step.getByRole("button", { name: "Find me in the atlas" }).click();
    await expect(step.getByTestId("no-candidates")).toHaveText("No entry found.");
    await step.getByRole("button", { name: "Find me in the atlas" }).click();
    await expect(step.getByRole("alert")).toHaveText("Too many searches. Please try again in an hour.");
    // Without both names (and no ORCID) there is nothing to match on.
    await step.getByRole("textbox", { name: "Last name" }).fill("");
    await expect(step.getByRole("button", { name: "Find me in the atlas" })).toBeDisabled();
  });

  test("a load error still lets you skip", async ({ page }) => {
    await toWorkStep(page, "Doctor", { "GET /me/professional": "offline" });
    const step = page.getByTestId("welcome-work-step");
    await expect(step.getByTestId("work-details-error")).toContainText("not reachable");
    await step.getByRole("button", { name: "Skip for now" }).click();
    await expect(page).toHaveURL(/\/privacy$/);
  });
});

test.describe("consent dialog", () => {
  for (const type of ["health_data", "contribute"] as const) {
    test(`${type}: notice content, no pre-ticked boxes, child needs parental confirmation`, async ({ page }) => {
      let granted: Record<string, unknown> | null = null;
      await mockApi(page, {
        "GET /auth/session": signedInSession(),
        "GET /profile": {},
        "GET /consents": [],
        "GET /contributions": [],
        "POST /consents": (req: { body: unknown }) => {
          granted = req.body as Record<string, unknown>;
          return { status: 201, json: { id: "c1", ...granted, granted_at: new Date().toISOString(), active: true } };
        },
      });
      const errors = trackConsoleErrors(page);
      await page.goto("/profile");
      await page.getByTestId(`grant-${type}`).click();
      const dialog = page.getByTestId("consent-dialog");
      await expect(dialog).toBeVisible();

      for (const text of ["What we process", "Why", "How it is protected", "How long we keep it", "Withdrawing"]) {
        await expect(dialog.getByRole("heading", { name: text, exact: true })).toBeVisible();
      }
      await expect(dialog).toContainText("Nothing is sold or shared");
      await expect(dialog.getByRole("link", { name: "privacy notice" })).toHaveAttribute("href", "/privacy");
      if (type === "health_data") {
        await expect(dialog).toContainText("What you type to Dr. Wu");
        await expect(dialog).toContainText("removed on our server before any AI model sees your text or documents");
        await expect(dialog).toContainText("Original files are deleted right after the text is extracted");
        await expect(dialog).toContainText("unless you separately agree to contribute");
      } else {
        await expect(dialog).toContainText("labelled patient-reported");
      }

      // Nothing pre-ticked, grant disabled.
      await expect(dialog.getByRole("checkbox", { checked: true })).toHaveCount(0);
      await expect(dialog.getByRole("radio", { checked: true })).toHaveCount(0);
      const grant = dialog.getByRole("button", { name: "I agree, continue" });
      await expect(grant).toBeDisabled();

      await dialog.getByRole("radio", { name: "A child I care for" }).click();
      await dialog.getByRole("checkbox", { name: /explicitly consent/ }).click();
      await expect(grant).toBeDisabled(); // parental responsibility still missing
      await dialog.getByRole("checkbox", { name: /parental responsibility/ }).click();
      await expect(grant).toBeEnabled();
      await grant.click();
      await expect(dialog).toBeHidden();
      expect(granted).toEqual({
        consent_type: type,
        version: type === "health_data" ? "health-data-2026-10-04" : "contribute-2026-10-04",
        about_child: true,
        parental_responsibility_confirmed: true,
      });
      expect(errors()).toEqual([]);
    });
  }

  test("declining is one click and grants nothing", async ({ page }) => {
    let posted = false;
    await mockApi(page, {
      "GET /auth/session": signedInSession(),
      "GET /profile": {},
      "GET /consents": [],
      "GET /contributions": [],
      "POST /consents": () => {
        posted = true;
        return { status: 201, json: {} };
      },
    });
    await page.goto("/profile");
    await page.getByTestId("grant-health_data").click();
    const dialog = page.getByTestId("consent-dialog");
    await dialog.getByRole("button", { name: "Not now" }).click();
    await expect(dialog).toBeHidden();
    expect(posted).toBe(false);
  });

  test("screenshots: both dialogs, light and dark", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockApi(page, {
      "GET /auth/session": signedInSession(),
      "GET /profile": {},
      "GET /consents": [],
      "GET /contributions": [],
    });
    for (const theme of ["light", "dark"] as const) {
      await setTheme(page, theme);
      for (const type of ["health_data", "contribute"] as const) {
        await page.goto("/profile");
        await page.getByTestId(`grant-${type}`).click();
        await page.getByTestId("consent-dialog").getByRole("radio", { name: "A child I care for" }).click();
        await shot(page, `account-consent-${type}-${theme}`);
      }
      await page.goto("/welcome");
    }
  });
});

test("welcome and consent on a phone @mobile", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockApi(page, {
    "GET /auth/session": signedInSession({ role: null, age_confirmed: false }),
    "GET /profile": {},
    "GET /consents": [],
    "GET /contributions": [],
  });
  await page.goto("/welcome");
  await expect(page.getByTestId("chatgpt-plan-notice")).toBeVisible();
  await shot(page, "account-welcome-notice-mobile");
  await page.getByRole("button", { name: "Got it" }).click();
  await shot(page, "account-welcome-mobile", { fullPage: true });
});

test("screenshots: welcome light and dark", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockApi(page, { "GET /auth/session": signedInSession({ role: null, age_confirmed: false }) });
  for (const theme of ["light", "dark"] as const) {
    await setTheme(page, theme);
    await page.goto("/welcome");
    await expect(page.getByTestId("chatgpt-plan-notice")).toBeVisible();
    await shot(page, `account-welcome-notice-${theme}`);
    await page.getByRole("button", { name: "Got it" }).click();
    await page.getByRole("radio", { name: "Patient or family" }).click();
    await shot(page, `account-welcome-${theme}`, { fullPage: true });
  }
});
