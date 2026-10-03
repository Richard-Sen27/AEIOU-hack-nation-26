/**
 * The one place that understands the API's error envelope
 * `{"error": {"code", "message"}}` and decides what the UI does with it.
 *
 * - `sign_in_required` (401) → global sign-in dialog
 * - `consent_required` (403) → global consent dialog
 * - `not_implemented` (501), network errors, 5xx → quiet toast
 *
 * The UI side (GateProvider) registers itself with `setApiErrorHandler`.
 * Messages shown to users never echo request bodies (health data).
 */

export type ApiErrorCode =
  | "sign_in_required"
  | "reauth_required"
  | "consent_required"
  | "age_confirmation_required"
  | "not_implemented"
  | "not_found"
  | "rate_limited"
  | "validation_error"
  | "network_error"
  | "aborted"
  | (string & {});

export class ApiError extends Error {
  readonly code: ApiErrorCode;
  readonly status: number;
  /** Extra fields from the envelope, e.g. `consent_type` for consent_required. */
  readonly details: Record<string, unknown>;

  constructor(
    code: ApiErrorCode,
    message: string,
    status: number,
    details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.details = details;
  }

  get isAbort() {
    return this.code === "aborted";
  }
}

const FALLBACK_CODE_BY_STATUS: Record<number, ApiErrorCode> = {
  401: "sign_in_required",
  403: "consent_required",
  404: "not_found",
  422: "validation_error",
  429: "rate_limited",
  501: "not_implemented",
};

/** Parse an error body (already JSON-decoded or raw) into an ApiError. */
export function toApiError(status: number, body: unknown): ApiError {
  const envelope =
    body && typeof body === "object" && "error" in body
      ? (body as { error: unknown }).error
      : undefined;
  if (envelope && typeof envelope === "object") {
    const { code, message, ...rest } = envelope as Record<string, unknown>;
    return new ApiError(
      typeof code === "string"
        ? code
        : (FALLBACK_CODE_BY_STATUS[status] ?? "http_error"),
      typeof message === "string" ? message : `Request failed (${status})`,
      status,
      rest,
    );
  }
  return new ApiError(
    FALLBACK_CODE_BY_STATUS[status] ?? "http_error",
    `Request failed (${status})`,
    status,
  );
}

export async function errorFromResponse(res: Response): Promise<ApiError> {
  let body: unknown = undefined;
  try {
    body = await res.clone().json();
  } catch {
    /* non-JSON body */
  }
  return toApiError(res.status, body);
}

export function networkError(cause: unknown): ApiError {
  if (cause instanceof DOMException && cause.name === "AbortError") {
    return new ApiError("aborted", "Request cancelled", 0);
  }
  if (cause instanceof ApiError) return cause;
  return new ApiError(
    "network_error",
    "Amber could not reach its server. Some features are unavailable right now.",
    0,
  );
}

export type ApiErrorHandler = (error: ApiError) => void;

let handler: ApiErrorHandler | null = null;

/** Registered once by GateProvider. Returns an unregister function. */
export function setApiErrorHandler(next: ApiErrorHandler): () => void {
  handler = next;
  return () => {
    if (handler === next) handler = null;
  };
}

/**
 * Route an error to the global UI (dialogs / toast). Aborts are ignored.
 * Call this for errors you do not handle locally; `apiFetch` and the
 * generated client do it automatically unless `{ quiet: true }`.
 */
export function reportApiError(error: ApiError): void {
  if (error.isAbort) return;
  if (error.code === "age_confirmation_required") {
    redirectToWelcome();
    return;
  }
  handler?.(error);
}

/**
 * `age_confirmation_required` (403): the account has not confirmed 16+ yet.
 * Send the user to /welcome and back to the current path afterwards (path
 * only: query strings and hashes could carry user content).
 */
function redirectToWelcome(): void {
  if (typeof window === "undefined") return;
  const path = window.location.pathname;
  if (path === "/welcome") return;
  const next = path && path !== "/" && !path.startsWith("//") ? `?next=${encodeURIComponent(path)}` : "";
  // Outside React (no router here); a full navigation also drops stale state.
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.assign(`/welcome${next}`);
}
