import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Parallel dev servers (NEXT_DIST_DIR=.next-<name>)
    ".next-*/**",
    // Generated API client (pnpm gen:api)
    "src/lib/api/generated/**",
    // Playwright output
    "test-results/**",
    "playwright-report/**",
  ]),
]);

export default eslintConfig;
