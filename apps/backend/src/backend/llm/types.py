from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Generic, Literal, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

LLMErrorCode = Literal[
    "usage_limit_exceeded",
    "usage_unavailable",
    "reauth_required",
    "timeout",
    "bad_output",
    "upstream",
]


class LLMError(Exception):
    """A failed LLM call. `code` is safe to show/log; nothing here contains prompts or tokens.

    `upstream_code` is OpenAI's error code (e.g. `subscription_sharing_usage_limit_exceeded`)
    and `status` the HTTP status, when known.
    """

    def __init__(
        self,
        code: LLMErrorCode,
        message: str = "",
        *,
        status: int | None = None,
        upstream_code: str | None = None,
    ):
        self.code = code
        self.status = status
        self.upstream_code = upstream_code
        super().__init__(message or code)


@runtime_checkable
class TokenProvider(Protocol):
    async def get_token(self) -> str: ...


class StaticToken:
    """A fixed bearer token (tests, scripts)."""

    def __init__(self, token: str):
        self._token = token

    async def get_token(self) -> str:
        return self._token

    def __repr__(self) -> str:
        return "StaticToken(***)"


@dataclass
class Tool:
    name: str
    description: str
    params_model: type[BaseModel]
    handler: Callable[[BaseModel], Awaitable[BaseModel | dict]]


@dataclass
class ModelInfo:
    slug: str
    display_name: str | None = None
    visibility: str | None = None


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.reasoning_tokens += other.reasoning_tokens
        self.cached_tokens += other.cached_tokens


@dataclass
class ToolEvent:
    """Progress event from `run_tools`. `text_delta` carries `delta`; tool events carry the rest."""

    type: Literal["tool_start", "tool_end", "text_delta"]
    name: str | None = None
    call_id: str | None = None
    arguments: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: float | None = None
    delta: str | None = None


@dataclass
class ToolCallRecord:
    name: str
    call_id: str
    arguments: dict[str, Any]
    output: dict[str, Any] | None
    error: str | None
    duration_ms: float


@dataclass
class ToolRunResult(Generic[T]):  # noqa: UP046
    text: str
    output: T | None = None
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    model: str | None = None
    tool_mode: str | None = None
    rounds: int = 0


OnEvent = Callable[[ToolEvent], Any]
