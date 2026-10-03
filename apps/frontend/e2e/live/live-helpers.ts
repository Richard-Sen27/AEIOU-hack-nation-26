/**
 * Helpers for the live suite (real API + mock OpenAI, no `page.route` mocks).
 *
 * Start the three processes first (always 127.0.0.1, never localhost):
 *
 *   cd apps/backend && uv run python -m backend.devtools.mock_openai --port 8081
 *   cd apps/backend && OPENAI_AUTH_ISSUER=http://127.0.0.1:8081 \
 *     OPENAI_API_BASE_URL=http://127.0.0.1:8081/v1 \
 *     OPENAI_REDIRECT_URI=http://127.0.0.1:8080/auth/callback \
 *     API_URL=http://127.0.0.1:8080 FRONTEND_URL=http://127.0.0.1:3106 \
 *     uv run uvicorn backend.main:app --host 127.0.0.1 --port 8080
 *   cd apps/frontend && NEXT_PUBLIC_API_URL=http://127.0.0.1:8080 PORT=3106 \
 *     NEXT_DIST_DIR=.next-live pnpm dev
 *
 * then `PORT=3106 pnpm test:e2e:live`. The API must serve the real graph.
 */
import { expect, type APIRequestContext, type BrowserContext, type Page } from "@playwright/test";

export const API = (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8080").replace(/\/+$/, "");
export const MOCK = (process.env.MOCK_OPENAI_URL || "http://127.0.0.1:8081").replace(/\/+$/, "");

/** Demo-cluster ids from the real graph (stable across reloads). */
export const IDS = {
  stxbp1: "HGNC:11444",
  dee4: "MONDO:0012812",
  scn1a: "HGNC:10585",
  scn2a: "HGNC:10588",
};

export const STORY =
  "My daughter is 2, diagnosed with STXBP1 last month. Lots of seizures, not walking yet, no problems with eating.";

/**
 * Console errors, hydration warnings, page errors and failed API requests.
 * 401/403 from the API are expected (guest probes, gates) and ignored.
 */
export function trackProblems(page: Page, { allowStatus = [401, 403] }: { allowStatus?: number[] } = {}) {
  const problems: string[] = [];
  page.on("console", (msg) => {
    const text = msg.text();
    if (msg.type() === "error") {
      // The browser logs every non-2xx fetch; those are judged by status below.
      if (/Failed to load resource/.test(text)) return;
      problems.push(`console: ${text.slice(0, 300)}`);
    } else if (msg.type() === "warning" && /hydrat|did not match/i.test(text)) {
      problems.push(`hydration: ${text.slice(0, 300)}`);
    }
  });
  page.on("pageerror", (err) => problems.push(`pageerror: ${err.message.slice(0, 300)}`));
  page.on("response", (res) => {
    if (!res.url().startsWith(API)) return;
    const s = res.status();
    if (s >= 400 && !allowStatus.includes(s)) problems.push(`http ${s} ${res.request().method()} ${new URL(res.url()).pathname}`);
  });
  page.on("requestfailed", (req) => {
    if (!req.url().startsWith(API)) return;
    const reason = req.failure()?.errorText ?? "";
    // Navigations and SSE readers cancelled by the page itself are not failures.
    if (/ERR_ABORTED|aborted/i.test(reason)) return;
    problems.push(`failed ${req.method()} ${new URL(req.url()).pathname}: ${reason}`);
  });
  return () => problems;
}

/** Every URL the page requests, to prove free text never enters one. */
export function trackUrls(page: Page) {
  const urls: string[] = [];
  page.on("request", (r) => urls.push(r.url()));
  return urls;
}

export async function storageDump(page: Page) {
  return page.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }));
}

export async function setTheme(page: Page | BrowserContext, theme: "light" | "dark") {
  await page.addInitScript((t) => {
    try {
      window.localStorage.setItem("theme", t);
    } catch {}
  }, theme);
}

/** Screenshot into e2e/screenshots/live-<name>.png (git-ignored). */
export async function shot(page: Page, name: string, { fullPage = false } = {}) {
  await page.screenshot({ path: `e2e/screenshots/live-${name}.png`, fullPage, animations: "disabled" });
}

/** Reset the mock's queue and switches. */
export async function resetMock(request: APIRequestContext) {
  await request.post(`${MOCK}/_mock/reset`);
}

/** Script the next model answers (see backend/devtools/mock_openai/state.py `enqueue`). */
export async function queueModel(request: APIRequestContext, ...items: Record<string, unknown>[]) {
  const res = await request.post(`${MOCK}/_mock/queue`, { data: items });
  expect(res.ok()).toBeTruthy();
}

