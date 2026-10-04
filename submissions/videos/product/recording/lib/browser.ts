// Launches the Playwright-managed Chromium the way every take needs it:
// real GPU (the Atlas is WebGL), light theme, 1920×1080 device pixels, the
// drawn cursor, and the session cookie when one is given.

import {
  chromium,
  type Browser,
  type BrowserContext,
  type Page,
} from "playwright";
import {
  BASE_URL,
  DEVICE_SCALE,
  HEADED,
  SESSION_COOKIE,
  SESSION_COOKIE_NAME,
  VIEWPORT,
} from "./config.ts";
import { CURSOR_INIT_SCRIPT } from "./cursor.ts";

export type Session = {
  readonly browser: Browser;
  readonly context: BrowserContext;
  readonly page: Page;
};

export async function openSession({
  signedIn,
}: {
  signedIn: boolean;
}): Promise<Session> {
  if (signedIn && !SESSION_COOKIE) {
    throw new Error(
      `This take needs a signed-in user: export AMBER_SESSION=<value of the ${SESSION_COOKIE_NAME} cookie> and run again.`,
    );
  }
  const browser = await chromium.launch({
    headless: !HEADED,
    // Without these, headless Chromium falls back to software WebGL
    // (SwiftShader), which draws the ~21k-edge Atlas far too slowly.
    args: [
      "--enable-gpu",
      "--ignore-gpu-blocklist",
      "--use-angle=metal",
      "--hide-scrollbars",
      "--force-color-profile=srgb",
    ],
  });
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: DEVICE_SCALE,
    colorScheme: "light",
    reducedMotion: "no-preference",
    locale: "en-US",
    timezoneId: "Europe/Berlin",
  });
  // The app keeps its theme choice in localStorage ("theme"); pin it to light
  // so the machine's dark mode never leaks into a take.
  await context.addInitScript(() => {
    try {
      window.localStorage.setItem("theme", "light");
    } catch {
      // Storage blocked: colorScheme above still asks for light.
    }
  });
  await context.addInitScript(CURSOR_INIT_SCRIPT);
  if (signedIn) {
    const url = new URL(BASE_URL);
    await context.addCookies([
      {
        name: SESSION_COOKIE_NAME,
        value: SESSION_COOKIE,
        domain: url.hostname,
        path: "/",
        httpOnly: true,
        secure: url.protocol === "https:",
        sameSite: "Lax",
      },
    ]);
  }
  const page = await context.newPage();
  page.setDefaultTimeout(30_000);
  return { browser, context, page };
}

export function url(pathname: string): string {
  return `${BASE_URL}${pathname}`;
}

// Fails a take early when the map is not really drawn: WebGL must run on the
// GPU, not on a software rasteriser.
export async function assertGpuWebgl(page: Page): Promise<string> {
  const renderer = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    const gl = (canvas.getContext("webgl2") ||
      canvas.getContext("webgl")) as WebGLRenderingContext | null;
    if (!gl) return "none";
    const info = gl.getExtension("WEBGL_debug_renderer_info");
    return String(
      info
        ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL)
        : gl.getParameter(gl.RENDERER),
    );
  });
  if (/swiftshader|software|llvmpipe|none/i.test(renderer)) {
    throw new Error(
      `WebGL runs on "${renderer}", not the GPU; try RECORD_HEADED=1.`,
    );
  }
  return renderer;
}
