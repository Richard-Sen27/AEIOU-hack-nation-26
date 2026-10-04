/**
 * Anonymous page and feature counting on the hosted site (self-hosted Umami,
 * docs/compliance.md "MUST NOT").
 *
 * URLs and titles here name diseases, chats, studies and conversations, so the analytics server
 * only ever gets a route pattern ("/node/[id]"), never a real path, query string, hash or title.
 * Feature events are a fixed list of names with properties from fixed lists (`EVENTS`), so no
 * id, name, search text or message can be sent. The component that loads the script is
 * components/shell/page-counter.tsx; features call `trackEvent`.
 */

import { NODE_TYPES } from "./graph/types";

export const ANALYTICS_SCRIPT_SRC = "https://analytics.deploy.richard-senger.com/script.js";
export const ANALYTICS_WEBSITE_ID = "4ba2d6ba-9405-49a5-9315-2ecf23f64572";
/** The only host names that count pages. Local dev, local production builds and tests never match. */
export const ANALYTICS_HOSTNAMES = ["frontend-production-aa5a.up.railway.app"];
/** Global the script calls before every send (`data-before-send`). */
export const BEFORE_SEND_GLOBAL = "__amberAnalyticsBeforeSend";

/** Every page in src/app, as Next.js names it. The unit test keeps this in sync with the folders. */
export const ROUTE_PATTERNS = [
  "/",
  "/about-data",
  "/atlas",
  "/calls",
  "/calls/[id]",
  "/calls/mine",
  "/calls/mine/[id]",
  "/calls/mine/new",
  "/calls/signups",
  "/chat",
  "/clusters",
  "/documents",
  "/documents/[id]",
  "/guide",
  "/messages",
  "/messages/[id]",
  "/node/[id]",
  "/path",
  "/people/[card_id]",
  "/privacy",
  "/profile",
  "/welcome",
] as const;

/** Any path that is not one of the pages above (a 404, a typo): its text is never sent. */
export const OTHER_PAGE = "/[other]";

const isDynamic = (segment: string) => segment.startsWith("[") && segment.endsWith("]");
const split = (path: string) => path.split("/").filter(Boolean);

/** Static segments win over dynamic ones ("/calls/mine" before "/calls/[id]"). */
const PATTERNS = ROUTE_PATTERNS.map((pattern) => ({ pattern, segments: split(pattern) })).sort((a, b) => {
  for (let i = 0; i < Math.min(a.segments.length, b.segments.length); i++) {
    const d = Number(isDynamic(a.segments[i])) - Number(isDynamic(b.segments[i]));
    if (d !== 0) return d;
  }
  return 0;
});

