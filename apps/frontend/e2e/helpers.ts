/**
 * Shared Playwright helpers for every feature:
 *
 *   await mockApi(page, {
 *     "GET /auth/session": signedInSession({ role: "patient" }),
 *     "GET /search": { results: [hit("MONDO:0100135", "disease", "STXBP1 encephalopathy")] },
 *     "POST /chat": sseBody([{ type: "summary_delta", text: "Hi" }, { type: "done" }]),
 *     "GET /node/*": (req) => ({ json: { id: decodeURIComponent(req.url.split("/").pop()!) } }),
 *   });
 *   const errors = trackConsoleErrors(page);
 *   await page.goto("/");
 *   await shot(page, "landing-light");        // → e2e/screenshots/landing-light.png
 *   expect(errors()).toEqual([]);
 *
 * Unmatched API requests are aborted by default (= API down), so tests never
 * depend on a running backend. Pass `{ fallback: "passthrough" }` to hit it.
 */
import type { Page, Request, Route } from "@playwright/test";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

type MockResult = {
  status?: number;
  json?: unknown;
  /** Raw body (e.g. from `sseBody`). */
  body?: string;
  contentType?: string;
  headers?: Record<string, string>;
};
type Mock =
  | MockResult
  | ((req: { url: string; method: string; body: unknown; request: Request }) => MockResult | Promise<MockResult>)
  | "offline";

/** Mark a plain JSON payload. Objects without status/json/body keys are treated as JSON. */
function normalise(m: unknown): MockResult {
  if (m && typeof m === "object" && ("json" in m || "body" in m || "status" in m)) return m as MockResult;
  return { json: m };
}

/**
 * Route API calls. Keys: `"METHOD /path"` or `"/path"` (any method); `*`
 * matches one path segment, `**` anything. Query strings are ignored for
 * matching (read them from `req.url` in a function mock).
 */
export async function mockApi(
  page: Page,
  mocks: Record<string, Mock | unknown>,
  { fallback = "offline" }: { fallback?: "offline" | "passthrough" | "not_implemented" } = {},
) {
  const table = Object.entries(mocks).map(([key, mock]) => {
    const [method, path] = key.includes(" ") ? key.split(" ", 2) : ["*", key];
    const re = new RegExp(
      "^" +
        path
          .replace(/[.+?^${}()|[\]\\]/g, "\\$&")
          .replace(/\*\*/g, "\u0000")
          .replace(/\*/g, "[^/]+")
          .replace(/\u0000/g, ".*") +
        "$",
    );
    return { method: method.toUpperCase(), re, mock };
  });

  await page.route(`${API_URL}/**`, async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const entry = table.find(
      (t) => (t.method === "*" || t.method === request.method()) && t.re.test(url.pathname),
    );
    if (!entry) {
      if (fallback === "passthrough") return route.continue();
      if (fallback === "not_implemented") {
        return route.fulfill(errorEnvelope(501, "not_implemented", "Not implemented"));
      }
      return route.abort("connectionrefused");
    }
    if (entry.mock === "offline") return route.abort("connectionrefused");
    let body: unknown = undefined;
    try {
      body = request.postDataJSON();
    } catch {
      body = request.postData();
    }
    const result =
      typeof entry.mock === "function"
        ? await (entry.mock as Exclude<Mock, MockResult | "offline">)({
            url: request.url(),
            method: request.method(),
            body,
            request,
          })
        : normalise(entry.mock);
    return route.fulfill({
      status: result.status ?? 200,
      headers: {
        "access-control-allow-origin": new URL(page.url() || "http://127.0.0.1").origin,
        "access-control-allow-credentials": "true",
        ...result.headers,
      },
      contentType: result.contentType ?? (result.body !== undefined ? "text/plain" : "application/json"),
      body: result.body ?? JSON.stringify(result.json ?? {}),
    });
  });
}

export function errorEnvelope(status: number, code: string, message = code): MockResult {
  return { status, json: { error: { code, message } } };
}

/** SSE response body from JSON events (each must carry `type`). */
export function sseBody(events: Array<{ type: string } & Record<string, unknown>>): MockResult {
  return {
    contentType: "text/event-stream",
    body: events.map((e) => `event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join(""),
  };
}

export const guestSession = { user: null, gpc: false, demo_mode: false, data_version: "test" };

export function signedInSession(user: Record<string, unknown> = {}) {
  return {
    ...guestSession,
    user: {
      id: "00000000-0000-0000-0000-000000000001",
      name: "Maria Example",
      email: "maria@example.org",
      role: "patient",
      role_verified: false,
      language: "en",
      expert_mode: false,
      age_confirmed: true,
      consents: [],
      ...user,
    },
  };
}

export function hit(id: string, type: string, label: string, matched_synonym?: string) {
  return { id, type, label, matched_synonym: matched_synonym ?? null, score: 1 };
}

/**
 * Collect console errors and uncaught page errors. Call before `goto`.
 * Failed requests to the (mocked-offline) API are ignored by default.
 */
export function trackConsoleErrors(page: Page, { ignoreApiFailures = true } = {}) {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (ignoreApiFailures && /Failed to load resource|ERR_CONNECTION_REFUSED|net::ERR_FAILED/.test(text)) return;
    errors.push(text);
  });
  page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
  return () => errors;
}

/** Force light or dark before navigation (next-themes reads localStorage). */
export async function setTheme(page: Page, theme: "light" | "dark" | "system") {
  await page.addInitScript((t) => {
    try {
      window.localStorage.setItem("theme", t);
    } catch {}
  }, theme);
}

/** Screenshot into e2e/screenshots/<name>.png (git-ignored) and return the path. */
export async function shot(page: Page, name: string, { fullPage = false } = {}) {
  const path = `e2e/screenshots/${name}.png`;
  await page.screenshot({ path, fullPage, animations: "disabled" });
  return path;
}
