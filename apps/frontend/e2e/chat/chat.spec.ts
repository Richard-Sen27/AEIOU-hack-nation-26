import { expect, test, type Page } from "@playwright/test";

import { errorEnvelope, guestSession, mockApi, setTheme, shot, signedInSession, sseBody, trackConsoleErrors } from "../helpers";
import { atlasTreePayload, summaryMock } from "../graph/fixtures";
import { emptyReply, graphMocks, reply, SESSION_ID, STORY, turnBody } from "./fixtures";

type Req = { url: string; method: string; body: unknown };

const sessions = [
  { id: SESSION_ID, title: "STXBP1 and related communities", created_at: "2026-10-03T10:00:00Z", updated_at: "2026-10-03T10:05:00Z" },
  { id: "33333333-3333-4333-8333-333333333333", title: "Dravet syndrome registries", created_at: "2026-10-01T09:00:00Z", updated_at: "2026-10-01T09:10:00Z" },
];

async function signedIn(page: Page, mocks: Record<string, unknown> = {}, user: Record<string, unknown> = {}) {
  await mockApi(page, {
    "GET /auth/session": signedInSession({ consents: ["health_data"], ...user }),
    "GET /chat/sessions": [],
    "GET /profile": { updated_at: "2026-10-03T00:00:00Z" },
    ...graphMocks,
    ...mocks,
  });
}

async function ask(page: Page, text = STORY) {
  const box = page.getByRole("textbox", { name: "Message Dr. Wu" });
  await box.fill(text);
  await box.press("Enter");
}

const turn = (page: Page) => page.getByTestId("assistant-turn").last();

