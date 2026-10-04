import { expect, test, type Page } from "@playwright/test";

import { errorEnvelope, guestSession, mockApi, setTheme, signedInSession, trackConsoleErrors } from "../helpers";
import { expectNoHealthDataInBrowser } from "../account/fixtures";
import { graphMocks, stxbp1Summary, summaryMock } from "../graph/fixtures";

const SHOTS = process.env.FOLLOW_SHOTS_DIR;
const STXBP1 = "MONDO:9900007";
const DRAVET = "MONDO:0100135";

type Req = { url: string; method: string; body: unknown };

const follow = (node_id: string, label: string, extra: Record<string, unknown> = {}) => ({
  node_id,
  label,
  in_atlas: true,
  updates_available: true,
  created_at: "2026-10-04T08:00:00Z",
  since_version: "2026-10-04.9",
  ...extra,
});

const note = (id: string, extra: Record<string, unknown>) => ({
  id,
  kind: "added",
  disease_id: DRAVET,
  disease_label: "Dravet syndrome",
  item_id: "PMID:1",
  item_type: "paper",
  item_label: "A paper",
  registry_id: null,
  year: null,
  gone: false,
  data_version: "2026-10-04.10",
  created_at: "2026-10-04T08:00:00Z",
  read_at: null,
  ...extra,
});

const NOTES = [
  note("n1", { kind: "now_recruiting", item_id: DRAVET, item_type: "trial", registry_id: "NCT01234567", created_at: "2026-10-04T09:00:00Z" }),
  note("n2", { item_type: "paper", year: 2025, created_at: "2026-10-04T08:30:00Z" }),
  note("n3", { item_type: "trial", registry_id: "NCT07654321", created_at: "2026-10-04T08:20:00Z" }),
  note("n4", { item_type: "patient_org", created_at: "2026-10-04T08:10:00Z", read_at: "2026-10-04T08:15:00Z" }),
  note("n5", { item_type: null, item_label: null, gone: true, created_at: "2026-10-04T08:00:00Z" }),
];

/** Follow and notification routes with call logs; `consent` flips when the dialog grants it. */
function followMocks(opts: { follows?: unknown[]; consents?: string[]; put?: (r: Req) => unknown; notes?: unknown[]; user?: Record<string, unknown> } = {}) {
  const calls: Req[] = [];
  const state = { consents: opts.consents ?? ["health_data"], follows: [...(opts.follows ?? [])] as Array<{ node_id: string }>, count: 0 };
  const notes = opts.notes ?? NOTES;
  state.count = (notes as Array<{ read_at: string | null }>).filter((n) => !n.read_at).length;
  const log = (r: Req) => (calls.push(r), r);
  const mocks = {
    "GET /auth/session": () => ({ json: signedInSession({ consents: state.consents, ...opts.user }) }),
    "POST /consents": (r: Req) => {
      log(r);
      state.consents = [...state.consents, "health_data"];
      return { status: 201, json: { id: "c1", consent_type: "health_data", active: true, granted_at: new Date().toISOString() } };
    },
    "GET /me/follows": (r: Req) => (log(r), { json: { items: state.follows, limit: 50 } }),
    "PUT /me/follows": (r: Req) => {
      log(r);
      if (opts.put) return opts.put(r);
      const id = (r.body as { node_id: string }).node_id;
      const f = follow(id, id === DRAVET ? "Dravet syndrome" : "STXBP1 encephalopathy");
      state.follows = [f, ...state.follows];
      return { json: f };
    },
    "DELETE /me/follows": (r: Req) => (log(r), { status: 204, body: "" }),
    "POST /me/follows/from-profile": (r: Req) => (
      log(r),
      { json: { added: [follow(DRAVET, "Dravet syndrome")], already_following: [STXBP1], not_in_atlas: ["MONDO:0000001"], limit_reached: false } }
    ),
    "GET /notifications": (r: Req) => (log(r), { json: { items: notes, unread_count: state.count } }),
    "GET /notifications/unread-count": (r: Req) => (log(r), { json: { count: state.count } }),
    "POST /notifications/read": (r: Req) => {
      log(r);
      const b = r.body as { ids?: string[]; all?: boolean };
      state.count = b.all ? 0 : Math.max(0, state.count - (b.ids?.length ?? 0));
      return { json: { count: state.count } };
    },
  };
  return { mocks, calls, state };
}

const of = (calls: Req[], method: string, path: string) => calls.filter((c) => c.method === method && new URL(c.url).pathname === path);

