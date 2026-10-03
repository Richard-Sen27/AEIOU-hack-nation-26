import { defineConfig, devices } from "@playwright/test";

/**
 * E2E + screenshots. Starts its own `next dev` unless one is already running
 * on PORT. Parallel agents: give each run its own port and dist dir, e.g.
 *
 *   PORT=3104 NEXT_DIST_DIR=.next-atlas pnpm test:e2e
 *
 * API calls are mocked per test with `mockApi()` from e2e/helpers.ts; without
 * a mock, requests go to NEXT_PUBLIC_API_URL (default http://127.0.0.1:8000).
 */
const PORT = Number(process.env.PORT || 3109);
const DIST = process.env.NEXT_DIST_DIR || ".next-e2e";
const BASE_URL = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  // The live suite (real API) has its own config: playwright.live.config.ts.
  testIgnore: ["live/**"],
  outputDir: "./test-results",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  timeout: 60_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } }, grepInvert: /@mobile/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, grep: /@mobile/ },
  ],
  webServer: {
    command: `pnpm exec next dev --hostname 127.0.0.1 --port ${PORT}`,
    url: BASE_URL,
    reuseExistingServer: true,
    timeout: 180_000,
    env: { NEXT_DIST_DIR: DIST, NEXT_TELEMETRY_DISABLED: "1" },
    stdout: "ignore",
    stderr: "pipe",
  },
});