test.describe("chat", () => {
  test("full streamed turn renders every part, in order", async ({ page }) => {
    const bodies: Req["body"][] = [];
    await signedIn(page, {
      "POST /chat": (req: Req) => {
        bodies.push(req.body);
        return turnBody();
      },
    }, { role: "researcher" });
    const errors = trackConsoleErrors(page);
    await page.goto("/chat");
    await expect(page.getByTestId("ai-disclosure")).toBeVisible();
    // Researchers get expert mode by default.
    await expect(page.getByTestId("expert-mode")).toHaveAttribute("aria-checked", "true");
    await ask(page);
    const t = turn(page);
    await expect(t).toHaveAttribute("data-phase", "done");
    expect(bodies[0]).toEqual({ message: STORY, session_id: null, expert_mode: true });

    await expect(t.getByTestId("summary")).toHaveText(reply.summary);
    await expect(t.getByTestId("chip")).toHaveCount(6);
    await expect(t.locator('[data-testid="chip"][data-negated]')).toContainText("Excluded");
    await expect(t.getByTestId("vus-notice").first()).toBeVisible();
    await expect(t.getByTestId("claim")).toHaveCount(3);
    await expect(t.getByTestId("claim").first().getByTestId("origin-badge")).toHaveText("Hypothesis");
    await expect(t.getByTestId("claim").nth(1).getByTestId("origin-badge")).toHaveText("Data");
    await expect(t.getByTestId("missing-evidence")).toContainText("SYNGAP1");
    await expect(t.getByTestId("mini-graph")).toBeVisible();
    await expect(t.getByTestId("mini-graph").locator('[data-edge-origin="inferred"] line').first()).toHaveAttribute("stroke-dasharray", "6 4");
    await expect(t.getByTestId("card-patient_group")).toContainText("STXBP1 Parents Group (fixture)");
    await expect(t.getByTestId("card-open_in_atlas").getByRole("link", { name: /Open in Atlas/ })).toHaveAttribute("href", "/atlas");
    await expect(t.locator('[data-viable="true"]')).toContainText("Enrol within 3 months");
    await expect(t.locator('[data-viable="false"]')).toBeVisible();
    await expect(t.getByTestId("follow-up")).toBeVisible();
    await expect(t.getByTestId("show-in-graph")).toHaveAttribute("href", "/atlas");

    // Document order: status → summary → chips → claims → cards → actions → follow-up.
    const order = await t.evaluate((el) =>
      ["status-lines", "summary", "chips", "claim", "cards", "actions", "follow-up"].map((id) => {
        const node = el.querySelector(`[data-testid="${id}"]`) ?? (id === "status-lines" ? el.querySelector("button[aria-expanded]") : null);
        return node ? Array.from(el.querySelectorAll("*")).indexOf(node) : -1;
      }),
    );
    expect(order.every((v, i) => v >= 0 && (i === 0 || v > order[i - 1]))).toBe(true);
    expect(errors()).toEqual([]);
  });

  test("status lines show while the agent works", async ({ page }) => {
    await signedIn(page, {
      "POST /chat": sseBody([
        { type: "status", tool: "find_path", message: "Finding the most trustworthy connections" },
        { type: "summary_delta", text: "Partial answer" },
      ]),
    });
    await page.goto("/chat");
    await ask(page);
    // Stream ended without final → kept content, marked interrupted with retry.
    await expect(turn(page).getByTestId("summary")).toHaveText("Partial answer");
    await expect(turn(page).getByTestId("turn-error")).toHaveAttribute("data-code", "network_error");
    await expect(turn(page).getByRole("button", { name: "Try again" })).toBeVisible();
  });

  test("uncertainty line comes before any content", async ({ page }) => {
    const r = emptyReply("These conditions may be related, but the links are weak.", {
      uncertainty: "All connections found here are below the confidence threshold.",
      claims: [{ text: "STXBP1 and SYNGAP1 may affect the same pathway.", edge_ids: ["e_275854103db5"], origin: "inferred", confidence: "low" }],
    });
    await signedIn(page, { "POST /chat": turnBody(r) });
    await page.goto("/chat");
    await ask(page, "Is STXBP1 related to SYNGAP1?");
    const t = turn(page);
    await expect(t.getByTestId("uncertainty")).toContainText("below the confidence threshold");
    const before = await t.evaluate((el) => {
      const u = el.querySelector('[data-testid="uncertainty"]')!;
      const s = el.querySelector('[data-testid="summary"]')!;
      return !!(u.compareDocumentPosition(s) & Node.DOCUMENT_POSITION_FOLLOWING);
    });
    expect(before).toBe(true);
    await expect(t.getByTestId("claim-confidence")).toContainText("Low");
  });

  test("uncertainty event renders above the summary before the reply is final", async ({ page }) => {
    await signedIn(page, {
      "POST /chat": sseBody([
        { type: "status", tool: "find_path", message: "Finding the most trustworthy connections" },
        { type: "uncertainty", text: "All connections found here are below the confidence threshold." },
        { type: "summary_delta", text: "These conditions may be related." },
      ]),
    });
    await page.goto("/chat");
    await ask(page, "Is STXBP1 related to SYNGAP1?");
    const t = turn(page);
    // No final arrived: the line comes from the uncertainty event itself.
    await expect(t.getByTestId("turn-error")).toBeVisible();
    await expect(t.getByTestId("uncertainty")).toContainText("below the confidence threshold");
    const before = await t.evaluate((el) => {
      const u = el.querySelector('[data-testid="uncertainty"]')!;
      const s = el.querySelector('[data-testid="summary"]')!;
      return !!(u.compareDocumentPosition(s) & Node.DOCUMENT_POSITION_FOLLOWING);
    });
    expect(before).toBe(true);
  });

  test("claim evidence expands, with the contradiction next to its claim", async ({ page }) => {
    await signedIn(page, { "POST /chat": turnBody() });
    await page.goto("/chat");
    await ask(page);
    const claim = turn(page).getByTestId("claim").first();
    await expect(claim.getByTestId("contradiction")).toContainText("seizures are only occasional");
    await claim.getByRole("button", { name: /Evidence · 1 link/ }).click();
    const item = claim.locator('[data-edge-id="e_3b8845b635b8"]');
    await expect(item).toContainText("SCN2A developmental and epileptic encephalopathy");
    await item.getByRole("button", { name: /Show 1 source/ }).click();
    await expect(item.getByTestId("evidence-list")).toContainText("fixture:80.1");
    await claim.getByRole("button", { name: "Show contradicting sources" }).click();
    await expect(claim.locator('[data-edge-id="e_9a6ff6e0e247"]')).toBeVisible();
  });

  test("chips: confirm, remove and correct update the profile", async ({ page }) => {
    const puts: Array<Record<string, Array<Record<string, unknown>>>> = [];
    let version = 0;
    await signedIn(page, {
      "POST /chat": turnBody(),
      "GET /profile": () => ({ json: { ...(puts.at(-1) ?? {}), updated_at: `2026-10-03T00:00:0${version}Z` } }),
      "PUT /profile": (req: Req) => {
        const body = req.body as Record<string, Array<Record<string, unknown>>> & { updated_at?: string };
        if (body.updated_at !== `2026-10-03T00:00:0${version}Z`) return errorEnvelope(409, "conflict");
        version += 1;
        puts.push(body);
        return { json: { ...body, updated_at: `2026-10-03T00:00:0${version}Z` } };
      },
      "GET /search": { results: [{ id: "HP:0012469", type: "phenotype", label: "Infantile spasms", matched_synonym: null, score: 1, match_kind: "exact" }] },
    });
    await page.goto("/chat");
    await ask(page);
    const chips = turn(page).getByTestId("chips");

    await chips.getByRole("button", { name: "Confirm STXBP1 encephalopathy" }).click();
    await expect(chips.getByTestId("chip").first()).toHaveAttribute("data-state", "confirmed");
    expect(puts.at(-1)!.diseases).toEqual([expect.objectContaining({ id: "MONDO:9900007", label: "STXBP1 encephalopathy", source: "chat" })]);

    await chips.getByRole("button", { name: "Confirm No Feeding difficulties" }).click();
    await expect.poll(() => puts.at(-1)!.phenotypes).toEqual([expect.objectContaining({ id: "HP:0011968", excluded: true })]);

    // Removing a confirmed chip takes it out of the profile again.
    await chips.getByRole("button", { name: "Remove STXBP1 encephalopathy" }).click();
    await expect(chips.getByTestId("chip").first()).toHaveAttribute("data-state", "removed");
    expect(puts.at(-1)!.diseases).toEqual([]);

    // Removing an unconfirmed chip changes nothing on the server.
    const n = puts.length;
    await chips.getByRole("button", { name: "Remove STXBP1", exact: true }).click();
    await expect(chips.getByTestId("chip").nth(1)).toHaveAttribute("data-state", "removed");
    expect(puts.length).toBe(n);

    // Correcting re-resolves through entity search, then confirms the pick.
    await chips.getByRole("button", { name: "Correct Seizure" }).click();
    const panel = chips.getByTestId("chip-correct");
    await panel.getByRole("textbox").fill("Infantile spasms");
    await panel.getByRole("button", { name: /Infantile spasms/ }).click();
    await expect(chips.getByTestId("chip").nth(2)).toContainText("Infantile spasms");
    await expect(chips.getByTestId("chip").nth(2)).toHaveAttribute("data-state", "confirmed");
    expect(puts.at(-1)!.phenotypes).toEqual(
      expect.arrayContaining([expect.objectContaining({ id: "HP:0012469", label: "Infantile spasms", excluded: false })]),
    );
  });

  test("chips into an empty profile carry the consent's child answer", async ({ page }) => {
    const puts: Array<Record<string, unknown>> = [];
    await signedIn(page, {
      "POST /chat": turnBody(),
      "GET /profile": { updated_at: null },
      "GET /consents": [
        { id: "c1", consent_type: "health_data", version: "health-data-2026-10-04", granted_at: "2026-10-03T00:00:00Z", active: true, about_child: true, parental_responsibility_confirmed: true },
      ],
      "PUT /profile": (req: Req) => {
        puts.push(req.body as Record<string, unknown>);
        return { json: { ...(req.body as object), updated_at: "2026-10-03T00:00:01Z" } };
      },
    });
    await page.goto("/chat");
    await ask(page);
    await turn(page).getByTestId("chips").getByRole("button", { name: "Confirm STXBP1 encephalopathy" }).click();
    await expect.poll(() => puts.length).toBe(1);
    expect(puts[0]).toMatchObject({ about_child: true, parental_responsibility_confirmed: true });
  });

  test("profile hints are confirmed one by one; a suspected child is offered once", async ({ page }) => {
    const puts: Array<Record<string, unknown>> = [];
    const withHints = { ...reply, profile_hints: { age_years: 2, onset: null, country: "AT", about_child_suspected: true } };
    await signedIn(page, {
      "POST /chat": turnBody(withHints),
      // Not empty and set to "own data": the reply suspecting a child offers to change it.
      "GET /profile": () => ({ json: { diseases: [{ id: "MONDO:9900007", label: "STXBP1 encephalopathy", source: "chat" }], about_child: false, ...(puts.at(-1) ?? {}), updated_at: null } }),
      "PUT /profile": (req: Req) => {
        puts.push(req.body as Record<string, unknown>);
        return { json: { ...(req.body as object), updated_at: null } };
      },
    });
    await page.goto("/chat");
    await ask(page);
    const hints = turn(page).getByTestId("profile-hints");
    await expect(hints.getByTestId("profile-hint")).toHaveCount(2);
    await hints.getByRole("button", { name: "Confirm Age 2" }).click();
    await expect(hints.getByTestId("profile-hint").first()).toHaveAttribute("data-state", "confirmed");
    expect(puts.at(-1)).toMatchObject({ age_years: 2 });
    await hints.getByRole("button", { name: "Dismiss Country: AT" }).click();
    await expect(hints.getByTestId("profile-hint")).toHaveCount(1);

    const offer = turn(page).getByTestId("child-offer");
    await expect(offer).toBeVisible();
    const yes = offer.getByRole("button", { name: "Yes, it is about a child" });
    await expect(yes).toBeDisabled();
    await offer.getByRole("checkbox", { name: /parental responsibility/ }).click();
    await yes.click();
    await expect(offer).toBeHidden();
    expect(puts.at(-1)).toMatchObject({ about_child: true, parental_responsibility_confirmed: true });
  });

  test("profile conflict is retried once with a fresh read", async ({ page }) => {
    let calls = 0;
    await signedIn(page, {
      "POST /chat": turnBody(),
      "PUT /profile": (req: Req) => {
        calls += 1;
        return calls === 1 ? errorEnvelope(409, "conflict") : { json: req.body };
      },
    });
    await page.goto("/chat");
    await ask(page);
    await turn(page).getByRole("button", { name: "Confirm STXBP1", exact: true }).click();
    await expect(turn(page).getByTestId("chip").nth(1)).toHaveAttribute("data-state", "confirmed");
    expect(calls).toBe(2);
  });

  test("follow-up quick reply sends it, skip hides it", async ({ page }) => {
    const messages: string[] = [];
    await signedIn(page, {
      "POST /chat": (req: Req) => {
        messages.push((req.body as { message: string }).message);
        return turnBody();
      },
    });
    await page.goto("/chat");
    await ask(page);
    await turn(page).getByRole("button", { name: "Yes, in the first weeks" }).click();
    await expect(page.getByTestId("assistant-turn")).toHaveCount(2);
    await expect.poll(() => messages).toEqual([STORY, "Yes, in the first weeks"]);
    // The first turn's question is answered; only the newest one is active.
    await expect(page.getByTestId("follow-up")).toHaveCount(1);
    await expect(turn(page)).toHaveAttribute("data-phase", "done");
    await turn(page).getByRole("button", { name: "Skip this question" }).click();
    await expect(page.getByTestId("follow-up")).toHaveCount(0);
    expect(messages).toHaveLength(2);
  });

  test("export proposal opens print-ready HTML in a new tab", async ({ page, context }) => {
    let proposal: Record<string, unknown> | null = null;
    await signedIn(page, {
      "POST /chat": turnBody(),
      "POST /proposal": (req: Req) => {
        proposal = req.body as Record<string, unknown>;
        return { contentType: "text/html", body: "<!doctype html><html><head><title>Proposal</title></head><body><h1>Sourced proposal</h1></body></html>" };
      },
    });
    await page.goto("/chat");
    await ask(page);
    const popup = context.waitForEvent("page");
    await turn(page).getByRole("button", { name: "Export proposal" }).click();
    const tab = await popup;
    await expect(tab.getByRole("heading", { name: "Sourced proposal" })).toBeVisible();
    expect(proposal!.edge_ids).toEqual(expect.arrayContaining(["e_0af807385728", "e_558f7d2a940d", "e_275854103db5"]));
    expect((proposal!.actions as unknown[]).length).toBe(2);
  });

  test("emergency reply looks different and has no graph content", async ({ page }) => {
    await signedIn(page, {
      "POST /chat": turnBody(
        emptyReply("This sounds like an emergency. Please call emergency services (112 or 911) now.", { kind: "emergency" }),
      ),
    });
    await page.goto("/chat");
    await ask(page, "She has been seizing for 10 minutes and is not breathing well");
    const t = turn(page);
    await expect(t.getByTestId("emergency")).toBeVisible();
    await expect(t.getByRole("alert")).toContainText("Call emergency services now");
    await expect(t.getByTestId("cards")).toHaveCount(0);
    await expect(t.getByTestId("chips")).toHaveCount(0);
  });

  test("emergency panel follows the reply flag, not the wording", async ({ page }) => {
    let next: Record<string, unknown> = emptyReply("Please get help for her right away.", { kind: "emergency" });
    await signedIn(page, { "POST /chat": () => turnBody(next) });
    await page.goto("/chat");
    await ask(page, "She is not breathing");
    await expect(turn(page).getByTestId("emergency")).toBeVisible();

    // An ordinary answer that merely mentions 112 is not an emergency reply.
    next = emptyReply("The registry hotline is 112 in some countries.", { kind: "answer" });
    await ask(page, "What is the registry's number?");
    await expect(turn(page)).toHaveAttribute("data-phase", "done");
    await expect(turn(page).getByTestId("summary")).toContainText("hotline");
    await expect(turn(page).getByTestId("emergency")).toHaveCount(0);
  });

  test("stored emergency reply without a flag still shows the emergency panel", async ({ page }) => {
    const old = emptyReply("This sounds like an emergency. Please call emergency services (112 or 911) now.");
    await signedIn(page, {
      "GET /chat/sessions": [sessions[0]],
      "GET /chat/sessions/*": {
        session: sessions[0],
        messages: [
          { id: "m1", session_id: SESSION_ID, role: "user", content: "She is not breathing", created_at: "2026-10-03T10:00:00Z" },
          { id: "m2", session_id: SESSION_ID, role: "assistant", content: old.summary, reply: old, created_at: "2026-10-03T10:00:05Z" },
        ],
      },
    });
    await page.goto("/chat");
    await page.getByTestId("session-list").first().getByRole("button", { name: /^STXBP1 and related communities/ }).click();
    await expect(turn(page).getByTestId("emergency")).toBeVisible();
  });

  test("declined request still shows the graph context", async ({ page }) => {
    const r = {
      ...reply,
      summary: "I can't recommend a treatment; please discuss medication with her neurologist. Here is what the atlas connects to STXBP1 encephalopathy.",
      follow_up: null,
      actions: [],
      kind: "declined",
    };
    await signedIn(page, { "POST /chat": turnBody(r) });
    await page.goto("/chat");
    await ask(page, "Which medication should she take?");
    await expect(turn(page).getByTestId("emergency")).toHaveCount(0);
    await expect(turn(page).getByTestId("mini-graph")).toBeVisible();
  });

  const errorCases = [
    { code: "rate_limited", message: "Your ChatGPT plan's usage limit has been reached.", title: "usage limit is reached", retry: true },
    { code: "reauth_required", message: "Please sign in again.", title: "Please sign in again", retry: false },
    { code: "upstream_error", message: "The answer timed out.", title: "took too long", retry: true },
  ];
  for (const c of errorCases) {
    test(`error event: ${c.code}`, async ({ page }) => {
      await signedIn(page, {
        "POST /chat": sseBody([
          { type: "status", message: "Reading what you described" },
          { type: "error", code: c.code, message: c.message },
        ]),
      });
      await page.goto("/chat");
      await ask(page);
      const err = turn(page).getByTestId("turn-error");
      await expect(err).toContainText(c.title);
      if (c.retry) await expect(err.getByRole("button", { name: "Try again" })).toBeVisible();
      else await expect(page.getByTestId("sign-in-dialog")).toBeVisible();
    });
  }

  test("network drop mid-stream keeps what arrived and retries", async ({ page }) => {
    let n = 0;
    await signedIn(page, {
      "POST /chat": () => {
        n += 1;
        return n === 1
          ? sseBody([{ type: "summary_delta", text: "STXBP1 encephalopathy shares" }])
          : turnBody();
      },
    });
    await page.goto("/chat");
    await ask(page);
    await expect(turn(page).getByTestId("summary")).toHaveText("STXBP1 encephalopathy shares");
    await turn(page).getByRole("button", { name: "Try again" }).click();
    await expect(turn(page)).toHaveAttribute("data-phase", "done");
    await expect(turn(page).getByTestId("summary")).toHaveText(reply.summary);
    await expect(page.getByTestId("assistant-turn")).toHaveCount(1);
  });

  test("a stored failed turn shows its steps, error and Try again; the retry reruns it in place", async ({ page }) => {
    const bodies: Array<Record<string, unknown>> = [];
    const steps = [
      { tool: null, message: "Checking your message" },
      { tool: "extract_entities", message: "Reading your message" },
      { tool: "get_neighborhood", message: "Looking at connected diseases" },
    ];
    await signedIn(page, {
      "GET /chat/sessions": [sessions[0]],
      "GET /chat/sessions/*": {
        session: sessions[0],
        messages: [
          { id: "m1", session_id: SESSION_ID, role: "user", content: STORY, reply: null, error: null, created_at: "2026-10-03T10:00:00Z" },
          {
            id: "m2",
            session_id: SESSION_ID,
            role: "assistant",
            content: "Dr. Wu took too long to answer. Please try again.",
            reply: null,
            error: { code: "upstream_error", message: "Dr. Wu took too long to answer. Please try again.", steps },
            created_at: "2026-10-03T10:01:30Z",
          },
        ],
      },
      "POST /chat": (req: Req) => {
        bodies.push(req.body as Record<string, unknown>);
        return turnBody();
      },
    });
    await page.goto("/chat");
    await page.getByTestId("session-list").first().getByRole("button", { name: /^STXBP1 and related communities/ }).click();
    await expect(page.getByTestId("user-message")).toHaveCount(1);
    const err = turn(page).getByTestId("turn-error");
    await expect(err).toContainText("took too long");
    await expect(turn(page).getByRole("button", { name: "Checked the atlas in 3 steps" })).toBeVisible();
    await err.getByRole("button", { name: "Try again" }).click();
    await expect(turn(page)).toHaveAttribute("data-phase", "done");
    await expect(turn(page).getByTestId("summary")).toHaveText(reply.summary);
    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toMatchObject({ message: STORY, session_id: SESSION_ID, retry_message_id: "m1" });
    await expect(page.getByTestId("user-message")).toHaveCount(1);
    await expect(page.getByTestId("assistant-turn")).toHaveCount(1);
  });

  test("a live failed turn is retried with its stored message id", async ({ page }) => {
    const bodies: Array<Record<string, unknown>> = [];
    await signedIn(page, {
      "POST /chat": (req: Req) => {
        bodies.push(req.body as Record<string, unknown>);
        return bodies.length === 1
          ? sseBody([
              { type: "status", message: "Checking your message" },
              { type: "turn", session_id: SESSION_ID, message_id: "44444444-4444-4444-8444-444444444444" },
              { type: "error", code: "upstream_error", message: "Dr. Wu took too long to answer. Please try again." },
            ])
          : turnBody();
      },
    });
    await page.goto("/chat");
    await ask(page);
    await turn(page).getByTestId("turn-error").getByRole("button", { name: "Try again" }).click();
    await expect(turn(page)).toHaveAttribute("data-phase", "done");
    expect(bodies[0]).not.toHaveProperty("retry_message_id");
    expect(bodies[1]).toMatchObject({
      message: STORY,
      session_id: SESSION_ID,
      retry_message_id: "44444444-4444-4444-8444-444444444444",
    });
    await expect(page.getByTestId("user-message")).toHaveCount(1);
  });

  test("501 from the API degrades gracefully", async ({ page }) => {
    await signedIn(page, { "POST /chat": errorEnvelope(501, "not_implemented", "Not implemented") });
    const errors = trackConsoleErrors(page);
    await page.goto("/chat");
    await ask(page);
    await expect(turn(page).getByTestId("turn-error")).toContainText("not available yet");
    expect(errors().filter((e) => !/501/.test(e))).toEqual([]);
  });

  test("stop ends the answer", async ({ page }) => {
    await signedIn(page, {
      "POST /chat": async () => {
        await new Promise((r) => setTimeout(r, 3000));
        return turnBody();
      },
    });
    await page.goto("/chat");
    await ask(page);
    await page.getByRole("button", { name: "Stop the answer" }).click();
    await expect(turn(page)).toHaveAttribute("data-phase", "stopped");
    await expect(page.getByRole("button", { name: "Send" })).toBeVisible();
  });

  test("guest sees what Dr. Wu does and the sign-in, not a chat", async ({ page }) => {
    const posts: string[] = [];
    await mockApi(page, { "GET /auth/session": guestSession });
    page.on("request", (r) => r.method() === "POST" && posts.push(r.url()));
    await page.goto("/chat");
    await expect(page.getByTestId("chat-guest")).toBeVisible();
    await expect(page.getByTestId("ai-disclosure")).toBeVisible();
    await expect(page.getByRole("button", { name: /Continue with ChatGPT/ }).last()).toBeVisible();
    await expect(page.getByTestId("composer")).toHaveCount(0);
    expect(posts).toEqual([]);
  });

  test("session list: open and delete", async ({ page }) => {
    const deleted: string[] = [];
    await signedIn(page, {
      "GET /chat/sessions": () => ({ json: sessions.filter((s) => !deleted.includes(s.id)) }),
      "GET /chat/sessions/*": () => ({
        json: {
          session: sessions[0],
          messages: [
            { id: "m1", session_id: SESSION_ID, role: "user", content: "STXBP1, daughter aged 2", created_at: "2026-10-03T10:00:00Z" },
            { id: "m2", session_id: SESSION_ID, role: "assistant", content: reply.summary, reply: { ...reply, chips: reply.chips.map((c, i) => ({ ...c, confirmed: i === 0 })) }, created_at: "2026-10-03T10:00:05Z" },
          ],
        },
      }),
      "DELETE /chat/sessions/*": (req: Req) => {
        deleted.push(decodeURIComponent(req.url.split("/").pop()!));
        return { status: 204, body: "" };
      },
    });
    await page.goto("/chat");
    const list = page.getByTestId("session-list").first();
    await expect(list.getByTestId("session-item")).toHaveCount(2);
    await list.getByRole("button", { name: /^STXBP1 and related communities/ }).click();
    await expect(page.getByTestId("user-message")).toContainText("daughter aged 2");
    await expect(turn(page).getByTestId("summary")).toHaveText(reply.summary);
    await expect(turn(page).getByTestId("chip").first()).toHaveAttribute("data-state", "confirmed");
    // History is read-only: its follow-up question is not active again.
    await expect(page.getByTestId("follow-up")).toHaveCount(0);

    await list.getByRole("button", { name: "Delete conversation: STXBP1 and related communities" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Delete" }).click();
    await expect(list.getByTestId("session-item")).toHaveCount(1);
    expect(deleted).toEqual([SESSION_ID]);
    // The open conversation was the deleted one: back to a fresh start.
    await expect(page.getByTestId("assistant-turn")).toHaveCount(0);
  });

  test("new conversation clears the log and sends without a session", async ({ page }) => {
    const bodies: Array<{ session_id: string | null }> = [];
    await signedIn(page, {
      "POST /chat": (req: Req) => {
        bodies.push(req.body as { session_id: string | null });
        return turnBody();
      },
    });
    await page.goto("/chat");
    await ask(page);
    await expect(turn(page)).toHaveAttribute("data-phase", "done");
    await ask(page, "What about Dravet syndrome?");
    await expect.poll(() => bodies.length).toBe(2);
    expect(bodies[1].session_id).toBe(SESSION_ID);
    await page.getByRole("button", { name: "New conversation" }).first().click();
    await expect(page.getByTestId("assistant-turn")).toHaveCount(0);
    await ask(page, "STXBP1");
    await expect.poll(() => bodies.length).toBe(3);
    expect(bodies[2].session_id).toBeNull();
  });

  test("drop zone hands files to the documents flow behind the consent gate", async ({ page }) => {
    await signedIn(page, { "GET /documents": [] }, { consents: ["health_data"] });
    await page.goto("/chat");
    await page.getByTestId("chat-file-input").setInputFiles({ name: "report.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4") });
    await expect(page).toHaveURL(/\/documents$/);
  });

  test("drop without consent opens the consent dialog", async ({ page }) => {
    await signedIn(page, {}, { consents: [] });
    await page.goto("/chat");
    const dt = await page.evaluateHandle(() => {
      const d = new DataTransfer();
      d.items.add(new File(["%PDF"], "report.pdf", { type: "application/pdf" }));
      return d;
    });
    const zone = page.getByTestId("chat-drop-zone");
    await zone.dispatchEvent("dragenter", { dataTransfer: dt });
    await expect(zone).toHaveAttribute("data-dragging", "true");
    await zone.dispatchEvent("drop", { dataTransfer: dt });
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page).toHaveURL(/\/chat$/);
  });

  test("first message without consent asks for it and keeps the text", async ({ page }) => {
    let posted = false;
    await signedIn(page, { "POST /chat": () => ((posted = true), turnBody()) }, { consents: [] });
    await page.goto("/chat");
    await ask(page);
    const dialog = page.getByTestId("consent-dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("Use of your health information");
    await dialog.getByRole("button", { name: "Not now" }).click();
    await expect(page.getByRole("textbox", { name: "Message Dr. Wu" })).toHaveValue(STORY);
    await expect(page.getByTestId("user-message")).toHaveCount(0);
    expect(posted).toBe(false);
  });

  test("show in graph hands the finds to the Atlas in memory, never in a URL or storage", async ({ page }) => {
    await signedIn(page, {
      "POST /chat": turnBody(),
      "GET /atlas/tree.json": atlasTreePayload(),
      "GET /atlas/summary/*": summaryMock(),
    });
    await page.goto("/chat");
    await ask(page);
    await expect(turn(page)).toHaveAttribute("data-phase", "done");
    await turn(page).getByTestId("show-in-graph").click();

    await expect(page).toHaveURL(/\/atlas$/);
    expect(new URL(page.url()).search).toBe("");
    await expect(page.getByTestId("atlas-wu-found")).toContainText("Dr. Wu found 1");
    const ids = ["MONDO:9900007", ...reply.graph_focus.highlight_path];
    const hrefs = await page.locator("a[href]").evaluateAll((as) => as.map((a) => decodeURIComponent(a.getAttribute("href") ?? "")));
    for (const id of ids) {
      expect(decodeURIComponent(page.url())).not.toContain(id);
      expect(hrefs.some((h) => h.includes(id))).toBe(false);
    }
    const stored = await page.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }));
    for (const id of ids) expect(stored).not.toContain(id);

    // The finds are the dock's: the list opens and clears like a reply in the dock.
    await page.getByTestId("atlas-wu-open").click();
    await expect(page.getByTestId("atlas-wu-found-item")).toHaveText([/STXBP1 encephalopathy/]);
    await page.getByTestId("atlas-wu-clear").click();
    await expect(page.getByTestId("atlas-wu-found")).toHaveCount(0);
  });

  test("message text never reaches URLs or browser storage", async ({ page }) => {
    const urls: string[] = [];
    page.on("request", (r) => urls.push(r.url()));
    await signedIn(page, { "POST /chat": turnBody() });
    await page.goto("/chat");
    await ask(page);
    await expect(turn(page)).toHaveAttribute("data-phase", "done");
    await turn(page).getByTestId("claim").first().getByRole("button", { name: /Evidence/ }).click();
    expect(urls.some((u) => /daughter|seizures|walking/i.test(decodeURIComponent(u)))).toBe(false);
    const stored = await page.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }));
    expect(stored).not.toMatch(/daughter|seizures|STXBP1|Dr\. Wu/);
    expect(page.url()).toMatch(/\/chat$/);
  });

  for (const theme of ["light", "dark"] as const) {
    test(`screenshot full turn ${theme}`, async ({ page }) => {
      await setTheme(page, theme);
      await signedIn(page, { "POST /chat": turnBody(), "GET /chat/sessions": sessions });
      await page.goto("/chat");
      await shot(page, `chat-empty-${theme}`);
      await ask(page);
      await expect(turn(page)).toHaveAttribute("data-phase", "done");
      await turn(page).getByTestId("claim").first().getByRole("button", { name: /Evidence/ }).click();
      await expect(turn(page).locator('[data-edge-id="e_3b8845b635b8"]').first()).toBeVisible();
      await page.getByTestId("chat-log").evaluate((el) => {
        el.style.overflow = "visible";
        el.style.height = "auto";
        el.parentElement!.parentElement!.style.height = "auto";
      });
      await shot(page, `chat-turn-${theme}`, { fullPage: true });
    });
  }

  test("screenshot phone @mobile", async ({ page }) => {
    await signedIn(page, { "POST /chat": turnBody() });
    await page.goto("/chat");
    await ask(page);
    await expect(turn(page)).toHaveAttribute("data-phase", "done");
    await shot(page, "chat-turn-mobile");
    await page.getByTestId("chat-log").evaluate((el) => {
      el.style.overflow = "visible";
      el.style.height = "auto";
      el.parentElement!.parentElement!.style.height = "auto";
    });
    await shot(page, "chat-turn-mobile-full", { fullPage: true });
  });

  test("emergency screenshot", async ({ page }) => {
    await signedIn(page, { "POST /chat": turnBody(emptyReply("This sounds like an emergency. Please call emergency services (112 or 911) now.", { kind: "emergency" })) });
    await page.goto("/chat");
    await ask(page, "She is not breathing");
    await expect(turn(page).getByTestId("emergency")).toBeVisible();
    await shot(page, "chat-emergency");
  });
});
