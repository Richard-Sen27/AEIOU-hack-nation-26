import { expect, test, type Page } from "@playwright/test";

import { guestSession, mockApi, recordReveal, revealSamples, setTheme, signedInSession, sseBody, trackConsoleErrors } from "../helpers";
import { atlasTreePayload, summaryMock } from "./fixtures";

const STORY = "My daughter has seizures since birth and I think it is a channel disorder.";
// On the map: a disease, a gene and a patient group. Not on the map: the made-up id.
const FOUND = ["MONDO:9900007", "HGNC:11444", "ORG:fx-stxbp1-parents"];
const MISSING = "MONDO:0000000";

const reply = {
  summary: "These conditions share a cause with what you describe.",
  uncertainty: null,
  chips: [
    { type: "symptom", id: "HP:0001250", label: "Seizure", negated: false, confirmed: false },
    { type: "symptom", id: "HP:0011968", label: "Feeding difficulties", negated: true, confirmed: false },
  ],
  claims: [],
  contradictions: [],
  missing_evidence: [],
  cards: [{ type: "patient_group", node_ids: ["ORG:fx-stxbp1-parents", MISSING], edge_ids: [] }],
  graph_focus: { node_ids: ["MONDO:9900007", "HGNC:11444", MISSING], highlight_path: ["e_e5f778ac8a21"] },
  actions: [],
  follow_up: null,
  ai_notice: null,
  gap_search: null,
  kind: "answer",
};

const turnBody = sseBody([
  { type: "status", tool: "resolve_to_ids", message: "Matching it to the atlas" },
  { type: "summary_delta", text: reply.summary },
  { type: "final", reply, session_id: "11111111-1111-4111-8111-111111111111", message_id: "22222222-2222-4222-8222-222222222222" },
]);

async function atlas(page: Page, mocks: Record<string, unknown> = {}, session: unknown = guestSession) {
  await mockApi(page, {
    "GET /auth/session": session,
    "GET /atlas/tree.json": atlasTreePayload(),
    "GET /atlas/summary/*": summaryMock(),
    "GET /chat/sessions": [],
    ...mocks,
  });
}

const dock = (page: Page) => page.getByTestId("atlas-wu-dock");

async function ask(page: Page, text = STORY) {
  await dock(page).getByTestId("atlas-wu-open").click();
  const box = dock(page).getByRole("textbox", { name: "Message Dr. Wu" });
  await box.fill(text);
  await box.press("Enter");
}

