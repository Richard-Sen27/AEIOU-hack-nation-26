import { expect, test } from "@playwright/test";

import { nodeHitPadding, nodeMinRadius, zoomToSizeRatio } from "../../src/components/atlas/atlas-model";

// Pure functions: no page needed.
test.describe("atlas zoom sizing", () => {
  test("follows Sigma's default at the overview and caps growth when zoomed in", () => {
    for (const r of [0.7, 1, 1.6, 2]) expect(zoomToSizeRatio(r)).toBeCloseTo(Math.sqrt(r), 10);
    // Growth (1 / ratio function) stays small however far the camera zooms in.
    expect(1 / zoomToSizeRatio(0.12)).toBeLessThan(1.4);
    expect(1 / zoomToSizeRatio(0.008)).toBeLessThan(1.6);
    // Monotonic: zooming in never shrinks items.
    let prev = Infinity;
    for (let r = 2; r > 0.005; r *= 0.9) {
      const v = zoomToSizeRatio(r);
      expect(v).toBeLessThanOrEqual(prev);
      prev = v;
    }
  });

  test("dots get a minimum radius and a wider hit area only when zoomed in", () => {
    for (const r of [0.7, 1, 2]) {
      expect(nodeMinRadius(r)).toBe(0);
      expect(nodeHitPadding(r)).toBe(0);
    }
    expect(nodeMinRadius(0.03)).toBeCloseTo(5.5, 5);
    expect(nodeMinRadius(0.008)).toBeCloseTo(5.5, 5);
    expect(nodeMinRadius(0.12)).toBeGreaterThan(2);
    expect(nodeHitPadding(0.01)).toBeCloseTo(4, 5);
  });
});
