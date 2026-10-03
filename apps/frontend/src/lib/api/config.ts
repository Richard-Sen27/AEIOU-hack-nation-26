/**
 * Where the FastAPI service lives. Always 127.0.0.1 (never localhost): the
 * session cookie is set by the API on 127.0.0.1 and the OAuth callback is
 * pinned there, so a `localhost` page would be cross-site and lose it.
 */
export const API_URL = (
  process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000"
).replace(/\/+$/, "");

export const PRIVACY_EMAIL = process.env.NEXT_PUBLIC_PRIVACY_EMAIL || "";

/** Absolute API URL for a path like `/search`. */
export function apiUrl(path: string): string {
  return `${API_URL}${path.startsWith("/") ? path : `/${path}`}`;
}