/** The route pattern of a path or same-site URL: no ids, no query string, no hash. */
export function routePattern(pathOrUrl: string): string {
  let path = pathOrUrl.split(/[?#]/, 1)[0];
  if (/^[a-z][a-z0-9+.-]*:/i.test(path)) {
    try {
      path = new URL(path).pathname;
    } catch {
      return OTHER_PAGE;
    }
  }
  const segments = split(path);
  const match = PATTERNS.find(
    (p) => p.segments.length === segments.length && p.segments.every((s, i) => isDynamic(s) || s === segments[i]),
  );
  return match ? match.pattern : OTHER_PAGE;
}

/** In-app referrer → its route pattern; another site → that site's origin only; anything else → "". */
export function redactReferrer(referrer: string, origin: string): string {
  if (!referrer) return "";
  let url: URL;
  try {
    url = new URL(referrer);
  } catch {
    return "";
  }
  if (url.origin === origin) return routePattern(url.pathname);
  if (url.protocol !== "https:" && url.protocol !== "http:") return "";
  return `${url.origin}/`;
}

/** Whether this page load counts at all: the hosted site only, unless switched off at build time. */
export function analyticsAllowed(hostname: string): boolean {
  if (process.env.NODE_ENV !== "production" || process.env.NEXT_PUBLIC_ANALYTICS === "off") return false;
  return ANALYTICS_HOSTNAMES.includes(hostname);
}

/**
 * The only feature events, each with its only properties and their only values. Adding a
 * property means adding a fixed list here: never an id, a name, search or message text.
 */
export const EVENTS = {
  wu_question: { surface: ["dock", "full"] },
  summary_written: {},
  node_selected: { kind: NODE_TYPES },
  search_used: { surface: ["header", "atlas"] },
  path_search: {},
  gap_search: {},
  export: { format: ["proposal", "csv", "graphml"] },
  follow: { source: ["disease", "profile"] },
  unfollow: {},
  call_submitted: { outcome: ["published", "review"] },
  signup_submitted: {},
  message_sent: { kind: ["request", "reply"] },
  report_uploaded: {},
  tour_started: {},
  tour_finished: {},
  sign_in_started: { provider: ["openai", "google"] },
} as const satisfies Record<string, Record<string, readonly string[]>>;

type Events = typeof EVENTS;
export type EventName = keyof Events;
export type EventProps<N extends EventName> = { [K in keyof Events[N]]: Events[N][K] extends readonly (infer V)[] ? V : never };
type PropsArg<N extends EventName> = keyof Events[N] extends never ? [] : [props: EventProps<N>];

/** `data` for an allowed event, or null when the name, a key or a value is not on the list. */
export function eventData(name: unknown, props: unknown = {}): Record<string, string> | null {
  if (typeof name !== "string" || !Object.hasOwn(EVENTS, name)) return null;
  if (!props || typeof props !== "object" || Array.isArray(props)) return null;
  const schema: Record<string, readonly string[]> = EVENTS[name as EventName];
  const given = props as Record<string, unknown>;
  const keys = Object.keys(schema);
  if (Object.keys(given).length !== keys.length) return null;
  const out: Record<string, string> = {};
  for (const key of keys) {
    const value = given[key];
    if (typeof value !== "string" || !schema[key].includes(value)) return null;
    out[key] = value;
  }
  return out;
}

type UmamiProps = { website?: string; hostname?: string; screen?: string; language?: string };
type Umami = { track: (build: (props: UmamiProps) => object) => Promise<unknown> };

/** The script's global; present only after the page counter loaded it on the hosted site. */
export function umamiClient(): Umami | null {
  if (typeof window === "undefined" || !analyticsAllowed(window.location.hostname)) return null;
  return (window as Window & { umami?: Umami }).umami ?? null;
}

/**
 * Count one use of a feature, at the point where it succeeded. A no-op off the hosted site, in
 * dev and in tests (no script, no `umami`). Sends the event name, its fixed properties and the
 * current route pattern; never a title, id or text.
 */
export function trackEvent<N extends EventName>(name: N, ...props: PropsArg<N>): void {
  const umami = umamiClient();
  const data = eventData(name, props[0] ?? {});
  if (!umami || !data) return;
  const url = routePattern(window.location.pathname);
  void umami.track((p) => ({
    website: p.website,
    hostname: p.hostname,
    screen: p.screen,
    language: p.language,
    url,
    name,
    ...(Object.keys(data).length ? { data } : {}),
  }));
}

/** What one page view or event may carry. Nothing else reaches the server. */
export type AnalyticsPayload = {
  website: string;
  hostname: string;
  url: string;
  referrer?: string;
  screen?: string;
  language?: string;
  name?: EventName;
  data?: Record<string, string>;
};

const ALLOWED_URLS = new Set<string>([...ROUTE_PATTERNS, OTHER_PAGE]);
const SCREEN = /^\d{1,5}x\d{1,5}$/;
const LANGUAGE = /^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8}){0,3}$/;

/**
 * Last check before anything is sent (the script's `data-before-send` hook). Only page views
 * with a route pattern and redacted referrer, and allowed events, pass, rebuilt from the
 * allowed fields; `identify` calls and anything with a title, id, unknown event name or value
 * are dropped (null cancels the send).
 */
export function beforeSend(type: string, payload: unknown): AnalyticsPayload | null {
  if (type !== "event" || !payload || typeof payload !== "object") return null;
  const p = payload as Record<string, unknown>;
  if (p.id !== undefined || p.title !== undefined || p.tag !== undefined) return null;
  if (typeof p.url !== "string" || !ALLOWED_URLS.has(p.url)) return null;
  if (p.website !== ANALYTICS_WEBSITE_ID || typeof p.hostname !== "string") return null;
  if (!ANALYTICS_HOSTNAMES.includes(p.hostname)) return null;
  const out: AnalyticsPayload = { website: p.website, hostname: p.hostname, url: p.url };
  if (typeof p.screen === "string" && SCREEN.test(p.screen)) out.screen = p.screen;
  if (typeof p.language === "string" && LANGUAGE.test(p.language)) out.language = p.language;
  if (p.name !== undefined) {
    const data = eventData(p.name, p.data ?? {});
    if (!data || p.referrer !== undefined) return null;
    out.name = p.name as EventName;
    if (Object.keys(data).length) out.data = data;
    return out;
  }
  if (p.data !== undefined) return null;
  const referrer = typeof p.referrer === "string" ? p.referrer : "";
  if (referrer && !ALLOWED_URLS.has(referrer) && !/^https?:\/\/[^/?#]+\/$/.test(referrer)) return null;
  if (referrer) out.referrer = referrer;
  return out;
}
