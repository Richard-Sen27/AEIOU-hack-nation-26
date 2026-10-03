// Public entry point of the API layer.
export { client } from "./client";
export * from "./generated/sdk.gen";
// Generated schema types, namespaced so they never clash with ./types.
export type * as Schemas from "./generated/types.gen";

export { API_URL, PRIVACY_EMAIL, apiUrl } from "./config";
export { apiFetch, buildUrl, type ApiFetchOptions } from "./fetch";
export { streamSSE, parseSSE, type SSEEvent, type SSEFrame } from "./sse";
export {
  ApiError,
  reportApiError,
  setApiErrorHandler,
  type ApiErrorCode,
} from "./errors";
export * from "./types";
