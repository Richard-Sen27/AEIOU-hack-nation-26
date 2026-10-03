import { API_URL } from "./config";

/**
 * Initial config for the generated Hey API client (see openapi-ts.config.ts).
 * Kept free of generated imports so the project typechecks before
 * `pnpm gen:api` has run. Error routing is attached in `./client.ts`.
 */
export const createClientConfig = <T extends object>(config?: T) =>
  ({
    ...(config ?? {}),
    baseUrl: API_URL,
    credentials: "include",
  }) as T & { baseUrl: string; credentials: RequestCredentials };
