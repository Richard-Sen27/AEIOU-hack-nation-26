import { client } from "./generated/client.gen";
import { networkError, reportApiError, toApiError } from "./errors";

/**
 * The generated Hey API client, configured for Amber:
 * base URL from NEXT_PUBLIC_API_URL, `credentials: "include"` (via
 * runtime-config.ts), and every error converted to `ApiError` and routed to
 * the global sign-in / consent dialogs or a quiet toast.
 *
 * SDK calls return `{ data, error, response }`; `error` is an `ApiError`.
 * Pass `meta: { quiet: true }` to handle an error locally without the
 * global UI. Import SDK functions from `@/lib/api` (this module re-exports
 * them) so this setup is guaranteed to have run.
 */
let installed = false;

if (!installed) {
  installed = true;
  client.interceptors.error.use((error, response, _request, options) => {
    const apiError =
      response === undefined
        ? networkError(error)
        : toApiError(response.status, error);
    const meta = (options as { meta?: { quiet?: boolean } } | undefined)?.meta;
    if (!meta?.quiet) reportApiError(apiError);
    return apiError;
  });
}

/**
 * Await a generated SDK call the way `apiFetch` behaves: resolve to the data,
 * or throw the call's `ApiError` (already reported unless `meta.quiet`).
 */
export async function unwrap<T>(call: Promise<{ data?: T; error?: unknown }>): Promise<T> {
  const { data, error } = await call;
  if (error !== undefined) throw error;
  return data as T;
}

export { client };
