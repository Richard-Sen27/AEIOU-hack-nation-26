"""SSE helpers. Wire format: ``event: <type>`` + ``data: <json>`` (JSON repeats ``type``)."""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, RootModel
from sse_starlette import EventSourceResponse

from backend.api.errors import ApiError
from backend.schemas.enums import ErrorCode

log = logging.getLogger(__name__)


class EventStream(EventSourceResponse):
    """EventSourceResponse with a class-level media type, so OpenAPI documents it."""

    media_type = "text/event-stream"


def sse_doc(event_model: type[BaseModel], description: str) -> dict[int | str, dict[str, Any]]:
    """OpenAPI entry declaring a text/event-stream 200 whose events follow event_model."""
    return {200: {"model": event_model, "description": description}}


def _encode(event: BaseModel) -> dict[str, str]:
    if isinstance(event, RootModel):
        event = event.root
    return {"event": event.type, "data": event.model_dump_json()}  # type: ignore[attr-defined]


def sse_response(events: AsyncIterator[BaseModel], **kwargs: Any) -> EventStream:
    """Stream pydantic events; a failure mid-stream becomes a final `error` event."""

    async def _gen() -> AsyncIterator[dict[str, str]]:
        try:
            async for event in events:
                yield _encode(event)
        except ApiError as exc:
            yield _error(exc.code, exc.message)
        except NotImplementedError:
            yield _error(ErrorCode.not_implemented, "This feature is not available yet.")
        except Exception as exc:  # noqa: BLE001
            log.error("stream failed: %s", type(exc).__name__)
            yield _error(ErrorCode.internal_error, "Something went wrong.")

    return EventStream(_gen(), **kwargs)


def _error(code: ErrorCode, message: str) -> dict[str, str]:
    return {
        "event": "error",
        "data": json.dumps({"type": "error", "code": code, "message": message}),
    }
