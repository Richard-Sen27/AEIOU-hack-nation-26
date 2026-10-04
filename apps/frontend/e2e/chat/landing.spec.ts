import { expect, test, type Page } from "@playwright/test";

import { atlasTreePayload, statsPayload } from "../graph/fixtures";
import { guestSession, hit, mockApi, setTheme, shot, signedInSession, trackConsoleErrors } from "../helpers";

const STORY = "My daughter is 2, diagnosed with STXBP1 last month. Lots of seizures, not walking yet, no problems with eating.";

/** Every request URL the page makes, to prove free text never leaves in a URL. */
function trackUrls(page: Page) {
  const urls: string[] = [];
  page.on("request", (r) => urls.push(r.url()));
  return urls;
}

const input = (page: Page) => page.getByRole("textbox", { name: /Describe the diagnosis/ });

test.describe("landing", () => {
  test("guest entity search opens the node", async ({ page }) => {
    const searched: string[] = [];
    await mockApi(page, {
      "GET /auth/session": guestSession,
      "GET /search": (req: { url: string }) => {
        searched.push(new URL(req.url).searchParams.get("q") ?? "");
        return { json: { results: [hit("MONDO:9900007", "disease", "STXBP1 encephalopathy", "Ohtahara syndrome")] } };
      },
    });
    const errors = trackConsoleErrors(page);
    await page.goto("/");
    await input(page).fill("Ohtahara syndrome");
    await expect(page.getByTestId("hero-hint")).toHaveAttribute("data-mode", "search");
    await input(page).press("Enter");
    await expect(page).toHaveURL(/\/node\/MONDO%3A9900007$/);
    expect(searched).toEqual(["Ohtahara syndrome"]);
    expect(errors()).toEqual([]);
  });

  test("guest free text offers sign-in and is sent nowhere", async ({ page }) => {
    await mockApi(page, { "GET /auth/session": guestSession, "GET /search": { results: [] } });
    const urls = trackUrls(page);
    const posts: string[] = [];
    page.on("request", (r) => {
      if (r.method() !== "GET") posts.push(r.postData() ?? "");
    });
    await page.goto("/");
    await input(page).fill(STORY);
    await expect(page.getByTestId("hero-hint")).toHaveAttribute("data-mode", "assistant");
    await page.getByRole("button", { name: "Send to Dr. Wu" }).click();
    const dialog = page.getByTestId("sign-in-dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("type it again");
    await expect(dialog.getByRole("button", { name: /Continue with ChatGPT/ })).toBeVisible();
    await page.keyboard.press("Escape");
    // Still on the page, so nothing is lost while they decide.
    await expect(input(page)).toHaveValue(STORY);
    expect(urls.filter((u) => u.includes("/search"))).toEqual([]);
    expect(urls.some((u) => u.includes("daughter") || u.includes("STXBP1"))).toBe(false);
    expect(posts.some((p) => p.includes("daughter"))).toBe(false);
    const stored = await page.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }));
    expect(stored).not.toContain("daughter");
  });

  test("signed-in free text arrives in the chat, never in the URL", async ({ page }) => {
    const bodies: unknown[] = [];
    await mockApi(page, {
      "GET /auth/session": signedInSession({ consents: ["health_data"] }),
      "GET /profile": {},
      "GET /chat/sessions": [],
      "POST /chat": (req: { body: unknown }) => {
        bodies.push(req.body);
        return {
          contentType: "text/event-stream",
          body: `event: summary_delta\ndata: ${JSON.stringify({ type: "summary_delta", text: "Thanks." })}\n\n`,
        };
      },
    });
    const urls = trackUrls(page);
    await page.goto("/");
    await input(page).fill(STORY);
    await input(page).press("Enter");
    await expect(page).toHaveURL(/\/chat$/);
    await expect(page.getByTestId("user-message").first()).toContainText("STXBP1 last month");
    await expect.poll(() => bodies.length).toBe(1);
    expect((bodies[0] as { message: string }).message).toBe(STORY);
    expect(urls.some((u) => u.includes("daughter"))).toBe(false);
  });

  test("dropping a file goes through the health-data consent gate", async ({ page }) => {
    let consentPosted = false;
    await mockApi(page, {
      "GET /auth/session": () =>
        ({ json: signedInSession({ consents: consentPosted ? ["health_data"] : [] }) }),
      "GET /profile": {},
      "POST /consents": () => {
        consentPosted = true;
        return { json: { consent_type: "health_data", version: "1", granted_at: new Date().toISOString(), revoked_at: null } };
      },
      "GET /documents": [],
    });
    await page.goto("/");
    await expect(page.getByTestId("landing-ready")).toBeAttached();
    const dt = await page.evaluateHandle(() => {
      const d = new DataTransfer();
      d.items.add(new File(["%PDF-1.4"], "report.pdf", { type: "application/pdf" }));
      return d;
    });
    const form = page.getByTestId("hero-input");
    await form.dispatchEvent("dragenter", { dataTransfer: dt });
    await expect(form).toHaveAttribute("data-dragging", "true");
    await form.dispatchEvent("drop", { dataTransfer: dt });
    const consent = page.getByRole("dialog");
    await expect(consent).toBeVisible();
    await expect(page).toHaveURL(/\/$/);
  });

  test("guest drop asks for sign-in first", async ({ page }) => {
    await mockApi(page, { "GET /auth/session": guestSession });
    await page.goto("/");
    await page.getByTestId("hero-file-input").setInputFiles({ name: "r.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF") });
    await expect(page.getByTestId("sign-in-dialog")).toBeVisible();
  });

  test("sections, the coming switch and the demo line", async ({ page }) => {
    await mockApi(page, { "GET /auth/session": guestSession });
    await page.goto("/");
    for (const name of ["Click one thing. See everything linked.", "Cleaned before you see it.", "Experts ask. Patients decide."]) {
      await expect(page.getByRole("heading", { level: 2, name })).toBeVisible();
    }
    await expect(page.getByText("Where to start")).toHaveCount(0);
    const follow = page.getByTestId("connect-follow");
    await expect(follow).not.toContainText("Coming soon");
    await expect(follow.getByRole("link")).toHaveAttribute("href", "/atlas");
    await expect(page.getByTestId("connect-calls")).not.toContainText("Coming soon");
    await expect(page.getByTestId("connect-calls").getByRole("link")).toHaveAttribute("href", "/calls");
    for (const key of ["choose"]) {
      const card = page.getByTestId(`connect-${key}`);
      await expect(card).toContainText("Coming soon");
      await expect(card).toContainText("Example");
      await expect(card.getByRole("link")).toHaveCount(0);
    }
    await expect(page.getByTestId("demo-journey")).toHaveCount(0);
  });

  test("demo line only in demo mode, starting the tour for guests", async ({ page }) => {
    await mockApi(page, { "GET /auth/session": { ...guestSession, demo_mode: true } });
    await page.goto("/");
    await page.getByTestId("demo-journey").getByRole("button", { name: /one family/ }).click();
    await expect(page).toHaveURL(/\/atlas\?tour=1$/);
  });

  test("live map preview, graph chips and counts line", async ({ page }) => {
    const tree = atlasTreePayload();
    await mockApi(page, {
      "GET /auth/session": guestSession,
      "GET /atlas/tree.json": tree,
      "GET /stats": statsPayload(),
    });
    const errors = trackConsoleErrors(page);
    await page.goto("/");
    await expect(page.getByTestId("landing-counts")).toHaveText("168 rare diseases · 15,553 cited links · 2,176 computed hypotheses");
    const preview = page.getByTestId("atlas-preview");
    await expect(preview).toHaveAttribute("href", "/atlas");
    await expect(preview).toHaveAccessibleName("Open the Atlas");
    await expect(preview.locator("svg path[d^='M']").first()).toBeAttached();
    // One branch path per category, drawn from the payload's own coordinates.
    await expect(preview.locator("svg g[data-category]")).toHaveCount(9);
    const genes = tree.nodes.find((n) => n.parent_id === "T:genes")!;
    await expect(preview.locator("g[data-category='genes'] path").first()).toHaveAttribute(
      "d",
      new RegExp(`L${Math.round(genes.x)} ${Math.round(-genes.y)}`),
    );

    const section = page.getByTestId("graph-section");
    await section.scrollIntoViewIfNeeded();
    await expect(section.getByRole("img")).toBeVisible();
    const card = section.getByTestId("link-card-observed");
    await expect(card).toBeVisible();
    // The demo disease is not in the fixture tree, so its chip is hidden and SCN1A leads.
    const chips = section.getByRole("group", { name: "Focus" }).getByRole("button");
    await expect(chips.first()).toHaveText("SCN1A");
    await expect(chips.first()).toHaveAttribute("aria-pressed", "true");
    await expect(section.getByRole("img")).toHaveAccessibleName(/^SCN1A: \d+ links, \d+ cited, \d+ computed$/);
    const before = await card.textContent();
    await chips.last().click();
    await expect(chips.last()).toHaveAttribute("aria-pressed", "true");
    await expect(section.getByRole("img")).not.toHaveAccessibleName(/^SCN1A:/);
    await expect(card).not.toHaveText(before ?? "");
    expect(errors()).toEqual([]);
  });

  test("hero map cycles through nodes, pauses on hover and with the control", async ({ page }) => {
    await mockApi(page, { "GET /auth/session": guestSession, "GET /atlas/tree.json": atlasTreePayload() });
    await page.goto("/");
    const map = page.getByTestId("hero-map");
    await expect(map).toHaveAttribute("data-cycle-step", "0");
    await page.mouse.move(2, 2);
    await expect(map).toHaveAttribute("data-paused", "false");
    const first = await map.getAttribute("data-focus");
    await expect(page.getByTestId("atlas-preview-label")).toBeVisible();

    // End the current node's CSS timeline instead of waiting for it.
    const finishCycle = () =>
      page.evaluate(() =>
        document
          .getAnimations()
          .filter((a) => (a as CSSAnimation).animationName === "lp-cycle")
          .forEach((a) => a.finish()),
      );
    await finishCycle();
    await expect(map).toHaveAttribute("data-cycle-step", "1");
    await expect(map).not.toHaveAttribute("data-focus", first ?? "");

    const cycleState = () =>
      page.evaluate(() =>
        document
          .getAnimations()
          .filter((a) => (a as CSSAnimation).animationName === "lp-cycle")
          .map((a) => a.playState),
      );
    await page.getByTestId("atlas-preview").hover();
    await expect(map).toHaveAttribute("data-paused", "true");
    await expect.poll(cycleState).toContain("paused");
    await page.mouse.move(2, 2);
    await expect(map).toHaveAttribute("data-paused", "false");
    await expect.poll(cycleState).toContain("running");

    // The control is a sibling of the link, keyboard-reachable and labelled.
    const toggle = page.getByRole("button", { name: "Pause the map animation" });
    await expect(page.getByTestId("atlas-preview").getByRole("button")).toHaveCount(0);
    await toggle.click();
    await page.mouse.move(2, 2);
    await expect(map).toHaveAttribute("data-paused", "true");
    await expect(page.getByRole("button", { name: "Play the map animation" })).toBeVisible();
    await page.getByRole("button", { name: "Play the map animation" }).focus();
    await page.keyboard.press("Enter");
    await expect(map).toHaveAttribute("data-paused", "false");
  });

  test("hero map does not cycle under reduced motion", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await mockApi(page, { "GET /auth/session": guestSession, "GET /atlas/tree.json": atlasTreePayload() });
    await page.goto("/");
    await expect(page.getByTestId("atlas-preview")).toHaveAttribute("data-state", "ready");
    const map = page.getByTestId("hero-map");
    await expect(map).not.toHaveAttribute("data-cycle-step", /.*/);
    await expect(page.getByTestId("hero-cycle-toggle")).toHaveCount(0);
    await expect(page.getByTestId("atlas-preview-highlight")).toBeAttached();
    const running = await page.evaluate(() => document.getAnimations().filter((a) => (a as CSSAnimation).animationName === "lp-cycle").length);
    expect(running).toBe(0);
  });

  test("API down: hero and prepared-data steps render, no counts line", async ({ page }) => {
    await mockApi(page, { "GET /auth/session": guestSession });
    const errors = trackConsoleErrors(page);
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Rare diseases, connected by what they share.");
    await expect(input(page)).toBeVisible();
    await expect(page.getByTestId("atlas-preview")).toHaveAttribute("data-state", "error");
    await expect(page.getByTestId("atlas-preview")).toHaveAttribute("href", "/atlas");
    await page.getByTestId("prep-section").scrollIntoViewIfNeeded();
    await expect(page.getByTestId("prep-steps")).toContainText("Collect");
    await expect(page.getByTestId("prep-visual")).toHaveCount(0);
    await expect(page.getByTestId("landing-counts")).toHaveCount(0);
    expect(errors()).toEqual([]);
  });

  test("prepared data shows the entry's real names", async ({ page }) => {
    const synonyms = ["developmental and epileptic encephalopathy, 4", "DEE4", "EIEE4", "STXBP1-related encephalopathy"];
    await mockApi(page, {
      "GET /auth/session": guestSession,
      "GET /node/*": {
        node: { id: "MONDO:0012812", type: "disease", label: synonyms[0], description: null, url: null, attrs: {}, cluster_id: null, x: 0, y: 0, centrality: null },
        synonyms,
        summary: "",
        relation_counts: {},
        degree: 0,
        cluster: null,
        classification: null,
        vus_notice: null,
      },
    });
    await page.goto("/");
    await page.getByTestId("prep-section").scrollIntoViewIfNeeded();
    await expect(page.getByTestId("prep-count")).toHaveText("4 names, 1 entry");
  });

  for (const theme of ["light", "dark"] as const) {
    test(`screenshot ${theme}`, async ({ page }) => {
      await setTheme(page, theme);
      await mockApi(page, { "GET /auth/session": { ...guestSession, demo_mode: true }, "GET /atlas/tree.json": atlasTreePayload(), "GET /stats": statsPayload() });
      await page.goto("/");
      await expect(page.getByTestId("atlas-preview")).toHaveAttribute("data-state", "ready");
      await input(page).fill(STORY);
      await shot(page, `chat-landing-${theme}`, { fullPage: true });
    });
  }

  test("screenshot phone @mobile", async ({ page }) => {
    await mockApi(page, { "GET /auth/session": guestSession, "GET /atlas/tree.json": atlasTreePayload(), "GET /stats": statsPayload() });
    await page.goto("/");
    await expect(page.getByTestId("atlas-preview")).toHaveAttribute("data-state", "ready");
    await shot(page, "chat-landing-mobile", { fullPage: true });
  });
});