test.describe("atlas Dr. Wu dock", () => {
  test("guests get the sign-in offer with the AI disclosure", async ({ page }) => {
    await atlas(page);
    const errors = trackConsoleErrors(page);
    await page.goto("/atlas");
    await expect(dock(page)).toHaveAttribute("data-tour", "wu");
    await dock(page).getByRole("button", { name: "Ask Dr. Wu" }).click();
    const guest = dock(page).getByTestId("atlas-wu-guest");
    await expect(guest).toBeVisible();
    await expect(dock(page).getByTestId("ai-disclosure")).toHaveCount(1);
    await expect(dock(page).getByTestId("ai-disclosure")).toContainText("Dr. Wu is an AI, not a doctor.");
    await expect(guest.getByRole("button", { name: "Continue with ChatGPT" })).toBeVisible();
    await expect(dock(page).getByRole("textbox")).toHaveCount(0);
    expect(errors()).toEqual([]);
  });

  test("the first message asks for the health-data consent and keeps the text", async ({ page }) => {
    let posted = false;
    await atlas(page, { "POST /chat": () => ((posted = true), turnBody) }, signedInSession({ consents: [] }));
    await page.goto("/atlas");
    await ask(page);
    const dialog = page.getByTestId("consent-dialog");
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Not now" }).click();
    await expect(dock(page).getByRole("textbox", { name: "Message Dr. Wu" })).toHaveValue(STORY);
    expect(posted).toBe(false);
  });

  test("a reply's finds are listed, selectable and never reach the URL or storage", async ({ page }) => {
    const urls: string[] = [];
    page.on("request", (r) => urls.push(r.url()));
    await atlas(page, { "POST /chat": turnBody }, signedInSession({ consents: ["health_data"] }));
    const errors = trackConsoleErrors(page);
    await page.goto("/atlas");
    await ask(page);

    await expect(dock(page).getByTestId("atlas-wu-turn")).toHaveAttribute("data-phase", "done");
    await expect(dock(page).getByTestId("summary")).toHaveText(reply.summary);
    // graph_focus + cards + non-negated chips that are on the map: 3 + the Seizure chip.
    const found = dock(page).getByTestId("atlas-wu-found");
    await expect(found).toContainText("Dr. Wu found 4");
    await expect(found.getByTestId("atlas-wu-found-item")).toHaveText([
      /STXBP1 encephalopathy/,
      /^STXBP1/,
      /STXBP1 Parents Group/,
      /Seizure/,
    ]);
    // No link in the dock carries a found id.
    const hrefs = await dock(page).locator("a").evaluateAll((as) => as.map((a) => a.getAttribute("href") ?? ""));
    for (const id of [...FOUND, "HP:0001250"]) expect(hrefs.some((h) => decodeURIComponent(h).includes(id))).toBe(false);

    // Selecting a find opens it in the panel without writing it to the URL.
    await found.getByTestId("atlas-wu-found-item").first().click();
    await expect(page.getByTestId("atlas-panel").getByRole("heading", { name: "STXBP1 encephalopathy" })).toBeVisible();
    const url = decodeURIComponent(page.url());
    expect(url).not.toContain("focus");
    for (const id of [...FOUND, "HP:0001250"]) expect(url).not.toContain(id);
    // Only the summary endpoint sees the selected (public) id, never a page URL or query.
    expect(urls.some((u) => /daughter|seizures/i.test(decodeURIComponent(u)))).toBe(false);
    const stored = await page.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }));
    for (const id of FOUND) expect(stored).not.toContain(id);
    expect(stored).not.toMatch(/daughter|seizures/i);

    // Clear.
    await page.getByTestId("atlas-panel").getByRole("button", { name: "Close summary" }).click();
    await dock(page).getByTestId("atlas-wu-clear").click();
    await expect(dock(page).getByTestId("atlas-wu-found")).toHaveCount(0);
    expect(errors()).toEqual([]);
  });

  test("the reply's text is revealed smoothly, then its statements come in", async ({ page }) => {
    const summary = Array.from({ length: 4 }, (_, i) => `Part ${i + 1}: ${reply.summary}`).join(" ");
    const claims = [{ text: "STXBP1 encephalopathy is caused by changes in STXBP1.", edge_ids: ["e_e5f778ac8a21"], confidence: "high", origin: "observed" }];
    const r = { ...reply, summary, claims };
    await recordReveal(page, '[data-testid="atlas-wu-dock"] [data-testid="summary"]');
    await atlas(
      page,
      {
        "POST /chat": sseBody([
          { type: "status", tool: "resolve_to_ids", message: "Matching it to the atlas" },
          { type: "summary_delta", text: summary },
          { type: "claims", claims, contradictions: [] },
          { type: "final", reply: r, session_id: "11111111-1111-4111-8111-111111111111", message_id: "22222222-2222-4222-8222-222222222222" },
        ]),
      },
      signedInSession({ consents: ["health_data"] }),
    );
    await page.goto("/atlas");
    await ask(page);
    await expect(dock(page).getByTestId("summary")).toHaveText(summary);
    const texts = (await revealSamples(page)).map((x) => x.text).filter(Boolean);
    expect(new Set(texts.filter((x) => x.length < summary.length)).size).toBeGreaterThanOrEqual(2);
    for (const x of texts) expect(summary.startsWith(x.trimEnd())).toBe(true);
    expect(texts[texts.length - 1]).toBe(summary);
    await expect(dock(page).getByTestId("claim")).toHaveCount(1);
    const toggle = dock(page).getByTestId("sources").getByRole("button");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
  });

  test("errors show as the chat shows them", async ({ page }) => {
    await atlas(page, { "POST /chat": sseBody([{ type: "error", code: "rate_limited", message: "Limit reached" }]) }, signedInSession({ consents: ["health_data"] }));
    await page.goto("/atlas");
    await ask(page);
    await expect(dock(page).getByTestId("turn-error")).toHaveAttribute("data-code", "rate_limited");
    await expect(dock(page).getByTestId("turn-error")).toContainText("usage limit");
  });

  test("retry reruns the failed turn without sending the message as new", async ({ page }) => {
    const bodies: Array<Record<string, unknown>> = [];
    const mid = "44444444-4444-4444-8444-444444444444";
    await atlas(
      page,
      {
        "POST /chat": (req: { body: unknown }) => {
          bodies.push(req.body as Record<string, unknown>);
          return bodies.length === 1
            ? sseBody([
                { type: "turn", session_id: "11111111-1111-4111-8111-111111111111", message_id: mid },
                { type: "error", code: "upstream_error", message: "Dr. Wu took too long to answer. Please try again." },
              ])
            : turnBody;
        },
      },
      signedInSession({ consents: ["health_data"] }),
    );
    await page.goto("/atlas");
    await ask(page);
    await dock(page).getByTestId("turn-error").getByRole("button", { name: "Retry" }).click();
    await expect(dock(page).getByTestId("atlas-wu-turn")).toHaveAttribute("data-phase", "done");
    expect(bodies[1]).toMatchObject({ session_id: "11111111-1111-4111-8111-111111111111", retry_message_id: mid });
  });

  for (const theme of ["light", "dark"] as const) {
    test(`screenshot dock ${theme}`, async ({ page }, info) => {
      await setTheme(page, theme);
      await atlas(page, { "POST /chat": turnBody }, signedInSession({ consents: ["health_data"] }));
      await page.goto("/atlas");
      await ask(page);
      await expect(dock(page).getByTestId("atlas-wu-found")).toBeVisible();
      await page.screenshot({ path: info.outputPath(`atlas-wu-dock-${theme}.png`) });
    });
  }

  test("opens as a sheet on mobile @mobile", async ({ page }, info) => {
    await atlas(page, { "POST /chat": turnBody }, signedInSession({ consents: ["health_data"] }));
    await page.goto("/atlas");
    await dock(page).getByTestId("atlas-wu-open").click();
    const sheet = page.getByTestId("atlas-wu-sheet");
    await expect(sheet).toBeVisible();
    const box = sheet.getByRole("textbox", { name: "Message Dr. Wu" });
    await box.fill(STORY);
    await box.press("Enter");
    await expect(sheet.getByTestId("atlas-wu-found")).toContainText("Dr. Wu found 4");
    await page.screenshot({ path: info.outputPath("atlas-wu-dock-mobile.png") });
  });
});
