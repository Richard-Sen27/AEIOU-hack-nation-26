import { expect, test, type Page } from "@playwright/test";

import { errorEnvelope, guestSession, mockApi, setTheme, signedInSession, trackConsoleErrors } from "../helpers";
import { atlasTreePayload, graphMocks, stxbp1Summary, summaryMock } from "../graph/fixtures";
import { CARD_ID, cardBackend, LABELS, publicCard, type Req, verification } from "./fixtures";

const SHOTS = process.env.CARDS_SHOTS_DIR;

const work = (page: Page) => page.locator("#your-work");

test.describe("verification and the public card on the profile", () => {
  test("ORCID: start sends return_to, the confirmed return shows the verified state", async ({ page, baseURL }) => {
    const be = cardBackend({ orcidSimulated: true });
    let startBody: unknown = null;
    await mockApi(page, {
      ...be.mocks,
      "POST /me/professional/orcid/start": (r: Req) => {
        startBody = r.body;
        // The simulated sign-in ends at the backend callback, which redirects back here.
        Object.assign(be.state, { verified: true, method: "orcid_simulated", orcidConfirmed: true });
        return { json: { authorize_url: `${baseURL}/profile?orcid=confirmed`, simulated: true } };
      },
    });
    const errors = trackConsoleErrors(page);
    await page.goto("/profile");
    const w = work(page);
    await expect(w.getByTestId("work-note")).toHaveText("Private to you. Not a verification.");
    await expect(w.getByTestId("orcid-simulated")).toHaveText("Demo: simulated sign-in");
    await expect(w.getByTestId("card-visible")).toBeDisabled();
    await expect(w.getByTestId("card-visible-note")).toHaveText("Confirm who you are first.");

    await w.getByTestId("orcid-start").click();
    await expect(page).toHaveURL(/\/profile#your-work$/);
    expect(startBody).toEqual({ return_to: "/profile" });
    await expect(w.getByTestId("orcid-result")).toHaveText("ORCID iD confirmed.");
    await expect(w.getByTestId("verified").getByTestId("verification-label")).toHaveText(LABELS.orcid_simulated);
    await expect(w.getByTestId("verified").getByTestId("verification-label")).toHaveAttribute("data-simulated", "true");
    // A confirmed ORCID iD is locked in the work details.
    await expect(w.getByRole("textbox", { name: "ORCID iD" })).toHaveAttribute("readonly", "");
    await expect(w.getByTestId("orcid-locked")).toHaveText("Confirmed with ORCID. Locked.");
    await expect(w.getByTestId("remove-ends-card")).toHaveText("Also ends your verification and card.");
    await expect(w.getByTestId("card-visible")).toBeEnabled();
    await expect(page.getByTestId("role-switch-note")).toContainText("Any role change ends your verification and card.");
    expect(errors()).toEqual([]);
  });

  for (const [result, text] of [
    ["denied", "ORCID sign-in was cancelled."],
    ["failed", "ORCID check failed. Please try again."],
    ["already_linked", "This ORCID iD is already confirmed on another Amber account."],
    ["nonsense", "ORCID check failed. Please try again."],
  ] as const) {
    test(`ORCID: ?orcid=${result} is explained and removed from the address`, async ({ page }) => {
      const be = cardBackend();
      await mockApi(page, be.mocks);
      await page.goto(`/profile?orcid=${result}`);
      await expect(work(page).getByTestId("orcid-result")).toHaveText(text);
      await expect(page).toHaveURL(/\/profile#your-work$/);
      await expect(work(page).getByTestId("orcid-start")).toBeVisible();
      await work(page).getByRole("button", { name: "Dismiss" }).click();
      await expect(work(page).getByTestId("orcid-result")).toHaveCount(0);
    });
  }

  test("ORCID: a server without ORCID shows the manual form; a 501 on start is explained", async ({ page }) => {
    const be = cardBackend({ orcidAvailable: false });
    await mockApi(page, be.mocks);
    await page.goto("/profile");
    await expect(work(page).getByTestId("orcid-start")).toHaveCount(0);
    await expect(work(page).getByTestId("request-form")).toBeVisible();

    const be2 = cardBackend();
    await mockApi(page, { ...be2.mocks, "POST /me/professional/orcid/start": errorEnvelope(501, "not_implemented") });
    await page.reload();
    await work(page).getByTestId("orcid-start").click();
    await expect(work(page).getByTestId("verification-error")).toHaveText("ORCID sign-in is not set up on this server.");
  });

  test("manual request: validation, pending, withdraw", async ({ page }) => {
    const be = cardBackend();
    await mockApi(page, be.mocks);
    await page.goto("/profile");
    const w = work(page);
    await expect(w.getByTestId("request-form")).toHaveCount(0);
    await w.getByTestId("request-open").click();
    const form = w.getByTestId("request-form");
    await expect(form.getByTestId("request-simulated")).toHaveCount(0);
    await form.getByRole("textbox", { name: "Work e-mail" }).fill("maria@bch.org");
    await form.getByRole("textbox", { name: "Staff or profile page" }).fill("http://bch.org/maria");
    await expect(form.getByText("Needs an https link.")).toBeVisible();
    await expect(form.getByRole("button", { name: "Send request" })).toBeDisabled();
    await form.getByRole("textbox", { name: "Staff or profile page" }).fill("https://bch.org/maria");
    await form.getByRole("button", { name: "Send request" }).click();

    const pending = w.getByTestId("request-pending");
    await expect(pending).toContainText("Request sent");
    await expect(pending).toContainText("maria@bch.org · https://bch.org/maria");
    await expect(w.getByTestId("orcid-start")).toHaveCount(0);
    expect(be.calls.find((c) => c.method === "POST")?.body).toEqual({ institutional_email: "maria@bch.org", profile_url: "https://bch.org/maria" });
    // Still not verified: the card stays off.
    await expect(w.getByTestId("card-visible")).toBeDisabled();

    await pending.getByRole("button", { name: "Withdraw" }).click();
    await expect(w.getByTestId("request-pending")).toHaveCount(0);
    await expect(w.getByTestId("orcid-start")).toBeVisible();
    expect(be.calls.some((c) => c.method === "DELETE")).toBe(true);
  });

  test("manual request: a rejected request can be dismissed or sent again", async ({ page }) => {
    const be = cardBackend({ request: { status: "rejected", decided_at: "2026-10-04T09:00:00Z" } });
    await mockApi(page, be.mocks);
    await page.goto("/profile");
    const rejected = work(page).getByTestId("request-rejected");
    await expect(rejected).toContainText("Not approved (4 Oct 2026). You can send a new request.");
    await expect(work(page).getByTestId("request-open")).toBeVisible();
    await rejected.getByRole("button", { name: "Dismiss" }).click();
    await expect(work(page).getByTestId("request-rejected")).toHaveCount(0);
    expect(be.calls.some((c) => c.method === "DELETE")).toBe(true);
  });

  test("manual request: the local demo approves at once, marked simulated", async ({ page }) => {
    const be = cardBackend({ orcidSimulated: true }, { autoApprove: true });
    await mockApi(page, be.mocks);
    await page.goto("/profile");
    const w = work(page);
    await w.getByTestId("request-open").click();
    await expect(w.getByTestId("request-simulated")).toHaveText("Demo: approved at once and marked simulated.");
    await w.getByRole("textbox", { name: "Work e-mail" }).fill("maria@bch.org");
    await w.getByRole("textbox", { name: "Staff or profile page" }).fill("https://bch.org/maria");
    await w.getByRole("button", { name: "Send request" }).click();
    await expect(w.getByTestId("verified").getByTestId("verification-label")).toHaveText(LABELS.manual_simulated);
    await expect(page.getByText("Verified (demo, simulated)").first()).toBeVisible();
    await expect(w.getByTestId("card-preview").getByTestId("verification-label")).toHaveText(LABELS.manual_simulated);
    await expect(w.getByTestId("card-preview").getByTestId("card-role")).toContainText("name self-declared");
  });

  test("card: switch on and off, settings, preview and the note", async ({ page }) => {
    const be = cardBackend({ verified: true, method: "orcid", orcidConfirmed: true, atlasLinkVerified: true });
    await mockApi(page, be.mocks);
    const errors = trackConsoleErrors(page);
    await page.goto("/profile");
    const w = work(page);
    const preview = w.getByTestId("card-preview");
    await expect(preview).toContainText("Hidden. Nobody sees it.");
    await expect(w.getByTestId("card-visible-note")).toHaveText("Off. Only signed-in users would see it.");
    await expect(w.getByTestId("card-show-atlas")).toBeVisible();

    await w.getByTestId("card-visible").click();
    await expect(w.getByTestId("card-visible-note")).toHaveText("On. Signed-in users can see it.");
    await expect(w.getByTestId("work-note")).toHaveText("Your public card shows only what you switch on below.");
    await expect(preview).toContainText("What signed-in users see.");
    await expect(preview.getByTestId("card-open")).toHaveAttribute("href", `/people/${CARD_ID}`);
    expect(be.calls.filter((c) => c.method === "PUT").at(-1)?.body).toEqual({
      visible: true,
      headline: null,
      accepts_patient_messages: false,
      show_institutions: true,
      show_atlas_entry: true,
    });

    // Draft settings, then Save.
    await w.getByTestId("card-headline-input").fill("Synaptic epilepsies");
    await w.getByTestId("card-show-institutions").click();
    await w.getByTestId("card-accepts-messages-toggle").click();
    await expect(preview).toContainText("Save to update.");
    await w.getByTestId("card-save").click();
    await expect(w.getByTestId("card-save")).toHaveCount(0);
    expect(be.calls.filter((c) => c.method === "PUT").at(-1)?.body).toEqual({
      visible: true,
      headline: "Synaptic epilepsies",
      accepts_patient_messages: true,
      show_institutions: false,
      show_atlas_entry: true,
    });
    await expect(preview.getByTestId("card-headline")).toHaveText("Synaptic epilepsies");
    await expect(preview.getByTestId("card-institutions")).toHaveCount(0);
    await expect(preview.getByTestId("card-accepts-messages")).toBeVisible();

    // A headline with contact details is refused.
    await w.getByTestId("card-headline-input").fill("mail me at maria@bch.org");
    await w.getByTestId("card-save").click();
    await expect(w.getByTestId("card-error")).toHaveText("The headline can't contain e-mail addresses, links or phone numbers.");

    // Off always works.
    await w.getByTestId("card-visible").click();
    await expect(w.getByTestId("card-visible-note")).toHaveText("Off. Only signed-in users would see it.");
    await expect(w.getByTestId("work-note")).toHaveText("Private to you. Not a verification.");
    expect((be.calls.filter((c) => c.method === "PUT").at(-1)?.body as { visible: boolean }).visible).toBe(false);
    expect(errors().filter((e) => !/422/.test(e))).toEqual([]);
  });

  test("card: blocked reasons and a 409 when the state changed elsewhere", async ({ page }) => {
    const be = cardBackend({ verified: true, method: "orcid", hasName: false });
    await mockApi(page, be.mocks);
    await page.goto("/profile");
    const w = work(page);
    await expect(w.getByTestId("card-visible")).toBeDisabled();
    await expect(w.getByTestId("card-visible-note")).toHaveText("Add your name above first.");
    await expect(w.getByTestId("card-preview")).toHaveCount(0);
    await expect(w.getByTestId("card-headline-input")).toHaveCount(0);

    // Verified when the page loaded, revoked before the switch: 409, then the fresh state.
    be.state.hasName = true;
    await page.reload();
    await expect(w.getByTestId("card-visible")).toBeEnabled();
    be.state.verified = false;
    await w.getByTestId("card-visible").click();
    await expect(w.getByTestId("card-error")).toHaveText("Confirm your identity first.");
    await expect(w.getByTestId("card-visible-note")).toHaveText("Confirm who you are first.");
    await expect(w.getByTestId("card-visible")).toBeDisabled();
  });

  test("work details: editing a reviewed name says it ends the verification", async ({ page }) => {
    const be = cardBackend({ verified: true, method: "institutional_email" });
    await mockApi(page, be.mocks);
    await page.goto("/profile");
    const w = work(page);
    await expect(w.getByTestId("reviewed-note")).toHaveText("Changing your name or institutions ends it.");
    await expect(w.getByRole("textbox", { name: "ORCID iD" })).not.toHaveAttribute("readonly", "");
    await expect(w.getByTestId("save-ends-verification")).toHaveCount(0);
    await w.getByRole("textbox", { name: "Last name" }).fill("Exampel");
    await expect(w.getByTestId("save-ends-verification")).toHaveText("Saving ends your verification.");
  });

  test("patients never see verification or card options", async ({ page }) => {
    const be = cardBackend({}, { role: "patient" });
    await mockApi(page, be.mocks);
    await page.goto("/profile");
    await expect(page.locator("#health-profile")).toBeVisible();
    await expect(page.locator("#your-work")).toHaveCount(0);
    await expect(page.getByTestId("card-section")).toHaveCount(0);
    await expect(page.getByTestId("orcid-start")).toHaveCount(0);
    expect(be.calls).toEqual([]);
  });
});

test.describe("the card page", () => {
  test("shows the card as the backend words it, the same as the owner's preview", async ({ page }) => {
    const be = cardBackend({ verified: true, method: "orcid", orcidConfirmed: true, atlasLinkVerified: true, visible: true, cardId: CARD_ID, headline: "Synaptic epilepsies", accepts: true });
    await mockApi(page, be.mocks);
    const errors = trackConsoleErrors(page);
    await page.goto("/profile");
    const previewText = await work(page)
      .getByTestId("card-preview")
      .getByTestId("public-card")
      .evaluate((el) => (el.textContent ?? "").replace(/\s+/g, " ").trim());
    expect(previewText).toContain("Synaptic epilepsies");

    await page.goto(`/people/${CARD_ID}`);
    const card = page.getByTestId("public-card");
    await expect(card.getByRole("heading", { level: 1 })).toHaveText("Maria Example");
    await expect(card.getByTestId("card-role")).toHaveText("Researcher (self-declared)");
    await expect(card.getByTestId("verification-label")).toHaveText(LABELS.orcid);
    await expect(card.getByTestId("card-headline")).toHaveText("Synaptic epilepsies");
    await expect(card.getByTestId("card-institutions").getByRole("listitem")).toHaveText(["Boston Children's Hospital", "St. Jude Research"]);
    await expect(card.getByRole("link", { name: "Boston Children's Hospital" })).toHaveAttribute("href", "/node/INST%3Abch");
    await expect(card.getByTestId("card-atlas-link")).toHaveAttribute("href", "/node/RES%3A0001");
    await expect(card.getByTestId("card-orcid-link")).toHaveAttribute("href", "https://orcid.org/0000-0002-1825-0097");
    await expect(card.getByTestId("card-accepts-messages")).toBeVisible();
    // The page renders the same component and data: equal apart from slots added by later stages.
    const text = (el: Element) => {
      const c = el.cloneNode(true) as HTMLElement;
      c.querySelectorAll("[data-slot]").forEach((s) => s.remove());
      return (c.textContent ?? "").replace(/\s+/g, " ").trim();
    };
    expect(await card.evaluate(text)).toBe(previewText);
    expect(errors()).toEqual([]);
  });

  test("a simulated verification is marked; no email or user id anywhere", async ({ page }) => {
    await mockApi(page, {
      "GET /auth/session": signedInSession(),
      "GET /people/*": publicCard({ verification: verification("orcid_simulated"), institutions: [], headline: null, atlas_node_id: null, atlas_node_label: null }),
    });
    await page.goto(`/people/${CARD_ID}`);
    const label = page.getByTestId("public-card").getByTestId("verification-label");
    await expect(label).toHaveText(LABELS.orcid_simulated);
    await expect(label).toHaveAttribute("data-simulated", "true");
    await expect(page.getByTestId("card-institutions")).toHaveCount(0);
    await expect(page.getByTestId("card-headline")).toHaveCount(0);
    await expect(page.getByTestId("public-card")).not.toContainText("@");
  });

  test("a card that is not shown is a 404, not an error page", async ({ page }) => {
    await mockApi(page, { "GET /auth/session": signedInSession(), "GET /people/*": errorEnvelope(404, "not_found") });
    await page.goto(`/people/${CARD_ID}`);
    await expect(page.getByTestId("card-error")).toContainText("This card is not shown");
    await expect(page.getByTestId("public-card")).toHaveCount(0);
  });

  test("guests get the sign-in prompt and no card request", async ({ page }) => {
    let fetched = false;
    await mockApi(page, {
      "GET /auth/session": guestSession,
      "GET /people/*": () => {
        fetched = true;
        return { json: publicCard() };
      },
    });
    await page.goto(`/people/${CARD_ID}`);
    await expect(page.getByTestId("sign-in-prompt")).toContainText("Sign in to see this card");
    expect(fetched).toBe(false);
  });

  test("accounts without the age check go to the welcome flow", async ({ page }) => {
    let fetched = false;
    await mockApi(page, {
      "GET /auth/session": signedInSession({ age_confirmed: false }),
      "GET /people/*": () => {
        fetched = true;
        return { json: publicCard() };
      },
    });
    await page.goto(`/people/${CARD_ID}`);
    await expect(page).toHaveURL(new RegExp(`/welcome\\?next=${encodeURIComponent(`/people/${CARD_ID}`)}`));
    expect(fetched).toBe(false);
  });
});

test.describe("Reachable in Amber", () => {
  const DRAVET = "/node/MONDO%3A0100135";
  const experts = [
    publicCard(),
    publicCard({ card_id: "33333333-3333-4333-8333-333333333333", role: "doctor", name: "Dr. Lee Demo", institutions: [], verification: verification("manual_simulated") }),
  ];

  test("lists the experts with a card on the disease page", async ({ page }) => {
    let query = "";
    await mockApi(page, graphMocks({
      "GET /auth/session": signedInSession({ role: "patient" }),
      "GET /people": (r: Req) => {
        query = new URL(r.url).searchParams.get("disease") ?? "";
        return { json: { disease_id: query, items: experts } };
      },
    }));
    await page.goto(DRAVET);
    const section = page.getByTestId("reachable-in-amber");
    await expect(section.getByRole("heading", { name: "Reachable in Amber" })).toBeVisible();
    const people = section.getByTestId("reachable-person");
    await expect(people).toHaveCount(2);
    await expect(people.first()).toHaveAttribute("href", `/people/${CARD_ID}`);
    await expect(people.first()).toContainText("Researcher · Boston Children's Hospital");
    await expect(people.nth(1).getByTestId("verification-label")).toHaveText("Demo, verification simulated");
    expect(query).toBe("MONDO:0100135");
  });

  test("nothing for guests and nothing when nobody is listed", async ({ page }) => {
    let calls = 0;
    const people = () => {
      calls++;
      return { json: { disease_id: "MONDO:0100135", items: [] } };
    };
    await mockApi(page, graphMocks({ "GET /people": people }));
    await page.goto(DRAVET);
    await expect(page.getByRole("heading", { level: 1, name: "Dravet syndrome" })).toBeVisible();
    await expect(page.getByTestId("reachable-in-amber")).toHaveCount(0);
    expect(calls).toBe(0);

    await mockApi(page, graphMocks({ "GET /auth/session": signedInSession(), "GET /people": people }));
    await page.reload();
    await expect(page.getByRole("heading", { level: 1, name: "Dravet syndrome" })).toBeVisible();
    await expect.poll(() => calls).toBeGreaterThan(0);
    await expect(page.getByTestId("reachable-in-amber")).toHaveCount(0);
  });

  test("the Atlas panel shows the chip only on items with a card", async ({ page }) => {
    const summary = stxbp1Summary();
    const researchers = summary.sections.find((s) => s.key === "researchers")!;
    researchers.items[0] = { ...researchers.items[0], card_id: CARD_ID } as typeof researchers.items[0];
    await mockApi(page, {
      "GET /auth/session": signedInSession({ role: "researcher" }),
      "GET /atlas/tree.json": atlasTreePayload(),
      "GET /atlas/summary/*": summaryMock({ "MONDO:9900007": { json: summary } }),
      "GET /chat/sessions": [],
      "GET /people/*": publicCard({ verification: verification("orcid_simulated") }),
    });
    await page.goto("/atlas?focus=MONDO:9900007");
    const section = page.getByTestId("atlas-panel").locator('[data-section="researchers"]');
    await expect(section.getByTestId("atlas-summary-item")).toHaveCount(2);
    const chip = section.getByTestId("in-amber-chip");
    await expect(chip).toHaveCount(1);
    await expect(chip).toHaveAttribute("href", `/people/${CARD_ID}`);
    await expect(chip).toContainText("In Amber · Demo, verification simulated");
    await expect(chip).toHaveAttribute("data-simulated", "true");
    await expect(section.getByTestId("atlas-summary-item").first().getByTestId("in-amber-chip")).toHaveCount(1);
    await expect(section.getByTestId("atlas-summary-item").nth(1).getByTestId("in-amber-chip")).toHaveCount(0);
  });
});

// ---------------------------------------------------------------------------
// Screenshots (only with CARDS_SHOTS_DIR set): profile panel, card page, disease section.

for (const theme of ["light", "dark"] as const) {
  for (const width of [1440, 390] as const) {
    test(`screenshots ${theme} ${width}`, async ({ page }) => {
      test.skip(!SHOTS, "set CARDS_SHOTS_DIR to take screenshots");
      await setTheme(page, theme);
      await page.setViewportSize({ width, height: 900 });
      const be = cardBackend({ verified: true, method: "orcid_simulated", orcidConfirmed: true, atlasLinkVerified: true, visible: true, cardId: CARD_ID, headline: "Synaptic epilepsies, STXBP1 natural history", accepts: true });
      await mockApi(page, {
        ...graphMocks(),
        ...be.mocks,
        "GET /people": { disease_id: "MONDO:0100135", items: [publicCard(), publicCard({ card_id: "33333333-3333-4333-8333-333333333333", role: "doctor", name: "Dr. Lee Demo", institutions: [], verification: verification("manual_simulated") })] },
      });
      await page.goto("/profile");
      const w = work(page);
      await expect(w.getByTestId("card-preview")).toBeVisible();
      await w.screenshot({ path: `${SHOTS}/cards-profile-${theme}-${width}.png`, animations: "disabled" });

      await page.goto(`/people/${CARD_ID}`);
      await expect(page.getByTestId("public-card")).toBeVisible();
      await page.screenshot({ path: `${SHOTS}/cards-page-${theme}-${width}.png`, animations: "disabled" });

      // The unverified state: ORCID button and the manual form.
      be.state.verified = false;
      be.state.method = null;
      be.state.orcidConfirmed = false;
      be.state.visible = false;
      be.state.orcidSimulated = true;
      await page.goto("/profile");
      await work(page).getByTestId("request-open").click();
      await work(page).getByTestId("card-section").screenshot({ path: `${SHOTS}/cards-verify-${theme}-${width}.png`, animations: "disabled" });

      await page.goto("/node/MONDO%3A0100135");
      await expect(page.getByTestId("reachable-in-amber")).toBeVisible();
      await page.screenshot({ path: `${SHOTS}/cards-disease-${theme}-${width}.png`, animations: "disabled" });
    });
  }
}
