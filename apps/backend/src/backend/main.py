import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.api.errors import error_body, install_error_handlers
from backend.api.ratelimit import limiter, request_limits
from backend.api.request_log import RequestLog
from backend.api.routes import (
    account,
    atlas,
    auth,
    calls,
    chat,
    contributions,
    documents,
    explain,
    follows,
    gap,
    graph,
    health,
    messaging,
    path,
    people,
    proposal,
    session,
    signups,
    stats,
)
from backend.api.services.documents import MAX_UPLOAD_BYTES
from backend.config import DEV_SESSION_SECRET, Settings, get_settings
from backend.db.session import configure_engine, dispose_engine, user_transaction
from backend.observability.logs import configure_logging, is_set, mask_url
from backend.schemas.enums import ErrorCode

log = logging.getLogger("backend")
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

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
    people,
    messaging,
    signups,  # before calls: /calls/suggested is not a call id
    calls,
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

    started = time.perf_counter()
    try:
        async with user_transaction(None) as db:
            store = await graph_service.load_graph(db)
        log.info(
            "graph loaded: %d nodes, %d edges data_version=%s ms=%d",
            len(store.nodes),
            len(store.edges),
            store.data_version or "none",
            round((time.perf_counter() - started) * 1000),
        )
    except NotImplementedError:
        log.warning("graph service not implemented yet; starting with an empty graph")
    except Exception as exc:  # noqa: BLE001 - the API must start even without a graph
        log.warning("graph not loaded (%s); starting with an empty graph", type(exc).__name__)


def settings_summary(settings: Settings) -> str:
    """Start-up line: which features are configured, never a secret's value."""
    from backend.google_auth import google_login_available
    from backend.openai_auth.settings import get_openai_settings

    openai = get_openai_settings()
    fields = {
        "local": settings.is_local,
        "frontend": settings.frontend_url,
        "db": mask_url(settings.database_url),
        "cookie_secure": settings.cookie_secure,
        "session_secret": "default" if settings.session_secret == DEV_SESSION_SECRET else "set",
        "token_key": is_set(openai.token_encryption_key),
        "message_key": is_set(settings.message_encryption_key),
        "openai_api_key": is_set(openai.openai_api_key),
        "api_models": f"{openai.openai_api_model_main},{openai.openai_api_model_small}",
        "google_login": google_login_available(),
        "orcid": "mock" if settings.orcid_mock else is_set(settings.orcid_client_id),
        "demo_auto_verify": settings.demo_auto_verify,
        "calls_review": settings.calls_review_required,
        "demo": settings.demo_mode,
        "log_level": settings.log_level.lower(),
        "trusted_proxy_hops": settings.trusted_proxy_hops,
        "rate_limit_general": settings.rate_limit_general,
        "model_daily_budget": settings.model_daily_budget,
        "model_daily_ceiling": settings.model_daily_ceiling,
        "model_max_concurrent": settings.model_max_concurrent,
        "model_max_concurrent_per_account": settings.model_max_concurrent_per_account,
    }
    return " ".join(
        f"{k}={str(v).lower() if isinstance(v, bool) else v}" for k, v in fields.items()
    )


async def log_migrations() -> None:
    """The database's Alembic revision against the newest one shipped with this build."""
    head = current = "unknown"
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config()
        cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
        head = ScriptDirectory.from_config(cfg).get_current_head() or "none"
    except Exception as exc:  # noqa: BLE001 - informational only
        log.debug("migration head unknown (%s)", type(exc).__name__)
    try:
        async with user_transaction(None) as db:
            current = await db.scalar(text("SELECT version_num FROM alembic_version")) or "none"
    except Exception as exc:  # noqa: BLE001 - the API role may not read alembic_version
        log.debug("migration state unknown (%s)", type(exc).__name__)
    if "unknown" in (head, current):
        state = "unknown"
    else:
        state = "current" if head == current else "behind"
    log.info("migrations state=%s db=%s head=%s", state, current, head)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from backend.api.ratelimit import gate
    from backend.api.services.chat import runs

    started = time.perf_counter()
    settings = app.state.settings
    log.info("starting %s", settings_summary(settings))
    if settings.demo_auto_verify:
        log.warning(
            "demo_auto_verify on: verification requests are approved without review and labelled"
            " simulated; switch it off before real use"
        )
    configure_engine(settings.database_url)
    await log_migrations()
    await load_graph_on_startup()
    log.info("ready ms=%d", round((time.perf_counter() - started) * 1000))
    yield
    log.info(
        "shutting down chat_runs_running=%d model_runs_running=%d",
        runs.running_count(),
        gate.running(),
    )
    await dispose_engine()
    log.info(
        "stopped %s model_requests=%d model_budget_spent_today=%d",
        runs.stats_text(),
        gate.started,
        gate.spent_today(),
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="Amber — Rare Disease Atlas API",
        version="0.1.0",
        lifespan=lifespan,
        separate_input_output_schemas=False,
        # The general and expensive-read rate limits, on every route (backend.api.ratelimit).
        dependencies=[Depends(request_limits)],
    )
    app.state.settings = settings
    app.state.limiter = limiter
    # Last added runs first: CORS wraps everything, so 413s and gzip responses carry its headers;
    # the request log wraps CORS, so every response (also 413 and 500) gets an id and a log line.
    app.add_middleware(UploadSizeLimit)
    app.add_middleware(GZipMiddleware, minimum_size=GZIP_MINIMUM_BYTES, compresslevel=GZIP_LEVEL)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url.rstrip("/")],
        allow_origin_regex=settings.cors_extra_origin_regex or None,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Accept", "Last-Event-ID", "Sec-GPC"],
        expose_headers=[
            "X-Neighborhood-Total",
            "X-Neighborhood-Truncated",
            "X-Request-ID",
            "Retry-After",
        ],
    )
    app.add_middleware(RequestLog, settings=settings)
    install_error_handlers(app)
    for module in ROUTERS:
        app.include_router(module.router)
    # Simulated ORCID sign-in: every route answers 404 unless ORCID_MOCK is on, which settings
    # refuse outside loopback (backend.devtools.mock_orcid).
    from backend.devtools.mock_orcid.router import router as mock_orcid_router

    app.include_router(mock_orcid_router)
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
