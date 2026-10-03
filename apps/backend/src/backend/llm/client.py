"""The single gateway for every LLM call (backend and pipeline).

Responses API over the official SDK, always `store=False` + `stream=True` (required for ChatGPT
plan usage). No prompts, outputs or tokens are ever logged or traced here.
"""

import asyncio
import hashlib
import inspect
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
import openai
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from backend.llm.schema import (
    extract_json,
    json_only_instructions,
    schema_name,
    strict_json_schema,
    tool_protocol_instructions,
    validation_feedback,
)
from backend.llm.types import (
    LLMError,
    ModelInfo,
    OnEvent,
    T,
    TokenProvider,
    Tool,
    ToolCallRecord,
    ToolEvent,
    ToolRunResult,
    Usage,
)
from backend.observability.tracing import NOOP_TRACER, Tracer

log = logging.getLogger(__name__)

ModelKind = Literal["main", "small"]
ToolMode = Literal["namespace", "function", "json"]
TOOL_NAMESPACE = "amber"
_TOOL_MODES: tuple[ToolMode, ...] = ("namespace", "function", "json")
_MODELS_TTL_S = 600.0

_USAGE_LIMIT_CODES = {"subscription_sharing_usage_limit_exceeded", "usage_limit_exceeded"}
_UNAVAILABLE_CODES = {
    "subscription_sharing_usage_unavailable",
    "subscription_sharing_unavailable",
    "subscription_sharing_user_unavailable",
    "subscription_sharing_user_not_eligible",
}
_REAUTH_CODES = {
    "subscription_sharing_invalid_user",
    "chatpass_v2_scope_not_authorized",
    "invalid_api_key",
    "token_expired",
}
_UNSUPPORTED_CODE = "subscription_sharing_unsupported_capability"


@dataclass
class _Capabilities:
    """What the upstream accepts, learned per base URL from 400 rejections."""

    json_schema: bool = True
    tool_mode: ToolMode = "namespace"
    include_reasoning: bool = True


_capabilities: dict[str, _Capabilities] = {}
_models_cache: dict[tuple[str, str], tuple[float, list[ModelInfo]]] = {}


class _BadRequest(LLMError):
    def __init__(self, *, param: str, message: str, upstream_code: str | None):
        super().__init__("upstream", "request rejected", status=400, upstream_code=upstream_code)
        self.param = param
        self.hint = f"{param} {message}".lower()

    def mentions(self, *words: str) -> bool:
        return any(w in self.hint for w in words)

    @property
    def unsupported(self) -> bool:
        return self.upstream_code == _UNSUPPORTED_CODE or self.mentions(
            "not supported", "unsupported", "not allowed", "unknown parameter", "not permitted"
        )


@dataclass
class _Result:
    text: str = ""
    items: list[dict[str, Any]] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


def _error_fields(body: Any) -> tuple[str | None, str, str]:
    err = body.get("error", body) if isinstance(body, dict) else {}
    if not isinstance(err, dict):
        return None, "", ""
    code = err.get("code") or err.get("type")
    return (str(code) if code else None), str(err.get("param") or ""), str(err.get("message") or "")


def _map_code(code: str | None, status: int | None) -> LLMError:
    if code in _USAGE_LIMIT_CODES or status == 429:
        return LLMError("usage_limit_exceeded", status=status, upstream_code=code)
    if code in _REAUTH_CODES or status == 401:
        return LLMError("reauth_required", status=status, upstream_code=code)
    if code in _UNAVAILABLE_CODES or status == 503:
        return LLMError("usage_unavailable", status=status, upstream_code=code)
    if status in (408, 504):
        return LLMError("timeout", status=status, upstream_code=code)
    return LLMError("upstream", status=status, upstream_code=code)


def _map_status_error(exc: openai.APIStatusError) -> LLMError:
    code, param, message = _error_fields(exc.body)
    if exc.status_code == 400:
        return _BadRequest(param=param, message=message, upstream_code=code)
    return _map_code(code, exc.status_code)


def _as_items(input: str | list) -> list[Any]:
    if isinstance(input, str):
        return [{"role": "user", "content": input}]
    items = []
    for item in input:
        if isinstance(item, dict) and item.get("role") == "system":
            item = {**item, "role": "developer"}
        items.append(item)
    return items