async function openAtlas(page: Page, extra: Record<string, unknown>, summary: unknown = undefined) {
  await mockApi(page, graphMocks({ "GET /chat/sessions": [], ...(summary ? { "GET /atlas/summary/*": summary } : {}), ...extra }));
  await page.goto(`/atlas?focus=${STXBP1}`);
  await expect(page.getByTestId("atlas-panel").getByRole("heading", { name: "STXBP1 encephalopathy" })).toBeVisible();
}

test.describe("follow a disease", () => {
  test("guests get the sign-in dialog", async ({ page }) => {
    const { mocks, calls } = followMocks();
    await openAtlas(page, { ...mocks, "GET /auth/session": guestSession });
    const toggle = page.getByTestId("atlas-panel").getByTestId("follow-toggle");
    await expect(toggle).toHaveText(/Follow/);
    await toggle.click();
    await expect(page.getByTestId("sign-in-dialog")).toBeVisible();
    expect(of(calls, "PUT", "/me/follows")).toHaveLength(0);
    // No bell and no polling for guests.
    await expect(page.getByTestId("notifications-bell")).toHaveCount(0);
    expect(calls.filter((c) => c.url.includes("/notifications"))).toHaveLength(0);
  });

  test("first follow asks for the health-data consent, then toggles; the id goes in the body only", async ({ page }) => {
    const { mocks, calls } = followMocks({ consents: [] });
    const errors = trackConsoleErrors(page);
    await openAtlas(page, mocks);
    const toggle = page.getByTestId("atlas-panel").getByTestId("follow-toggle");
    await expect(toggle).toHaveAttribute("aria-pressed", "false");
    await toggle.click();
    const dialog = page.getByTestId("consent-dialog");
    await expect(dialog).toBeVisible();
    expect(of(calls, "PUT", "/me/follows")).toHaveLength(0);
    await dialog.getByRole("radio", { name: "My own" }).click();
    await dialog.getByRole("checkbox", { name: /explicitly consent/ }).click();
    await dialog.getByRole("button", { name: "I agree, continue" }).click();
    await expect(dialog).toBeHidden();

    await expect(toggle).toHaveText(/Following/);
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    const puts = of(calls, "PUT", "/me/follows");
    expect(puts).toHaveLength(1);
    expect(puts[0].body).toEqual({ node_id: STXBP1 });
    expect(new URL(puts[0].url).search).toBe("");
    await expect(page.getByTestId("follow-no-updates")).toHaveCount(0);

    await toggle.click();
    await expect(toggle).toHaveText(/^Follow/);
    const dels = of(calls, "DELETE", "/me/follows");
    expect(dels).toHaveLength(1);
    expect(dels[0].body).toEqual({ node_id: STXBP1 });
    await expectNoHealthDataInBrowser(page, ["follow", "Dravet"]);
    expect(errors()).toEqual([]);
  });

  test("the limit of 50 and a non-atlas id say so", async ({ page }) => {
    let status = 409;
    const { mocks } = followMocks({
      put: () => (status === 409 ? errorEnvelope(409, "conflict", "You can follow at most 50 diseases.") : errorEnvelope(404, "not_found", "x")),
    });
    await openAtlas(page, mocks);
    const panel = page.getByTestId("atlas-panel");
    await panel.getByTestId("follow-toggle").click();
    await expect(panel.getByTestId("follow-error")).toHaveText("You can follow up to 50 diseases.");
    await expect(panel.getByTestId("follow-toggle")).toHaveText(/^Follow/);
    status = 404;
    await panel.getByTestId("follow-toggle").click();
    await expect(panel.getByTestId("follow-error")).toHaveText("Not a disease in the atlas.");
  });

  test("a core disease says no updates are tracked", async ({ page }) => {
    const { mocks } = followMocks();
    await openAtlas(page, mocks, summaryMock({ [STXBP1]: { json: { ...stxbp1Summary(), coverage: "core" } } }));
    await expect(page.getByTestId("atlas-panel").getByTestId("follow-no-updates")).toHaveText("No updates tracked for this one");
  });

  test("node page: shows Following for a followed disease and unfollows", async ({ page }) => {
    const { mocks, calls } = followMocks({ follows: [follow(DRAVET, "Dravet syndrome")] });
    await mockApi(page, graphMocks(mocks));
    await page.goto(`/node/${encodeURIComponent(DRAVET)}`);
    const toggle = page.getByTestId("node-view").getByTestId("follow-toggle");
    await expect(toggle).toHaveText(/Following/);
    await toggle.click();
    await expect(toggle).toHaveText(/^Follow/);
    expect(of(calls, "DELETE", "/me/follows")[0].body).toEqual({ node_id: DRAVET });
    await toggle.click();
    await expect(toggle).toHaveText(/Following/);
    // Genes have no toggle.
    await page.goto(`/node/${encodeURIComponent("HGNC:11444")}`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByTestId("follow-toggle")).toHaveCount(0);
  });
});

