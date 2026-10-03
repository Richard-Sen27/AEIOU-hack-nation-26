import { ApiError, reportApiError } from "@/lib/api/errors";

/** Errors the global UI always handles (sign-in dialog, welcome redirect, consent dialog), even for quiet calls. */
const GLOBAL_CODES = new Set(["sign_in_required", "reauth_required", "age_confirmation_required", "consent_required"]);

/** Route global errors from a quiet call; returns the ApiError (or null) for local handling. */
export function routeGlobalError(e: unknown): ApiError | null {
  const err = e instanceof ApiError ? e : null;
  if (err && GLOBAL_CODES.has(err.code)) reportApiError(err);
  return err;
}
