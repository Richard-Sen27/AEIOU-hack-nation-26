import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Several agents run `next dev` side by side, each with its own output dir
  // (NEXT_DIST_DIR=.next-<name>) and port.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // The Docker image sets NEXT_OUTPUT=standalone; dev and `next start` are unchanged.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  poweredByHeader: false,
  // Hosted deployments (docs/deploy-railway.md): API_PROXY_TARGET, read at build time, makes the
  // API same-origin so the SameSite=Lax session cookie works. /api/* goes to the API; /auth/* is
  // forwarded unprefixed so the OAuth callbacks match the sign-in cookies' paths. Unset locally.
  async rewrites() {
    const target = process.env.API_PROXY_TARGET?.replace(/\/+$/, "");
    if (!target) return [];
    return [
      { source: "/api/:path*", destination: `${target}/:path*` },
      { source: "/auth/:path*", destination: `${target}/auth/:path*` },
    ];
  },
  experimental: {
    // Proxied requests (the rewrites above) otherwise time out after 30 s, cutting chat streams.
    proxyTimeout: 10 * 60 * 1000,
    // Keeps `next dev` from appending `<distDir>/types/**` globs to
    // tsconfig.json for every custom distDir; route types are pulled in via
    // next-env.d.ts instead.
    strictRouteTypes: true,
  },
};

export default nextConfig;
