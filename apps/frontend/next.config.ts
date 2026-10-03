import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Several agents run `next dev` side by side, each with its own output dir
  // (NEXT_DIST_DIR=.next-<name>) and port.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // The Docker image sets NEXT_OUTPUT=standalone; dev and `next start` are unchanged.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  poweredByHeader: false,
  experimental: {
    // Keeps `next dev` from appending `<distDir>/types/**` globs to
    // tsconfig.json for every custom distDir; route types are pulled in via
    // next-env.d.ts instead.
    strictRouteTypes: true,
  },
};

export default nextConfig;
