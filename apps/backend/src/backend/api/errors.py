"""One error envelope for the whole API: {"error": {"code": ..., "message": ...}}.

Messages are fixed strings chosen by the server; they never echo user content.
"""

import contextlib
import logging
import math
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.observability.logs import current_request_id, safe_frames
from backend.schemas.common import ErrorResponse
from backend.schemas.enums import ErrorCode

log = logging.getLogger(__name__)

DEFAULT_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.bad_request: "The request could not be processed.",
    ErrorCode.sign_in_required: "Sign in to use this feature.",
    ErrorCode.consent_required: "This feature needs your consent first.",
    ErrorCode.age_group_required: "Tell us your age group before you contact anyone.",
    ErrorCode.guardian_agreement_required: (
        "Confirm that a parent or guardian knows about this and agrees."
    ),
    ErrorCode.forbidden: "You do not have access to this resource.",
    ErrorCode.not_found: "Not found.",
    ErrorCode.conflict: "The request conflicts with the current state.",
    ErrorCode.payload_too_large: "The upload is too large.",
    ErrorCode.unsupported_media_type: "This file type is not supported.",
    ErrorCode.validation_error: "The request is invalid.",
    ErrorCode.rate_limited: "Too many requests. Please try again later.",
    ErrorCode.not_implemented: "This feature is not available yet.",
    ErrorCode.upstream_error: "An upstream service failed. Please try again.",
    ErrorCode.reauth_required: "Please sign in with ChatGPT again.",
    ErrorCode.assistant_unavailable: "Dr. Wu is not available for this sign-in.",
    ErrorCode.internal_error: "Something went wrong.",
}

# The frontend's consent gate opens the contribute dialog when the message names contributing.
CONTRIBUTE_CONSENT_MESSAGE = "Contributing needs your consent first."

STATUS_CODES: dict[int, ErrorCode] = {
    400: ErrorCode.bad_request,
    401: ErrorCode.sign_in_required,
    403: ErrorCode.forbidden,
    404: ErrorCode.not_found,
    405: ErrorCode.bad_request,
    409: ErrorCode.conflict,
    413: ErrorCode.payload_too_large,
    415: ErrorCode.unsupported_media_type,
    422: ErrorCode.validation_error,
    429: ErrorCode.rate_limited,
    501: ErrorCode.not_implemented,
    502: ErrorCode.upstream_error,
}


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        message: str | None = None,
        *,
        headers: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ):
        self.status_code = status_code
        self.code = code
        self.message = message or DEFAULT_MESSAGES[code]
        self.headers = headers
        self.extra = extra  # fixed, server-chosen fields (e.g. reason, retry_after)
        super().__init__(code.value)


def not_found(message: str | None = None) -> ApiError:
    return ApiError(404, ErrorCode.not_found, message)


def error_body(
    code: ErrorCode, message: str | None = None, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code.value, "message": message or DEFAULT_MESSAGES[code]}
    if extra:
        error.update(extra)
    rid = current_request_id()
    if rid:
        error["request_id"] = rid
    return {"error": error}


def error_response(
    status_code: int,
    code: ErrorCode,
    message: str | None = None,
    headers=None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(error_body(code, message, extra), status_code=status_code, headers=headers)


RESPONSE_DESCRIPTIONS: dict[int, str] = {
    400: "bad_request",
    401: "sign_in_required: guest, or the session expired.",
    403: "consent_required (no active consent of the needed type) or forbidden.",
    404: "not_found",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error: lists invalid field names only.",
    429: "rate_limited",
    501: "not_implemented",
    502: "upstream_error",
    503: "assistant_unavailable: no model access for this sign-in (the rest works).",
}


def responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI `responses` entries for the given error status codes."""
    return {
        code: {"model": ErrorResponse, "description": RESPONSE_DESCRIPTIONS[code]}
        for code in status_codes
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message, exc.headers, exc.extra)

    @app.exception_handler(NotImplementedError)
    async def _not_implemented(_: Request, exc: NotImplementedError) -> JSONResponse:
        return error_response(501, ErrorCode.not_implemented)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Field locations only; pydantic's error inputs would echo user content.
        fields = sorted(
            {".".join(str(p) for p in err.get("loc", ()) if p != "body") for err in exc.errors()}
        )
        message = "Invalid request fields: " + ", ".join(f for f in fields if f) if fields else None
        return error_response(422, ErrorCode.validation_error, message)

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limited(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        # A per-route slowapi limit; the general and model limits raise ApiError instead.
        from backend.api import ratelimit

        retry = 60
        view = getattr(request.state, "view_rate_limit", None)
        if view is not None:
            with contextlib.suppress(Exception):
                stats = ratelimit.limiter.limiter.get_window_stats(view[0], *view[1])
                retry = max(1, math.ceil(stats.reset_time - time.time()))
        client = ratelimit.identify(request)
        ratelimit.log_rejection(client.kind, ratelimit.route_template(request), "route")
        return error_response(
            429,
            ErrorCode.rate_limited,
            headers={"Retry-After": str(retry)},
            extra={"reason": "rate", "retry_after": retry},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = STATUS_CODES.get(exc.status_code, ErrorCode.internal_error)
        return error_response(exc.status_code, code, headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Normally the request-log middleware catches these first (backend.api.request_log).
        log.error("unhandled error exc=%s where=%s", type(exc).__name__, safe_frames(exc))
        return error_response(500, ErrorCode.internal_error)
