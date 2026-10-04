"""Outermost ASGI middleware: a request id, one log line per request, and unhandled errors.

The line names the route template (`/node/{node_id}`), never the raw path or query string:

    request rid=3f9c0a1b2c4d5e6f method=GET route=/node/{node_id} status=200 ms=12 bytes=5123
        client=user uh=8c1d2e3f4a

`uh` is the account's daily pseudonym (backend.observability.logs.user_tag); guests have none.
Health checks are logged at debug level only. Every response carries `X-Request-ID`, and error
envelopes carry the same id (`request_id`), so a user's report can be matched to the log.
"""

import json
import logging
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.api.errors import error_body
from backend.api.ratelimit import identify
from backend.config import Settings
from backend.observability.logs import REQUEST_ID, safe_frames, user_tag
from backend.schemas.enums import ErrorCode

log = logging.getLogger("backend.request")

REQUEST_ID_HEADER = "X-Request-ID"
QUIET_ROUTES = {"/health"}
METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}


def _template(scope: Scope) -> str:
    route = scope.get("route")
    return getattr(route, "path", None) or "unmatched"


class RequestLog:
    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid = uuid.uuid4().hex[:16]
        token = REQUEST_ID.set(rid)
        started = time.perf_counter()
        client = identify(Request(scope), self.settings)
        status = 0
        size = 0
        responded = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status, size, responded
            if message["type"] == "http.response.start":
                responded = True
                status = message["status"]
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, rid)
            elif message["type"] == "http.response.body":
                size += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:  # noqa: BLE001 - logged without its message, answered 500
            status = 500
            log.error(
                "unhandled error rid=%s route=%s exc=%s where=%s",
                rid,
                _template(scope),
                type(exc).__name__,
                safe_frames(exc),
            )
            if not responded:
                await _send_internal_error(send_wrapper)
        finally:
            self._log(scope, rid, client, status, size, started)
            REQUEST_ID.reset(token)

    def _log(self, scope: Scope, rid: str, client, status: int, size: int, started: float) -> None:
        route = _template(scope)
        level = logging.DEBUG if route in QUIET_ROUTES else logging.INFO
        if status >= 500:
            level = logging.WARNING
        if not log.isEnabledFor(level):
            return
        method = scope.get("method", "")
        fields = [
            f"rid={rid}",
            f"method={method if method in METHODS else 'OTHER'}",
            f"route={route}",
            f"status={status}",
            f"ms={round((time.perf_counter() - started) * 1000)}",
            f"bytes={size}",
            f"client={client.kind}",
        ]
        if client.user_id is not None:
            fields.append(f"uh={user_tag(client.user_id, self.settings.session_secret)}")
        if log.isEnabledFor(logging.DEBUG):
            fields.append(f"via={client.via}")
            if client.network:
                # Shows whether two guests on different networks get different keys (the
                # TRUSTED_PROXY_HOPS check); a per-process keyed hash, not the address.
                fields.append(f"net={client.network[4:10]}")
        log.log(level, "request %s", " ".join(fields))


async def _send_internal_error(send: Send) -> None:
    body = json.dumps(error_body(ErrorCode.internal_error)).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 500,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