test.describe("notifications", () => {
  test("bell: count, one line per kind, gone items, open marks read, mark all", async ({ page }) => {
    const { mocks, calls } = followMocks();
    const errors = trackConsoleErrors(page);
    await mockApi(page, graphMocks(mocks));
    await page.goto("/clusters");
    const bell = page.getByTestId("notifications-bell");
    await expect(bell.getByTestId("notifications-count")).toHaveText("4");
    await expect(bell).toHaveAttribute("aria-label", "Notifications, 4 unread");
    await bell.click();
    const items = page.getByTestId("notification");
    await expect(items).toHaveText([
      "New trial recruiting · Dravet syndrome · NCT01234567(unread)",
      "Added to the atlas · paper (2025) · Dravet syndrome(unread)",
      "Added to the atlas · trial · Dravet syndrome · NCT07654321(unread)",
      "Added to the atlas · patient group · Dravet syndrome",
      "Added to the atlas · item · Dravet syndrome(unread)No longer in the atlas",
    ]);
    await expect(page.getByTestId("notifications-list")).not.toContainText(/published/i);
    const gone = items.nth(4);
    await expect(gone).toHaveAttribute("data-gone", "true");
    await expect(gone.getByRole("link")).toHaveCount(0);

    await items.nth(0).getByRole("link").click();
    await expect(page).toHaveURL(new RegExp(`/node/${encodeURIComponent(DRAVET)}$`));
    expect(of(calls, "POST", "/notifications/read")[0].body).toEqual({ ids: ["n1"] });
    await expect(bell.getByTestId("notifications-count")).toHaveText("3");

    await bell.click();
    await page.getByTestId("notifications-mark-all").click();
    await expect(bell.getByTestId("notifications-count")).toHaveCount(0);
    expect(of(calls, "POST", "/notifications/read").at(-1)!.body).toEqual({ all: true });
    await expect(page.getByTestId("notifications-mark-all")).toBeDisabled();
    expect(errors()).toEqual([]);
  });

  test("empty state", async ({ page }) => {
    const { mocks } = followMocks({ notes: [] });
    await mockApi(page, mocks);
    await page.goto("/clusters");
    await page.getByTestId("notifications-bell").click();
    await expect(page.getByTestId("notifications-empty")).toHaveText("Nothing new yet.");
  });

  test("polls every 60 s only while visible, and on focus", async ({ page }) => {
    await page.clock.install();
    const { mocks, calls } = followMocks();
    await mockApi(page, mocks);
    await page.goto("/clusters");
    await expect(page.getByTestId("notifications-count")).toHaveText("4");
    const polls = () => of(calls, "GET", "/notifications/unread-count").length;
    const first = polls();
    expect(first).toBe(1);
    await page.clock.runFor(60_000);
    await expect.poll(polls).toBe(first + 1);

    await page.evaluate(() => {
      Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await page.clock.runFor(5 * 60_000);
    expect(polls()).toBe(first + 1);

    await page.evaluate(() => {
      Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await expect.poll(polls).toBe(first + 2);
    await page.clock.runFor(5_000);
    await page.evaluate(() => window.dispatchEvent(new Event("focus")));
    await expect.poll(polls).toBe(first + 3);
  });

  test("no bell and no polling before the 16+ confirmation", async ({ page }) => {
    const { mocks, calls } = followMocks({ user: { age_confirmed: false } });
    await mockApi(page, mocks);
    await page.goto("/privacy");
    await expect(page.getByTestId("user-menu")).toBeVisible();
    await page.waitForTimeout(1000);
    await expect(page.getByTestId("notifications-bell")).toHaveCount(0);
    expect(calls.filter((c) => c.url.includes("/notifications") || c.url.includes("/me/follows"))).toHaveLength(0);
  });

  test("header fits at 1024 px with the bell and a two-digit count", async ({ page }) => {
    const { mocks, state } = followMocks();
    state.count = 12;
    await mockApi(page, mocks);
    for (const width of [1024, 1100]) {
      await page.setViewportSize({ width, height: 800 });
      await page.goto("/atlas");
      const header = page.getByRole("banner");
      await expect(header.getByTestId("notifications-count")).toHaveText("9+");
      const links = header.getByRole("navigation", { name: "Primary" }).getByRole("link");
      const heights = await links.evaluateAll((els) => els.map((el) => el.getBoundingClientRect().height));
      expect(Math.max(...heights)).toBeLessThan(36);
      expect(Math.max(...heights) - Math.min(...heights)).toBeLessThan(1);
      expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
      // Theme toggle, bell, user menu in that order.
      const xs = await Promise.all(
        ["theme-toggle", "notifications-bell", "user-menu"].map(async (id) => (await header.getByTestId(id).first().boundingBox())!.x),
      );
      expect(xs[0]).toBeLessThan(xs[1]);
      expect(xs[1]).toBeLessThan(xs[2]);
    }
  });
});

test("profile: list, unfollow, follow the profile's diseases", async ({ page }) => {
  const { mocks, calls } = followMocks({ follows: [follow(STXBP1, "STXBP1 encephalopathy", { updates_available: false })] });
  await mockApi(page, { ...mocks, "GET /profile": {}, "GET /consents": [], "GET /contributions": [] });
  await page.goto("/profile");
  const section = page.getByTestId("following-section");
  await expect(section.getByTestId("following-item")).toHaveText([/STXBP1 encephalopathy\s*No updates tracked\s*Unfollow/]);
  await section.getByTestId("following-from-profile").click();
  await expect(section.getByTestId("following-result")).toHaveText("Added: Dravet syndrome. 1 not in the atlas.");
  await expect(section.getByTestId("following-item")).toHaveCount(2);
  expect(of(calls, "POST", "/me/follows/from-profile")).toHaveLength(1);
  await section.getByRole("button", { name: "Unfollow STXBP1 encephalopathy" }).click();
  await expect(section.getByTestId("following-item")).toHaveCount(1);
  await section.getByRole("button", { name: "Unfollow Dravet syndrome" }).click();
  await expect(section.getByTestId("following-empty")).toHaveText("Not following any disease.");
  await expectNoHealthDataInBrowser(page, ["Dravet", "STXBP1"]);
});

test("phone menu: unread dot and a Notifications entry with the list @mobile", async ({ page }) => {
  const { mocks } = followMocks();
  await mockApi(page, graphMocks(mocks));
  await page.goto("/clusters");
  await expect(page.getByTestId("menu-unread-dot")).toBeVisible();
  await page.getByRole("button", { name: "Open menu, 4 unread" }).click();
  const menu = page.getByRole("dialog", { name: "Menu" });
  const entry = menu.getByTestId("menu-notifications");
  await expect(entry.getByTestId("notifications-count")).toHaveText("4");
  await entry.click();
  await expect(menu.getByTestId("notification")).toHaveCount(5);
  await menu.getByTestId("notification").first().getByRole("link").click();
  await expect(page).toHaveURL(new RegExp(`/node/${encodeURIComponent(DRAVET)}$`));
  await expect(menu).toBeHidden();
});

test("screenshots", async ({ page }) => {
  test.skip(!SHOTS, "set FOLLOW_SHOTS_DIR");
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const theme of ["light", "dark"] as const) {
    for (const [w, h] of [[1440, 900], [390, 844]] as const) {
      const tag = `${w}-${theme}`;
      await setTheme(page, theme);
      await page.setViewportSize({ width: w, height: h });
      const { mocks } = followMocks({ follows: [follow(STXBP1, "STXBP1 encephalopathy"), follow("MONDO:0000002", "A core disease", { updates_available: false })] });
      await page.unrouteAll({ behavior: "ignoreErrors" });
      await mockApi(page, graphMocks({ "GET /chat/sessions": [], "GET /profile": {}, "GET /consents": [], "GET /contributions": [], ...mocks }));

      await page.goto(`/atlas?focus=${STXBP1}`);
      await expect(page.getByTestId("atlas-panel").getByTestId("follow-toggle")).toHaveText(/Following/);
      await page.screenshot({ path: `${SHOTS}/follow-panel-${tag}.png` });

      await page.goto(`/node/${encodeURIComponent(DRAVET)}`);
      await expect(page.getByTestId("node-view").getByTestId("follow-toggle")).toBeVisible();
      await page.screenshot({ path: `${SHOTS}/follow-node-${tag}.png` });

      if (w > 800) {
        await page.getByTestId("notifications-bell").click();
      } else {
        await page.getByRole("button", { name: /Open menu/ }).click();
        await page.getByTestId("menu-notifications").click();
      }
      await expect(page.getByTestId("notification")).toHaveCount(5);
      await page.screenshot({ path: `${SHOTS}/follow-bell-${tag}.png` });
      await page.keyboard.press("Escape");

      await page.goto("/profile");
      const section = page.locator("#following");
      await expect(section.getByTestId("following-item")).toHaveCount(2);
      await section.scrollIntoViewIfNeeded();
      await section.screenshot({ path: `${SHOTS}/follow-profile-${tag}.png` });
    }
  }
});
