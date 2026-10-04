import { readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

import { expect, test } from "@playwright/test";

import {
  ANALYTICS_HOSTNAMES,
  ANALYTICS_WEBSITE_ID,
  EVENTS,
  OTHER_PAGE,
  ROUTE_PATTERNS,
  analyticsAllowed,
  beforeSend,
  eventData,
  redactReferrer,
  routePattern,
  trackEvent,
} from "../../src/lib/analytics";
import { guestSession, mockApi } from "../helpers";

const APP_DIR = join(__dirname, "../../src/app");
const HOST = ANALYTICS_HOSTNAMES[0];
const ORIGIN = `https://${HOST}`;
const ANALYTICS_HOST = "analytics.deploy.richard-senger.com";

/** Every page.tsx under src/app as a Next.js route ("/node/[id]"); route groups dropped. */
function appRoutes(dir = APP_DIR): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) out.push(...appRoutes(full));
    else if (name === "page.tsx") {
      const segments = relative(APP_DIR, dir).split(sep).filter((s) => s && !/^\(.*\)$/.test(s));
      out.push(`/${segments.join("/")}`);
    }
  }
  return out;
}

/** A realistic real path for each dynamic route: ids that must never reach the server. */
const REAL: Record<string, string[]> = {
  "/node/[id]": ["/node/MONDO:0100135", "/node/MONDO%3A0100135", "/node/HGNC:10585", "/node/DOC:2b11f0e39516"],
  "/calls/[id]": ["/calls/0b6a8a52-6f0e-4bde-9a3c-1f1e2d3c4b5a"],
  "/calls/mine/[id]": ["/calls/mine/0b6a8a52-6f0e-4bde-9a3c-1f1e2d3c4b5a"],
  "/documents/[id]": ["/documents/doc-1", "/documents/7c9e6679-7425-40de-944b-e07fc1f90ae7"],
  "/messages/[id]": ["/messages/3f2504e0-4f89-11d3-9a0c-0305e82c3301"],
  "/people/[card_id]": ["/people/card-8d0e"],
};

