import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.errors import install_error_handlers
from backend.api.ratelimit import limiter
from backend.api.routes import (
    account,
    auth,
    chat,
    contributions,
    documents,
    explain,
    gap,
    graph,
    health,
    path,
    proposal,
    session,
)
from backend.config import Settings, get_settings
from backend.db.session import configure_engine, dispose_engine, user_transaction

log = logging.getLogger("backend")

ROUTERS = (
    health,
    session,
    auth,
    account,
    graph,
    path,
    explain,
    chat,
    gap,
    documents,
    contributions,
    proposal,
)


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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url.rstrip("/")],
        allow_origin_regex=settings.cors_extra_origin_regex or None,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Accept", "Last-Event-ID", "Sec-GPC"],
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
