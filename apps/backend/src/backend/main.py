import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.api.errors import error_body, install_error_handlers
from backend.api.ratelimit import limiter
from backend.api.routes import (
    account,
    atlas,
    auth,
    chat,
    contributions,
    documents,
    explain,
    follows,
    gap,
    graph,
    health,
    path,
    proposal,
    session,
    stats,
)
from backend.api.services.documents import MAX_UPLOAD_BYTES
from backend.config import Settings, get_settings
from backend.db.session import configure_engine, dispose_engine, user_transaction
from backend.schemas.enums import ErrorCode

log = logging.getLogger("backend")

ROUTERS = (
    health,
    session,
    auth,
    account,
    graph,
    atlas,
    stats,
    path,
    explain,
    chat,
    gap,
    documents,
    contributions,
    proposal,
    follows,
)


# Large JSON (atlas.json is several MB) is gzip-compressed; text/event-stream is excluded by
# Starlette's default, so SSE responses stay uncompressed and flush event by event.
GZIP_MINIMUM_BYTES = 1024
GZIP_LEVEL = 6
# Multipart framing around a file of MAX_UPLOAD_BYTES; the service re-checks the file itself.
UPLOAD_ROUTES = {("POST", "/documents")}
UPLOAD_OVERHEAD_BYTES = 64 * 1024


class UploadSizeLimit:
    """Reject uploads whose Content-Length exceeds the limit before the body is read.

    Chunked uploads (no Content-Length) fall through to the service's own size check."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_UPLOAD_BYTES + UPLOAD_OVERHEAD_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and (scope["method"], scope["path"]) in UPLOAD_ROUTES:
            length = dict(scope["headers"]).get(b"content-length")
            if length is not None and length.isdigit() and int(length) > self.max_bytes:
                await _send_too_large(send)
                return
        await self.app(scope, receive, send)


async def _send_too_large(send: Send) -> None:
    body = json.dumps(
        error_body(ErrorCode.payload_too_large, "The upload is larger than 20 MB.")
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def load_graph_on_startup() -> None:
    from backend.api.services import graph as graph_service

    try:
        async with user_transaction(None) as db:
            store = await graph_service.load_graph(db)
        log.info("graph loaded: %d nodes, %d edges", len(store.nodes), len(store.edges))
    except NotImplementedError:
        log.warning("graph service not implemented yet; starting with an empty graph")
    except Exception as exc:  # noqa: BLE001 - the API must start even without a graph
        log.warning("graph not loaded (%s); starting with an empty graph", type(exc).__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_engine(app.state.settings.database_url)
    await load_graph_on_startup()
    yield
    await dispose_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="Amber — Rare Disease Atlas API",
        version="0.1.0",
        lifespan=lifespan,
        separate_input_output_schemas=False,
    )
    app.state.settings = settings
    app.state.limiter = limiter
    # Last added runs first: CORS wraps everything, so 413s and gzip responses carry its headers.
    app.add_middleware(UploadSizeLimit)
    app.add_middleware(GZipMiddleware, minimum_size=GZIP_MINIMUM_BYTES, compresslevel=GZIP_LEVEL)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url.rstrip("/")],
        allow_origin_regex=settings.cors_extra_origin_regex or None,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Accept", "Last-Event-ID", "Sec-GPC"],
        expose_headers=["X-Neighborhood-Total", "X-Neighborhood-Truncated"],
    )
    install_error_handlers(app)
    for module in ROUTERS:
        app.include_router(module.router)
    _clean_event_stream_schemas(app)
    return app


def _clean_event_stream_schemas(app: FastAPI) -> None:
    """FastAPI adds `type: string` next to the $ref of text/event-stream bodies; drop it."""
    original = app.openapi

    def openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema
        schema = original()
        for ops in schema.get("paths", {}).values():
            for op in ops.values():
                for resp in op.get("responses", {}).values():
                    body = resp.get("content", {}).get("text/event-stream", {}).get("schema")
                    if body and "$ref" in body:
                        body.pop("type", None)
        return schema

    app.openapi = openapi  # type: ignore[method-assign]


app = create_app()
