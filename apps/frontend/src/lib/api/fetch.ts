import { apiUrl } from "./config";
import {
  ApiError,
  errorFromResponse,
  networkError,
  reportApiError,
  reportsWhenQuiet,
} from "./errors";

export type ApiFetchOptions = Omit<RequestInit, "body"> & {
  /** JSON body; serialised for you. Use `rawBody` for FormData uploads. */
  json?: unknown;
  rawBody?: BodyInit;
  /** Query params. Only public ids / short entity terms, never health data. */
  query?: Record<string, string | number | boolean | undefined | null>;
  /** Do not route errors to the global dialogs / toast. */
  quiet?: boolean;
};

export function buildUrl(path: string, query?: ApiFetchOptions["query"]) {
  const url = new URL(apiUrl(path));
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
    }
  }
  return url.toString();
}

/**
 * Hand-written fetch for the API (cookie session, error envelope).
 * Prefer the generated SDK in `@/lib/api/generated` once it exists; use this
 * for endpoints it does not cover or before generation.
 *
 * Throws `ApiError`. Unless `quiet`, the error is also reported to the global
 * handler (sign-in dialog, consent dialog or toast).
 */
export async function apiFetch<T>(
  path: string,
  { json, rawBody, query, quiet, headers, ...init }: ApiFetchOptions = {},
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(buildUrl(path, query), {
      credentials: "include",
      ...init,
      headers: {
        Accept: "application/json",
        ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
        ...headers,
      },
      body: json !== undefined ? JSON.stringify(json) : rawBody,
    });
  } catch (cause) {
    const err = networkError(cause);
    if (!quiet) reportApiError(err);
    throw err;
  }
  if (!res.ok) {
    const err = await errorFromResponse(res);
    if (!quiet || reportsWhenQuiet(err, init.method)) reportApiError(err);
    throw err;
  }
  if (res.status === 204) return undefined as T;
  const type = res.headers.get("content-type") ?? "";
  if (type.includes("application/json")) return (await res.json()) as T;
  return (await res.text()) as T;
}

export { ApiError };
