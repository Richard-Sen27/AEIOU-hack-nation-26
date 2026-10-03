import { defineConfig } from "@hey-api/openapi-ts";

// `pnpm gen:api` — typed client from the FastAPI OpenAPI spec.
// The backend writes ../backend/openapi.json; regenerate after API changes.
export default defineConfig({
  input: "../backend/openapi.json",
  output: "src/lib/api/generated",
  plugins: [
    {
      name: "@hey-api/client-fetch",
      // Base URL, cookies and error routing (see src/lib/api/runtime-config.ts).
      runtimeConfigPath: "./src/lib/api/runtime-config",
    },
    "@hey-api/typescript",
    "@hey-api/sdk",
  ],
});