test.describe("analytics redaction (unit)", () => {
  test("the pattern list matches the pages in src/app", () => {
    expect([...ROUTE_PATTERNS].sort()).toEqual(appRoutes().sort());
  });

  test("every dynamic route: real path in, pattern out, with query strings, hashes and full URLs", () => {
    const dynamic = ROUTE_PATTERNS.filter((p) => p.includes("["));
    expect(Object.keys(REAL).sort()).toEqual([...dynamic].sort());
    for (const [pattern, paths] of Object.entries(REAL)) {
      for (const path of paths) {
        for (const variant of [
          path,
          `${path}/`,
          `${path}?from=MONDO:0011794&to=HGNC:10585`,
          `${path}#section-genes`,
          `${path}?q=dravet%20syndrome#x`,
          `${ORIGIN}${path}?session=abc#top`,
        ]) {
          const out = routePattern(variant);
          expect(out, variant).toBe(pattern);
          expect(out).not.toMatch(/MONDO|HGNC|DOC:|doc-1|card-8d0e|[0-9a-f]{8}-/);
        }
      }
    }
  });

  test("static routes keep their name and lose query strings and hashes; static beats dynamic", () => {
    expect(routePattern("/")).toBe("/");
    expect(routePattern("/path?from=MONDO:0100135&to=MONDO:0011794")).toBe("/path");
    expect(routePattern("/chat?session=8d0e5c&q=seizures")).toBe("/chat");
    expect(routePattern("/about-data?entry=DOC:2b11f0e39516")).toBe("/about-data");
    expect(routePattern("/welcome?next=/node/MONDO:0100135")).toBe("/welcome");
    expect(routePattern("/profile#health-profile")).toBe("/profile");
    expect(routePattern("/calls/mine")).toBe("/calls/mine");
    expect(routePattern("/calls/mine/new")).toBe("/calls/mine/new");
    expect(routePattern("/calls/signups")).toBe("/calls/signups");
  });

  test("unknown paths become one fixed value, never their text", () => {
    for (const p of ["/MONDO:0100135", "/node", "/node/MONDO:1/extra", "/dravet-syndrome", "not a url", ""]) {
      expect(routePattern(p), p).toBe(p === "" ? "/" : OTHER_PAGE);
    }
  });

  test("referrer: in-app becomes its pattern, another site its origin only", () => {
    expect(redactReferrer(`${ORIGIN}/node/MONDO:0100135?x=1#y`, ORIGIN)).toBe("/node/[id]");
    expect(redactReferrer(`${ORIGIN}/chat?session=1`, ORIGIN)).toBe("/chat");
    expect(redactReferrer("https://www.google.com/search?q=dravet+syndrome", ORIGIN)).toBe("https://www.google.com/");
    expect(redactReferrer("https://forum.example.org/t/my-son-has-dravet/123", ORIGIN)).toBe("https://forum.example.org/");
    expect(redactReferrer("", ORIGIN)).toBe("");
    expect(redactReferrer("android-app://com.example/", ORIGIN)).toBe("");
    expect(redactReferrer("garbage", ORIGIN)).toBe("");
  });

  test("counts only on the hosted site, in production builds, unless switched off", () => {
    const env = process.env as Record<string, string | undefined>;
    const saved = { node: env.NODE_ENV, off: env.NEXT_PUBLIC_ANALYTICS };
    try {
      env.NODE_ENV = "production";
      delete env.NEXT_PUBLIC_ANALYTICS;
      expect(analyticsAllowed(HOST)).toBe(true);
      for (const h of ["127.0.0.1", "localhost", "example.com", `${HOST}.evil.com`]) expect(analyticsAllowed(h)).toBe(false);
      env.NEXT_PUBLIC_ANALYTICS = "off";
      expect(analyticsAllowed(HOST)).toBe(false);
      delete env.NEXT_PUBLIC_ANALYTICS;
      env.NODE_ENV = "development";
      expect(analyticsAllowed(HOST)).toBe(false);
    } finally {
      env.NODE_ENV = saved.node;
      if (saved.off === undefined) delete env.NEXT_PUBLIC_ANALYTICS;
      else env.NEXT_PUBLIC_ANALYTICS = saved.off;
    }
  });
});

