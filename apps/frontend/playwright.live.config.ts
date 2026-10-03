import { defineConfig, devices } from "@playwright/test";

/**
 * Live end-to-end suite: real API + mock OpenAI + real graph, no route mocks.
 * Start the three processes first (see e2e/live/live-helpers.ts), then:
 *
 *   PORT=3106 pnpm test:e2e:live
 *
 * It reuses the frontend already running on PORT (which must have been
 * started with NEXT_PUBLIC_API_URL pointing at the live API) and never
 * starts its own. Tests share one database and mock, so they run serially.
 */
const PORT = Number(process.env.PORT || 3106);

export default defineConfig({
  testDir: "./e2e/live",
  outputDir: "./test-results-live",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  timeout: 120_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
    actionTimeout: 20_000,
    // Real GPU in headless mode: the Atlas draws ~17k edges with WebGL, which
    // software rendering (SwiftShader) makes too slow to judge pan and zoom.
    launchOptions: { args: ["--enable-gpu", "--ignore-gpu-blocklist", "--use-angle=metal"] },
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } }, grepInvert: /@mobile/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, grep: /@mobile/ },
  ],
});
