// Helpers for the Atlas page (/atlas): wait until the map is drawn, and move
// its sigma.js camera smoothly from inside the page.

import type { Page } from "playwright";

// The map is ready when the counts are in, the "Drawing the map…" notice is
// gone and the WebGL canvas exists.
export async function waitForAtlas(page: Page): Promise<void> {
  await page
    .getByTestId("atlas-counts")
    .getByText(/items · [\d,]+ connections/)
    .waitFor({ timeout: 60_000 });
  await page
    .getByTestId("atlas-canvas")
    .locator("canvas")
    .first()
    .waitFor({ timeout: 60_000 });
  await page
    .getByText("Drawing the map")
    .waitFor({ state: "hidden", timeout: 60_000 });
}

type CameraState = { x: number; y: number; ratio: number };

// The app keeps its sigma instance in a React ref and exposes no handle, so
// this finds it through the canvas element's React fiber (read-only lookup,
// recording only). Stored on window.__recSigma for the calls below.
async function findSigma(page: Page): Promise<void> {
  const found = await page.evaluate(() => {
    const host = document.querySelector('[data-testid="atlas-canvas"]');
    if (!host) return false;
    const key = Object.keys(host).find((k) => k.startsWith("__reactFiber$"));
    type Hook = { memoizedState?: unknown; next?: Hook | null };
    type Fiber = { memoizedState?: Hook | null; return?: Fiber | null };
    let fiber = key
      ? ((host as unknown as Record<string, Fiber>)[key] ?? null)
      : null;
    for (
      let depth = 0;
      fiber && depth < 40;
      depth++, fiber = fiber.return ?? null
    ) {
      for (
        let hook = fiber.memoizedState ?? null;
        hook;
        hook = hook.next ?? null
      ) {
        const ref = hook.memoizedState as {
          current?: { getCamera?: unknown };
        } | null;
        if (
          ref &&
          typeof ref === "object" &&
          ref.current &&
          typeof ref.current.getCamera === "function"
        ) {
          (window as unknown as { __recSigma: unknown }).__recSigma =
            ref.current;
          return true;
        }
      }
    }
    return false;
  });
  if (!found)
    throw new Error(
      "Could not find the Atlas camera (sigma instance) on the page.",
    );
}

export async function getCamera(page: Page): Promise<CameraState> {
  await findSigma(page);
  return page.evaluate(() => {
    const sigma = (
      window as unknown as {
        __recSigma: { getCamera: () => { getState: () => CameraState } };
      }
    ).__recSigma;
    const { x, y, ratio } = sigma.getCamera().getState();
    return { x, y, ratio };
  });
}

export async function setCamera(page: Page, state: CameraState): Promise<void> {
  await findSigma(page);
  await page.evaluate((s) => {
    const sigma = (
      window as unknown as {
        __recSigma: { getCamera: () => { setState: (s: CameraState) => void } };
      }
    ).__recSigma;
    sigma.getCamera().setState(s);
  }, state);
}

// Camera coordinates of a point on screen (CSS pixels relative to the canvas).
export async function cameraPointAt(
  page: Page,
  point: { x: number; y: number },
): Promise<{ x: number; y: number }> {
  await findSigma(page);
  return page.evaluate((p) => {
    const sigma = (
      window as unknown as {
        __recSigma: {
          viewportToFramedGraph: (p: { x: number; y: number }) => {
            x: number;
            y: number;
          };
        };
      }
    ).__recSigma;
    return sigma.viewportToFramedGraph(p);
  }, point);
}

// Zooms the camera from `from` to `to` over `durationMs`, driven by the page's
// own animation frames so every painted frame is on the curve. The zoom is
// eased in log space and the position follows the zoom, so the starting spot
// stays put while the map opens up around it. Resolves when it has finished.
export async function flyCamera(
  page: Page,
  from: CameraState,
  to: CameraState,
  durationMs: number,
): Promise<void> {
  await findSigma(page);
  await page.evaluate(
    ({ from, to, durationMs }) =>
      new Promise<void>((resolve) => {
        const sigma = (
          window as unknown as {
            __recSigma: {
              getCamera: () => { setState: (s: CameraState) => void };
            };
          }
        ).__recSigma;
        const camera = sigma.getCamera();
        // Smootherstep: zero velocity and acceleration at both ends.
        const ease = (t: number) => t * t * t * (t * (t * 6 - 15) + 10);
        const logFrom = Math.log(from.ratio);
        const logTo = Math.log(to.ratio);
        const t0 = performance.now();
        const tick = (now: number) => {
          const t = Math.min(1, (now - t0) / durationMs);
          const s = ease(t);
          const ratio = Math.exp(logFrom + (logTo - logFrom) * s);
          const k =
            to.ratio === from.ratio
              ? s
              : (ratio - from.ratio) / (to.ratio - from.ratio);
          camera.setState({
            x: from.x + (to.x - from.x) * k,
            y: from.y + (to.y - from.y) * k,
            ratio,
          });
          if (t < 1) requestAnimationFrame(tick);
          else resolve();
        };
        requestAnimationFrame(tick);
      }),
    { from, to, durationMs },
  );
}