def _replayable(item: dict[str, Any]) -> dict[str, Any]:
    """Output item -> input item. With store=False nothing is persisted server-side, so item ids
    are dropped (reasoning items keep theirs; they travel with their encrypted_content)."""
    if item.get("type") == "reasoning":
        return item
    return {k: v for k, v in item.items() if k != "id"}


def _usage_from(resp: Any) -> Usage:
    u = getattr(resp, "usage", None)
    if u is None:
        return Usage()
    out_details = getattr(u, "output_tokens_details", None)
    in_details = getattr(u, "input_tokens_details", None)
    return Usage(
        input_tokens=getattr(u, "input_tokens", 0) or 0,
        output_tokens=getattr(u, "output_tokens", 0) or 0,
        reasoning_tokens=getattr(out_details, "reasoning_tokens", 0) or 0,
        cached_tokens=getattr(in_details, "cached_tokens", 0) or 0,
    )


def _dump(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    return obj.model_dump(mode="json", exclude_none=True)


def _pick_model(models: list[ModelInfo], kind: ModelKind) -> str | None:
    visible = [m for m in models if m.visibility in (None, "list")] or models
    if not visible:
        return None
    slugs = [m.slug for m in visible]

    def small(s: str) -> bool:
        return any(t in s.lower() for t in ("mini", "nano", "small"))

    general = [s for s in slugs if "codex" not in s.lower()] or slugs
    if kind == "small":
        for marker in ("mini", "nano", "small"):
            for s in general:
                if marker in s.lower():
                    return s
    return next((s for s in general if not small(s)), general[0])


async def _emit(on_event: OnEvent | None, event: ToolEvent) -> None:
    if on_event is None:
        return
    res = on_event(event)
    if inspect.isawaitable(res):
        await res


class LLMClient:
    def __init__(
        self,
        token_provider: TokenProvider,
        *,
        base_url: str | None = None,
        tracer: Tracer | None = None,
        timeout: float = 90.0,
        http_client: httpx.AsyncClient | None = None,
        model_overrides: dict[str, str] | None = None,
    ):
        from backend.openai_auth.settings import get_openai_settings

        settings = get_openai_settings()
        self.token_provider = token_provider
        self.base_url = (base_url or settings.api_base_url).rstrip("/")
        self.tracer = tracer or NOOP_TRACER
        overrides = {"main": settings.openai_model_main, "small": settings.openai_model_small}
        overrides.update(model_overrides or {})
        self._overrides = {k: v for k, v in overrides.items() if v}
        self._resolved: dict[str, str] = {}
        self._openai = AsyncOpenAI(
            api_key="unset",
            base_url=self.base_url,
            max_retries=0,
            timeout=timeout,
            http_client=http_client,
        )
        self._caps = _capabilities.setdefault(self.base_url, _Capabilities())

    def __repr__(self) -> str:
        return f"LLMClient(base_url={self.base_url!r})"

    async def bearer(self) -> str:
        return await self.token_provider.get_token()

    async def _sdk(self) -> AsyncOpenAI:
        return self._openai.with_options(api_key=await self.bearer())

    async def _force_refresh(self) -> bool:
        refresh = getattr(self.token_provider, "force_refresh", None)
        if refresh is None:
            return False
        try:
            await refresh()
        except Exception:
            return False
        return True

    # ---- models -------------------------------------------------------------------------

    async def list_models(self) -> list[ModelInfo]:
        token = await self.bearer()
        key = (self.base_url, hashlib.sha256(token.encode()).hexdigest()[:16])
        cached = _models_cache.get(key)
        if cached and time.monotonic() - cached[0] < _MODELS_TTL_S:
            return cached[1]
        try:
            resp = await self._openai.with_options(api_key=token).get(
                "/models", cast_to=httpx.Response
            )
        except openai.APIStatusError as exc:
            raise _map_status_error(exc) from None
        except openai.APITimeoutError:
            raise LLMError("timeout", "model list timed out") from None
        except openai.APIConnectionError:
            raise LLMError("upstream", "connection failed") from None
        try:
            body = resp.json()
        except ValueError:
            raise LLMError("upstream", "invalid model list") from None
        models: list[ModelInfo] = []
        for raw in body.get("models") or []:
            if isinstance(raw, dict) and raw.get("slug"):
                models.append(
                    ModelInfo(raw["slug"], raw.get("display_name"), raw.get("visibility"))
                )
        for raw in body.get("data") or []:
            if isinstance(raw, dict) and raw.get("id"):
                models.append(ModelInfo(raw["id"], raw.get("display_name"), "list"))
        _models_cache[key] = (time.monotonic(), models)
        return models

    async def resolve_model(self, kind: ModelKind) -> str:
        if kind in self._overrides:
            return self._overrides[kind]
        if kind not in self._resolved:
            slug = _pick_model(await self.list_models(), kind)
            if not slug:
                raise LLMError("usage_unavailable", "no models available for this account")
            self._resolved[kind] = slug
        return self._resolved[kind]

    # ---- low level streaming ------------------------------------------------------------

    async def _open(self, params: dict[str, Any]):
        for attempt in range(2):
            client = await self._sdk()
            try:
                return await client.responses.create(**params, store=False, stream=True)
            except openai.AuthenticationError as exc:
                if attempt == 0 and await self._force_refresh():
                    continue
                raise _map_status_error(exc) from None
            except openai.APIStatusError as exc:
                raise _map_status_error(exc) from None
            except openai.APITimeoutError:
                raise LLMError("timeout", "request timed out") from None
            except openai.APIConnectionError:
                raise LLMError("upstream", "connection failed") from None
        raise LLMError("reauth_required")

    async def _events(self, params: dict[str, Any]) -> AsyncIterator[tuple[str, Any]]:
        """Yields ("delta", str) for text deltas and finally ("done", _Result)."""
        model = params.get("model")
        started = time.monotonic()
        with self.tracer.generation("llm.responses", model=model) as gen:
            stream = await self._open(params)
            result = _Result()
            text: list[str] = []
            items: list[dict[str, Any]] = []
            completed = None
            try:
                async for event in stream:
                    etype = getattr(event, "type", "")
                    if etype == "response.output_text.delta":
                        text.append(event.delta)
                        yield "delta", event.delta
                    elif etype == "response.output_item.done":
                        items.append(_dump(event.item))
                    elif etype == "response.completed":
                        completed = event.response
                    elif etype == "response.failed":
                        err = getattr(event.response, "error", None)
                        raise _map_code(getattr(err, "code", None), None)
                    elif etype == "response.incomplete":
                        raise LLMError(
                            "upstream", "response incomplete", upstream_code="incomplete"
                        )
                    elif etype == "error":
                        code = getattr(event, "code", None)
                        raise _map_code(code, None)
            except openai.APIStatusError as exc:
                raise _map_status_error(exc) from None
            except (openai.APITimeoutError, httpx.TimeoutException):
                raise LLMError("timeout", "stream timed out") from None
            except (openai.APIConnectionError, httpx.TransportError):
                raise LLMError("upstream", "stream interrupted") from None
            finally:
                await stream.close()
            if completed is None:
                raise LLMError("upstream", "stream ended without response.completed")
            output = getattr(completed, "output", None)
            result.items = [_dump(i) for i in output] if output else items
            result.text = "".join(text) or _output_text(result.items)
            result.usage = _usage_from(completed)
            gen.update(
                usage=result.usage,
                metadata={"latency_ms": round((time.monotonic() - started) * 1000)},
            )
            yield "done", result

    async def _collect(self, params: dict[str, Any], on_delta=None) -> _Result:
        result = _Result()
        async for kind, value in self._events(params):
            if kind == "delta" and on_delta is not None:
                await on_delta(value)
            elif kind == "done":
                result = value
        return result

    # ---- text -----------------------------------------------------------------------------

    async def stream_text(
        self, *, instructions: str, input: str | list, kind: ModelKind = "main"
    ) -> AsyncIterator[str]:
        model = await self.resolve_model(kind)
        params = {"model": model, "instructions": instructions, "input": _as_items(input)}
        async for event, value in self._events(params):
            if event == "delta":
                yield value

    async def complete_text(
        self, *, instructions: str, input: str | list, kind: ModelKind = "main"
    ) -> str:
        model = await self.resolve_model(kind)
        params = {"model": model, "instructions": instructions, "input": _as_items(input)}
        return (await self._collect(params)).text

    # ---- structured -----------------------------------------------------------------------

    async def structured(
        self,
        schema: type[T],
        *,
        instructions: str,
        input: str | list,
        kind: ModelKind = "small",
        max_retries: int = 2,
    ) -> T:
        model = await self.resolve_model(kind)
        items = _as_items(input)
        json_schema, strict = strict_json_schema(schema)
        use_format = self._caps.json_schema
        attempts = 0
        while True:
            params: dict[str, Any] = {"model": model, "input": items}
            if use_format:
                params["instructions"] = instructions
                params["text"] = {
                    "format": {
                        "type": "json_schema",
                        "name": schema_name(schema),
                        "schema": json_schema,
                        "strict": strict,
                    }
                }
            else:
                params["instructions"] = instructions + json_only_instructions(json_schema)
            try:
                result = await self._collect(params)
            except _BadRequest as exc:
                if use_format and exc.mentions("text", "format", "schema", "json"):
                    if exc.unsupported:
                        self._caps.json_schema = False
                    use_format = False
                    continue
                raise
            try:
                return schema.model_validate(extract_json(result.text))
            except (ValidationError, ValueError) as exc:
                attempts += 1
                if attempts > max_retries:
                    raise LLMError("bad_output", "model output failed validation") from None
                items = [
                    *items,
                    {"role": "assistant", "content": result.text or "(empty)"},
                    {
                        "role": "user",
                        "content": "Your previous reply was invalid: "
                        f"{validation_feedback(exc)}. Reply again with only the corrected JSON.",
                    },
                ]

    # ---- tools ----------------------------------------------------------------------------

    async def run_tools(
        self,
        *,
        instructions: str,
        input: str | list,
        tools: list[Tool],
        final_schema: type[T] | None = None,
        kind: ModelKind = "main",
        max_tool_calls: int = 8,
        deadline_s: float = 30.0,
        on_event: OnEvent | None = None,
    ) -> ToolRunResult[T]:
        try:
            async with asyncio.timeout(deadline_s):
                return await self._run_tools(
                    instructions=instructions,
                    input=input,
                    tools=tools,
                    final_schema=final_schema,
                    kind=kind,
                    max_tool_calls=max_tool_calls,
                    on_event=on_event,
                )
        except TimeoutError:
            raise LLMError("timeout", "tool run exceeded its deadline") from None

    async def _run_tools(
        self,
        *,
        instructions: str,
        input: str | list,
        tools: list[Tool],
        final_schema: type[T] | None,
        kind: ModelKind,
        max_tool_calls: int,
        on_event: OnEvent | None,
    ) -> ToolRunResult[T]:
        model = await self.resolve_model(kind)
        items = _as_items(input)
        while True:
            run = _ToolRun(self, model, tools, final_schema, max_tool_calls, on_event)
            mode = self._caps.tool_mode if tools else "namespace"
            try:
                if mode == "json":
                    return await run.json_protocol(instructions, items)
                return await run.native(instructions, items, mode)
            except _BadRequest as exc:
                if not self._downgrade(exc, mode, run):
                    raise

    def _downgrade(self, exc: "_BadRequest", mode: ToolMode, run: "_ToolRun") -> bool:
        caps = self._caps
        if mode != "json" and run.used_include and exc.mentions("include", "reasoning", "encrypt"):
            caps.include_reasoning = False
            return True
        if run.used_format and exc.mentions("text.format", "json_schema", "response_format"):
            caps.json_schema = False
            return True
        if mode != "json" and exc.mentions("tool", "namespace", "function"):
            caps.tool_mode = _TOOL_MODES[_TOOL_MODES.index(mode) + 1]
            log.info("LLM upstream rejected %s tools; falling back", mode)
            return True
        return False


def _output_text(items: list[dict[str, Any]]) -> str:
    parts = []
    for item in items:
        if item.get("type") == "message":
            for c in item.get("content") or []:
                if c.get("type") == "output_text":
                    parts.append(c.get("text", ""))
    return "".join(parts)


class _ToolRun:
    def __init__(
        self,
        llm: LLMClient,
        model: str,
        tools: list[Tool],
        final_schema: type[BaseModel] | None,
        max_tool_calls: int,
        on_event: OnEvent | None,
    ):
        self.llm = llm
        self.model = model
        self.tools = {t.name: t for t in tools}
        self.final_schema = final_schema
        self.max_tool_calls = max_tool_calls
        self.on_event = on_event
        self.usage = Usage()
        self.records: list[ToolCallRecord] = []
        self.rounds = 0
        self.used_include = False
        self.used_format = False
        self.final_json, self.final_strict = (
            strict_json_schema(final_schema) if final_schema else (None, False)
        )

    def _fn_def(self, tool: Tool) -> dict[str, Any]:
        params, strict = strict_json_schema(tool.params_model)
        return {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": params,
            "strict": strict,
        }

    def _tools_param(self, mode: ToolMode) -> list[dict[str, Any]]:
        fns = [self._fn_def(t) for t in self.tools.values()]
        if mode == "namespace":
            return [
                {
                    "type": "namespace",
                    "name": TOOL_NAMESPACE,
                    "description": "Amber rare-disease atlas tools",
                    "tools": fns,
                }
            ]
        return fns

    async def _call_tool(self, name: str, call_id: str, raw_args: str | dict) -> dict[str, Any]:
        tool = self.tools.get(name)
        if tool is None and "." in name:
            tool = self.tools.get(name.rsplit(".", 1)[-1])
        started = time.monotonic()
        args: dict[str, Any] = {}
        if tool is None:
            output, error = {"error": f"unknown tool {name!r}"}, "unknown_tool"
        else:
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                if not isinstance(args, dict):
                    raise ValueError
            except ValueError:
                args = {}
            await _emit(
                self.on_event,
                ToolEvent("tool_start", name=tool.name, call_id=call_id, arguments=args),
            )
            output, error = await self._invoke(tool, args)
        duration = round((time.monotonic() - started) * 1000, 1)
        tool_name = tool.name if tool else name
        self.records.append(ToolCallRecord(tool_name, call_id, args, output, error, duration))
        with self.llm.tracer.tool(f"tool:{tool_name}") as span:
            span.update(metadata={"duration_ms": duration, "error": error})
        await _emit(
            self.on_event,
            ToolEvent(
                "tool_end",
                name=tool_name,
                call_id=call_id,
                arguments=args,
                output=output,
                error=error,
                duration_ms=duration,
            ),
        )
        return output

    async def _invoke(self, tool: Tool, args: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        try:
            params = tool.params_model.model_validate(args)
        except ValidationError as exc:
            return {"error": f"invalid arguments: {validation_feedback(exc)}"}, "invalid_arguments"
        try:
            out = await tool.handler(params)
        except Exception as exc:
            log.warning("tool %s failed: %s", tool.name, type(exc).__name__)
            return {"error": "tool failed"}, type(exc).__name__
        if isinstance(out, BaseModel):
            return out.model_dump(mode="json"), None
        return dict(out), None

    def _parse_final(self, text: str) -> Any:
        assert self.final_schema is not None
        return self.final_schema.model_validate(extract_json(text))

    def _result(self, text: str, output: Any, mode: str) -> ToolRunResult:
        return ToolRunResult(
            text=text,
            output=output,
            tool_calls=self.records,
            usage=self.usage,
            model=self.model,
            tool_mode=mode,
            rounds=self.rounds,
        )

    async def native(self, instructions: str, items: list[Any], mode: ToolMode) -> ToolRunResult:
        caps = self.llm._caps
        items = list(items)
        budget_exhausted = False
        bad_outputs = 0

        async def on_delta(delta: str) -> None:
            await _emit(self.on_event, ToolEvent("text_delta", delta=delta))

        while True:
            params: dict[str, Any] = {"model": self.model, "input": items}
            instr = instructions
            if self.tools:
                params["tools"] = self._tools_param(mode)
                params["parallel_tool_calls"] = True
                if budget_exhausted:
                    params["tool_choice"] = "none"
            if caps.include_reasoning:
                params["include"] = ["reasoning.encrypted_content"]
                self.used_include = True
            if self.final_schema is not None:
                if caps.json_schema:
                    params["text"] = {
                        "format": {
                            "type": "json_schema",
                            "name": schema_name(self.final_schema),
                            "schema": self.final_json,
                            "strict": self.final_strict,
                        }
                    }
                    self.used_format = True
                else:
                    instr += json_only_instructions(self.final_json)
            params["instructions"] = instr
            result = await self.llm._collect(params, on_delta=on_delta)
            self.rounds += 1
            self.usage.add(result.usage)
            calls = [i for i in result.items if i.get("type") == "function_call"]
            items.extend(_replayable(i) for i in result.items)
            if calls:
                for call in calls:
                    call_id = call.get("call_id") or call.get("id") or ""
                    if len(self.records) >= self.max_tool_calls:
                        output = {"error": "tool call budget exhausted; answer now"}
                        budget_exhausted = True
                    else:
                        output = await self._call_tool(
                            call.get("name", ""), call_id, call.get("arguments") or "{}"
                        )
                    items.append(
                        {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": json.dumps(output, default=str),
                        }
                    )
                if len(self.records) >= self.max_tool_calls:
                    budget_exhausted = True
                continue
            if self.final_schema is None:
                return self._result(result.text, None, mode)
            try:
                return self._result(result.text, self._parse_final(result.text), mode)
            except (ValidationError, ValueError) as exc:
                bad_outputs += 1
                if bad_outputs > 2:
                    raise LLMError("bad_output", "final answer failed validation") from None
                items.append(
                    {
                        "role": "user",
                        "content": "Your previous reply was invalid: "
                        f"{validation_feedback(exc)}. Reply again with only the corrected JSON.",
                    }
                )

    async def json_protocol(self, instructions: str, items: list[Any]) -> ToolRunResult:
        tool_specs = [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.params_model.model_json_schema(),
            }
            for t in self.tools.values()
        ]
        instr = instructions + tool_protocol_instructions(tool_specs, self.final_json)
        items = list(items)
        bad_outputs = 0
        call_no = 0
        while True:
            result = await self.llm._collect(
                {"model": self.model, "instructions": instr, "input": items}
            )
            self.rounds += 1
            self.usage.add(result.usage)
            text = result.text
            try:
                action = extract_json(text)
            except ValueError:
                action = None
            if isinstance(action, dict) and "tool" in action:
                items.append({"role": "assistant", "content": text})
                call_no += 1
                call_id = f"json_call_{call_no}"
                if len(self.records) >= self.max_tool_calls:
                    output = {"error": "tool call budget exhausted; give the final answer now"}
                else:
                    output = await self._call_tool(
                        str(action["tool"]), call_id, action.get("arguments") or {}
                    )
                items.append(
                    {
                        "role": "user",
                        "content": f'<tool_result name="{action["tool"]}">'
                        f"{json.dumps(output, default=str)}</tool_result>",
                    }
                )
                continue
            final = action.get("final") if isinstance(action, dict) and "final" in action else None
            if self.final_schema is None:
                answer = (
                    final if isinstance(final, str) else (text if final is None else str(final))
                )
                await _emit(self.on_event, ToolEvent("text_delta", delta=answer))
                return self._result(answer, None, "json")
            try:
                candidate = final if final is not None else action
                parsed = self.final_schema.model_validate(candidate)
                return self._result(json.dumps(candidate), parsed, "json")
            except ValidationError as exc:
                feedback = validation_feedback(exc)
            bad_outputs += 1
            if bad_outputs > 2:
                raise LLMError("bad_output", "final answer failed validation")
            items.append({"role": "assistant", "content": text or "(empty)"})
            items.append(
                {
                    "role": "user",
                    "content": f"Invalid reply: {feedback}. Reply with ONLY one JSON object "
                    'following the protocol ({"tool": ...} or {"final": ...}).',
                }
            )
