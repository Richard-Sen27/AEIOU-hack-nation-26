from typing import Annotated, Any

from fastapi import Body, FastAPI

from backend.devtools.mock_openai import api, issuer
from backend.devtools.mock_openai.state import MockState


def create_app(state: MockState | None = None) -> FastAPI:
    """ASGI app serving both mock hosts: the issuer at `/` and the API at `/v1`."""
    state = state or MockState()
    app = FastAPI(title="Mock OpenAI (development only)", docs_url=None, redoc_url=None)
    app.state.mock = state

    @app.middleware("http")
    async def no_keep_alive(request, call_next):
        # One request per connection: no pooled connection can be reused in a half-closed state.
        response = await call_next(request)
        response.headers["connection"] = "close"
        return response
    app.include_router(issuer.build_router(state))
    app.include_router(api.build_router(state))

    @app.post("/_mock/reset")
    async def reset():
        state.reset()
        return {"ok": True}

    @app.post("/_mock/config")
    async def configure(switches: Annotated[dict[str, Any], Body()]):
        state.configure(**switches)
        return {"ok": True}

    @app.post("/_mock/queue")
    async def queue(script: Annotated[dict[str, Any] | list[dict[str, Any]], Body()]):
        items = script if isinstance(script, list) else [script]
        state.enqueue(*items)
        return {"queued": len(state.queue)}

    @app.get("/_mock/requests")
    async def requests(kind: str | None = None):
        return state.recorded(kind)

    @app.get("/_mock/users")
    async def users():
        return [u.__dict__ for u in state.users.values()]

    return app
