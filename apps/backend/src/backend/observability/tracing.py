"""Tracing facade. A no-op unless LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are
all set (self-hosted Langfuse only). Callers pass REDACTED text only; never prompts with personal
data, never tokens. Importing this module never touches the network."""

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)

ObservationType = Literal["span", "generation", "tool", "agent", "chain", "retriever", "guardrail"]


class _TracingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env", extra="ignore"
    )

    langfuse_host: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.langfuse_host and self.langfuse_public_key and self.langfuse_secret_key)


class Span:
    """Handle for one observation. All methods are safe no-ops when tracing is off."""

    def __init__(self, obs: Any = None):
        self._obs = obs

    def update(
        self,
        *,
        output: Any = None,
        metadata: dict[str, Any] | None = None,
        usage: Any = None,
        model: str | None = None,
        level: Literal["DEBUG", "DEFAULT", "WARNING", "ERROR"] | None = None,
        status_message: str | None = None,
    ) -> None:
        if self._obs is None:
            return
        fields: dict[str, Any] = {}
        if output is not None:
            fields["output"] = output
        if metadata:
            fields["metadata"] = metadata
        if model:
            fields["model"] = model
        if level:
            fields["level"] = level
        if status_message:
            fields["status_message"] = status_message
        if usage is not None:
            fields["usage_details"] = _usage_details(usage)
        try:
            self._obs.update(**fields)
        except Exception:
            log.debug("trace update failed", exc_info=False)

    def event(self, name: str, metadata: dict[str, Any] | None = None) -> None:
        if self._obs is None:
            return
        try:
            self._obs.create_event(name=name, metadata=metadata or {})
        except Exception:
            log.debug("trace event failed", exc_info=False)


def _usage_details(usage: Any) -> dict[str, int]:
    if isinstance(usage, dict):
        return {k: int(v) for k, v in usage.items() if isinstance(v, int | float)}
    return {
        "input": int(getattr(usage, "input_tokens", 0) or 0),
        "output": int(getattr(usage, "output_tokens", 0) or 0),
        "reasoning": int(getattr(usage, "reasoning_tokens", 0) or 0),
    }


class Tracer:
    def __init__(self, client: Any = None):
        self._client = client

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @contextmanager
    def trace(
        self,
        name: str,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        input: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[Span]:
        """Root span for one turn/job. `user_id` should be the internal pseudonymous user UUID."""
        if self._client is None:
            yield Span()
            return
        from langfuse import propagate_attributes

        attrs = {k: v for k, v in {"user_id": user_id, "session_id": session_id}.items() if v}
        with propagate_attributes(**attrs):
            with self.span(name, input=input, metadata=metadata) as span:
                yield span

    @contextmanager
    def span(
        self,
        name: str,
        *,
        as_type: ObservationType = "span",
        input: Any = None,
        metadata: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> Iterator[Span]:
        if self._client is None:
            yield Span()
            return
        kwargs: dict[str, Any] = {"name": name, "as_type": as_type}
        if input is not None:
            kwargs["input"] = input
        if metadata:
            kwargs["metadata"] = metadata
        if model:
            kwargs["model"] = model
        try:
            cm = self._client.start_as_current_observation(**kwargs)
            obs = cm.__enter__()
        except Exception:
            log.debug("trace span failed", exc_info=False)
            yield Span()
            return
        span = Span(obs)
        try:
            yield span
        except BaseException as exc:
            span.update(level="ERROR", status_message=type(exc).__name__)
            cm.__exit__(None, None, None)
            raise
        cm.__exit__(None, None, None)

    def generation(self, name: str, *, model: str | None = None, metadata=None):
        return self.span(name, as_type="generation", model=model, metadata=metadata)

    def tool(self, name: str, *, metadata: dict[str, Any] | None = None):
        return self.span(name, as_type="tool", metadata=metadata)

    def flush(self) -> None:
        if self._client is not None:
            try:
                self._client.flush()
            except Exception:
                log.debug("trace flush failed", exc_info=False)


NOOP_TRACER = Tracer()
_lock = threading.Lock()


@lru_cache
def get_tracer() -> Tracer:
    settings = _TracingSettings()
    if not settings.enabled:
        return NOOP_TRACER
    with _lock:
        try:
            from langfuse import Langfuse, is_langfuse_span

            client = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
                should_export_span=is_langfuse_span,
            )
        except Exception:
            log.warning("Langfuse init failed; tracing disabled")
            return NOOP_TRACER
    return Tracer(client)