test.describe("analytics events (unit)", () => {
  test("only allow-listed names and values pass", () => {
    expect(eventData("wu_question", { surface: "dock" })).toEqual({ surface: "dock" });
    expect(eventData("summary_written")).toEqual({});
    expect(eventData("node_selected", { kind: "disease" })).toEqual({ kind: "disease" });
    // Unknown name, unknown value, extra key, missing key, free text, non-string values.
    expect(eventData("question_text", { text: "my son has seizures" })).toBeNull();
    expect(eventData("wu_question", { surface: "my son has seizures" })).toBeNull();
    expect(eventData("wu_question", { surface: "dock", id: "MONDO:0100135" })).toBeNull();
    expect(eventData("wu_question", {})).toBeNull();
    expect(eventData("summary_written", { node: "MONDO:0100135" })).toBeNull();
    expect(eventData("node_selected", { kind: "MONDO:0100135" })).toBeNull();
    expect(eventData("node_selected", { kind: 1 })).toBeNull();
    expect(eventData("toString")).toBeNull();
    expect(eventData("__proto__")).toBeNull();
    expect(eventData("follow", ["disease"])).toBeNull();
  });

  test("every allow-listed value is a short fixed token", () => {
    for (const [name, schema] of Object.entries(EVENTS)) {
      expect(name).toMatch(/^[a-z_]+$/);
      for (const values of Object.values(schema as Record<string, readonly string[]>)) {
        for (const v of values) expect(v).toMatch(/^[a-z_]{2,20}$/);
      }
    }
  });

  test("the wrapper's types reject anything off the list", () => {
    // Compile-time checks (pnpm typecheck); trackEvent itself is a no-op here (no window).
    trackEvent("wu_question", { surface: "full" });
    trackEvent("tour_started");
    // @ts-expect-error unknown event name
    trackEvent("search_text", { q: "dravet" });
    // @ts-expect-error value not on the list
    trackEvent("wu_question", { surface: "sidebar" });
    // @ts-expect-error free text in a property
    trackEvent("node_selected", { kind: "disease", label: "Dravet syndrome" });
    // @ts-expect-error properties required
    trackEvent("export");
    // @ts-expect-error no properties allowed
    trackEvent("gap_search", { from: "MONDO:0100135" });
  });

  test("before-send: rebuilds allowed page views and events, drops everything else", () => {
    const base = { website: ANALYTICS_WEBSITE_ID, hostname: HOST, screen: "1440x900", language: "de-AT" };
    expect(beforeSend("event", { ...base, url: "/node/[id]", referrer: "/atlas" })).toEqual({ ...base, url: "/node/[id]", referrer: "/atlas" });
    expect(beforeSend("event", { ...base, url: "/", referrer: "https://www.google.com/" })).toEqual({ ...base, url: "/", referrer: "https://www.google.com/" });
    expect(beforeSend("event", { ...base, url: "/atlas", name: "node_selected", data: { kind: "gene" } })).toEqual({
      ...base,
      url: "/atlas",
      name: "node_selected",
      data: { kind: "gene" },
    });
    expect(beforeSend("event", { ...base, url: "/atlas", name: "tour_started" })).toEqual({ ...base, url: "/atlas", name: "tour_started" });
    // Raw paths, titles, ids, identify, unknown events or values, raw referrers, other hosts.
    expect(beforeSend("event", { ...base, url: "/node/MONDO:0100135" })).toBeNull();
    expect(beforeSend("event", { ...base, url: `${ORIGIN}/node/[id]` })).toBeNull();
    expect(beforeSend("event", { ...base, url: "/node/[id]", title: "Dravet syndrome · Amber" })).toBeNull();
    expect(beforeSend("event", { ...base, url: "/node/[id]", id: "user-1" })).toBeNull();
    expect(beforeSend("identify", { ...base, url: "/", data: { role: "patient" } })).toBeNull();
    expect(beforeSend("event", { ...base, url: "/", name: "chat", data: { text: "seizures" } })).toBeNull();
    expect(beforeSend("event", { ...base, url: "/", name: "wu_question", data: { surface: "seizures" } })).toBeNull();
    expect(beforeSend("event", { ...base, url: "/", data: { anything: "x" } })).toBeNull();
    expect(beforeSend("event", { ...base, url: "/", referrer: `${ORIGIN}/node/MONDO:0100135` })).toBeNull();
    expect(beforeSend("event", { ...base, url: "/", referrer: "https://www.google.com/search?q=dravet" })).toBeNull();
    expect(beforeSend("event", { ...base, hostname: "127.0.0.1", url: "/" })).toBeNull();
    expect(beforeSend("event", { ...base, website: "other", url: "/" })).toBeNull();
    // Screen and language only in their plain shapes.
    expect(beforeSend("event", { ...base, url: "/", screen: "dravet", language: "my son" })).toEqual({ website: base.website, hostname: HOST, url: "/" });
  });
});

test("the mocked suite never requests the analytics host", async ({ page }) => {
  const hits: string[] = [];
  page.on("request", (r) => {
    if (new URL(r.url()).hostname === ANALYTICS_HOST) hits.push(r.url());
  });
  // Belt and braces: should a regression load it, nothing leaves the machine.
  await page.route(`https://${ANALYTICS_HOST}/**`, (route) => route.abort());
  await mockApi(page, { "GET /auth/session": guestSession });
  for (const path of ["/", "/node/MONDO%3A0100135", "/chat", "/path?from=MONDO:0100135&to=MONDO:0011794", "/privacy"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  }
  expect(await page.locator(`script[src*="${ANALYTICS_HOST}"]`).count()).toBe(0);
  expect(await page.evaluate(() => "umami" in window)).toBe(false);
  expect(hits).toEqual([]);
});