/**
 * Sign in through the real flow: click "Continue with ChatGPT" somewhere on
 * the page (caller opens it), then pick the mock user on the mock's consent
 * page. Returns once back on the frontend.
 */
export async function completeMockSignIn(page: Page, user: "alice" | "bob" | "carol") {
  await page.waitForURL((u) => u.origin === MOCK, { timeout: 15_000 });
  const url = new URL(page.url());
  url.searchParams.set("mock_user", user);
  await page.goto(url.toString());
  await page.waitForURL((u) => !u.origin.startsWith(MOCK) && !u.origin.startsWith(API), { timeout: 20_000 });
}

/** Sign in directly via the API start URL (for tests that do not test the button). */
export async function signInAs(page: Page, user: "alice" | "bob" | "carol", returnTo = "/") {
  await page.goto(`${API}/auth/chatgpt/start?return_to=${encodeURIComponent(returnTo)}`);
  await completeMockSignIn(page, user);
}

/** Pass the welcome step (role, 16+) if the app sent us there. */
export async function passWelcome(page: Page, role: RegExp = /Patient or family/) {
  if (!new URL(page.url()).pathname.startsWith("/welcome")) return;
  await page.getByRole("radio", { name: role }).check();
  await page.getByRole("checkbox", { name: /16 or older/ }).check();
  await page.getByRole("button", { name: /^Continue/ }).click();
  await page.waitForURL((u) => !u.pathname.startsWith("/welcome"), { timeout: 15_000 });
}

/** Delete the signed-in account through the app's API (cookies of the page). */
export async function deleteAccount(page: Page) {
  const res = await page.request.delete(`${API}/me`, { headers: { Origin: new URL(page.url()).origin } });
  expect([204, 401]).toContain(res.status());
}

/**
 * A one-page text PDF built in memory (Helvetica, one line per entry), for
 * upload tests. Only synthetic, made-up personal data goes in here.
 */
export function syntheticPdf(lines: string[]): Buffer {
  const esc = (t: string) => t.replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)");
  const text = lines.map((l, i) => `BT /F1 11 Tf 56 ${780 - i * 18} Td (${esc(l)}) Tj ET`).join("\n");
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    `<< /Length ${Buffer.byteLength(text)} >>\nstream\n${text}\nendstream`,
  ];
  let out = "%PDF-1.4\n";
  const offsets: number[] = [];
  objects.forEach((o, i) => {
    offsets.push(Buffer.byteLength(out));
    out += `${i + 1} 0 obj\n${o}\nendobj\n`;
  });
  const xref = Buffer.byteLength(out);
  out += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  out += offsets.map((n) => `${String(n).padStart(10, "0")} 00000 n \n`).join("");
  out += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(out, "latin1");
}

/** A synthetic genetic report with fake personal data and a VUS. */
export const GENETIC_REPORT = [
  "Genetic Testing Report - Example Genomics Laboratory",
  "Patient name: Jane Testperson. Date of birth: 01/02/2022.",
  "Address: 12 Example Street, Sampletown. Patient ID: MRN-0000123.",
  "Test: Epilepsy gene panel. Report date: 2026-09-15.",
  "Gene: STXBP1 Variant: c.1162C>T (p.Arg388Ter) Zygosity: heterozygous",
  "Classification: Pathogenic",
  "Gene: SCN2A Variant: c.2558G>A (p.Arg853Gln) Zygosity: heterozygous",
  "Classification: Variant of uncertain significance (VUS)",
];

/** What the model would extract from GENETIC_REPORT (classification, then extraction). */
export const GENETIC_REPORT_SCRIPT = [
  { json: { doc_type: "genetic_report" } },
  {
    json: {
      variants: [
        {
          gene: "STXBP1",
          hgvs: "c.1162C>T",
          zygosity: "heterozygous",
          classification: "pathogenic",
          test_date: "2026-09-15",
          page: 1,
          snippet: "Gene: STXBP1 Variant: c.1162C>T (p.Arg388Ter) Zygosity: heterozygous",
        },
        {
          gene: "SCN2A",
          hgvs: "c.2558G>A",
          zygosity: "heterozygous",
          classification: "uncertain_significance",
          test_date: "2026-09-15",
          page: 1,
          snippet: "Gene: SCN2A Variant: c.2558G>A (p.Arg853Gln) Zygosity: heterozygous",
        },
      ],
    },
  },
];
