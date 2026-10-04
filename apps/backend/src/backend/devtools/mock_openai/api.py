"""Mock of api.openai.com/v1 for ChatGPT plan usage: /models and streaming /responses."""

import asyncio
import json
import secrets
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from backend.devtools.mock_openai.responder import Plan, plan_response
from backend.devtools.mock_openai.state import PLAN_SCOPE_TOKEN, MockState

FORBIDDEN_FIELDS = (
    "background",
    "conversation",
    "max_output_tokens",
    "max_tool_calls",
    "metadata",
    "moderation",
    "multi_agent",
    "prompt",
    "prompt_cache_retention",
    "safety_identifier",
    "temperature",
    "top_logprobs",
    "top_p",
    "truncation",
    "user",
    "previous_response_id",
)
HOSTED_TOOLS = {
    "image_generation",
    "file_search",
    "code_interpreter",
    "computer_use_preview",
    "computer",
    "computer_use",
    "mcp",
    "tool_search",
    "programmatic_tool_calling",
}
UNSUPPORTED = "subscription_sharing_unsupported_capability"


def api_error(status: int, message: str, *, code: str | None, param: str | None = None):
    return JSONResponse(
        {
            "error": {
                "message": message,
                "type": "invalid_request_error" if status == 400 else "api_error",
                "param": param,
                "code": code,
            }
        },
        status_code=status,
    )


def _auth(state: MockState, request: Request) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else ""
    claims = state.check_access_token(token) if token else None
    if claims is None:
        return None, api_error(401, "Invalid or expired access token", code="invalid_api_key")
    if PLAN_SCOPE_TOKEN not in str(claims.get("scope", "")).split():
        return None, api_error(
            403, "Token lacks plan usage scope", code="chatpass_v2_scope_not_authorized"
        )
    return claims, None


def validate_request(state: MockState, body: dict[str, Any]) -> JSONResponse | None:
    cfg = state.config
    if body.get("stream") is not True:
        return api_error(400, "stream must be true", code=UNSUPPORTED, param="stream")
    if body.get("store") is not False:
        return api_error(400, "store must be false", code=UNSUPPORTED, param="store")
    for name in FORBIDDEN_FIELDS:
        if name in body:
            return api_error(400, f"Unsupported parameter: {name}", code=UNSUPPORTED, param=name)
    if not isinstance(body.get("input"), list):
        return api_error(400, "input must be an array", code=UNSUPPORTED, param="input")
    slugs = {m["slug"] for m in cfg.models}
    if body.get("model") not in slugs:
        return api_error(
            400, "The requested model does not exist", code="model_not_found", param="model"
        )
    for i, item in enumerate(body["input"]):
        if not isinstance(item, dict):
            continue
        if item.get("role") == "system":
            return api_error(
                400, "system message items are not supported", code=UNSUPPORTED, param=f"input[{i}]"
            )
        if item.get("type") == "reasoning" and not item.get("encrypted_content"):
            return api_error(
                400,
                f"Item with id '{item.get('id')}' not found. Items are not persisted when "
                "`store` is set to false.",
                code=None,
                param=f"input[{i}]",
            )
    if cfg.reject_file_inputs:
        for i, item in enumerate(body["input"]):
            content = item.get("content") if isinstance(item, dict) else None
            for part in content if isinstance(content, list) else []:
                if isinstance(part, dict) and part.get("type") in ("input_image", "input_file"):
                    return api_error(
                        400,
                        f"{part['type']} is not supported",
                        code=UNSUPPORTED,
                        param=f"input[{i}].content",
                    )
    if "include" in body and cfg.reject_include:
        return api_error(400, "include is not supported", code=UNSUPPORTED, param="include")
    tools = list(body.get("tools") or [])
    for item in body["input"]:
        if isinstance(item, dict) and item.get("type") == "additional_tools":
            tools.extend(item.get("tools") or [])
    for tool in tools:
        ttype = tool.get("type")
        if ttype in HOSTED_TOOLS:
            return api_error(400, f"Tool {ttype} is not supported", code=UNSUPPORTED, param="tools")
        if ttype in ("function", "namespace", "custom") and cfg.reject_function_tools:
            return api_error(
                400, "function tools are not supported", code=UNSUPPORTED, param="tools"
            )
        if ttype == "namespace" and cfg.reject_namespace_tools:
            return api_error(
                400, "namespace tools are not supported", code=UNSUPPORTED, param="tools"
            )
        if ttype in ("function", "custom") and not cfg.allow_top_level_functions:
            if tool in (body.get("tools") or []):
                return api_error(
                    400,
                    "Group function/custom tools in namespaces or supply them through "
                    "additional_tools input items.",
                    code=UNSUPPORTED,
                    param="tools",
                )
    fmt = (body.get("text") or {}).get("format") or {}
    if fmt.get("type") == "json_schema" and cfg.reject_json_schema:
        return api_error(
            400, "text.format json_schema is not supported", code=UNSUPPORTED, param="text.format"
        )
    return None


def _response_obj(
    rid: str, body: dict[str, Any], status: str, output: list, usage=None, error=None
):
    return {
        "id": rid,
        "object": "response",
        "created_at": int(time.time()),
        "status": status,
        "model": body.get("model"),
        "output": output,
        "usage": usage,
        "error": error,
        "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None,
        "instructions": None,
        "metadata": {},
        "parallel_tool_calls": body.get("parallel_tool_calls", True),
        "temperature": None,
        "top_p": None,
        "tool_choice": body.get("tool_choice", "auto"),
        "tools": body.get("tools") or [],
        "store": False,
        "text": body.get("text") or {"format": {"type": "text"}},
        "reasoning": None,
        "truncation": "disabled",
        "background": False,
    }


def _plan_from_script(script: dict[str, Any], body: dict[str, Any]) -> Plan:
    if "tool_calls" in script:
        namespaces = {t.get("type"): t.get("name") for t in body.get("tools") or []}
        default_ns = namespaces.get("namespace")
        return Plan(
            calls=[
                (c["name"], c.get("arguments") or {}, c.get("namespace", default_ns))
                for c in script["tool_calls"]
            ]
        )
    if "json" in script:
        return Plan(text=json.dumps(script["json"]))
    return Plan(text=str(script.get("text", "")))


def request_kind(body: dict[str, Any]) -> str:
    if body.get("tools") or any(
        isinstance(i, dict) and i.get("type") == "additional_tools" for i in body["input"]
    ):
        return "tools"
    instructions = body.get("instructions") or ""
    if "<tools>[" in instructions:
        return "tools"
    fmt = (body.get("text") or {}).get("format") or {}
    if fmt.get("type") == "json_schema" or "<json_schema>{" in instructions:
        return "structured"
    return "text"


def _usage(body: dict[str, Any], output: list[dict[str, Any]]) -> dict[str, Any]:
    """Rough tokenizer: ~4 characters per token, as for English text."""
    prompt = json.dumps([body.get("instructions"), body.get("input"), body.get("tools")])
    in_tokens = max(8, len(prompt) // 4)
    visible = [o for o in output if o.get("type") != "reasoning"]
    reasoning = 0 if len(visible) == len(output) else 32 + 8 * len(visible)
    out_tokens = max(1, len(json.dumps(visible)) // 4) + reasoning
    return {
        "input_tokens": in_tokens,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens": out_tokens,
        "output_tokens_details": {"reasoning_tokens": reasoning},
        "total_tokens": in_tokens + out_tokens,
    }


async def _sse(
    state: MockState,
    body: dict[str, Any],
    plan: Plan,
    script: dict | None,
    mode: str | None = None,
):
    rid = f"resp_{secrets.token_hex(12)}"
    seq = 0
    output: list[dict[str, Any]] = []
    delay = state.config.stream_delay_s

    def ev(etype: str, **data: Any) -> str:
        nonlocal seq
        seq += 1
        payload = {"type": etype, "sequence_number": seq, **data}
        return f"event: {etype}\ndata: {json.dumps(payload)}\n\n"

    async def stream() -> AsyncIterator[str]:
        yield ev("response.created", response=_response_obj(rid, body, "in_progress", []))
        yield ev("response.in_progress", response=_response_obj(rid, body, "in_progress", []))
        index = 0
        if "reasoning.encrypted_content" in (body.get("include") or []):
            item = {
                "id": f"rs_{secrets.token_hex(8)}",
                "type": "reasoning",
                "summary": [],
                "encrypted_content": f"mock-enc-{secrets.token_hex(16)}",
            }
            yield ev("response.output_item.added", output_index=index, item=item)
            yield ev("response.output_item.done", output_index=index, item=item)
            output.append(item)
            index += 1
        if script and "fail" in script:
            error = {"code": script["fail"], "message": "Mock failure"}
            yield ev(
                "response.failed", response=_response_obj(rid, body, "failed", output, error=error)
            )
            return
        if mode == "usage_limit_stream":
            error = {"code": "subscription_sharing_usage_limit_exceeded", "message": "Limit"}
            yield ev(
                "response.failed", response=_response_obj(rid, body, "failed", output, error=error)
            )
            return
        for name, args, namespace in plan.calls:
            call_id = f"call_{secrets.token_hex(8)}"
            item = {
                "id": f"fc_{secrets.token_hex(8)}",
                "type": "function_call",
                "call_id": call_id,
                "name": name,
                "arguments": "",
                "status": "in_progress",
            }
            if namespace:
                item["namespace"] = namespace
            arguments = json.dumps(args)
            yield ev("response.output_item.added", output_index=index, item=item)
            yield ev(
                "response.function_call_arguments.delta",
                item_id=item["id"],
                output_index=index,
                delta=arguments,
            )
            yield ev(
                "response.function_call_arguments.done",
                item_id=item["id"],
                output_index=index,
                arguments=arguments,
                name=name,
            )
            done = {**item, "arguments": arguments, "status": "completed"}
            yield ev("response.output_item.done", output_index=index, item=done)
            output.append(done)
            index += 1
        if plan.text is not None:
            mid = f"msg_{secrets.token_hex(8)}"
            item = {
                "id": mid,
                "type": "message",
                "role": "assistant",
                "status": "in_progress",
                "content": [],
            }
            yield ev("response.output_item.added", output_index=index, item=item)
            part = {"type": "output_text", "text": "", "annotations": [], "logprobs": []}
            yield ev(
                "response.content_part.added",
                item_id=mid,
                output_index=index,
                content_index=0,
                part=part,
            )
            text = plan.text
            for start in range(0, len(text), 24):
                if delay:
                    await asyncio.sleep(delay)
                yield ev(
                    "response.output_text.delta",
                    item_id=mid,
                    output_index=index,
                    content_index=0,
                    delta=text[start : start + 24],
                    logprobs=[],
                )
            yield ev(
                "response.output_text.done",
                item_id=mid,
                output_index=index,
                content_index=0,
                text=text,
                logprobs=[],
            )
            full_part = {**part, "text": text}
            yield ev(
                "response.content_part.done",
                item_id=mid,
                output_index=index,
                content_index=0,
                part=full_part,
            )
            done = {**item, "status": "completed", "content": [full_part]}
            yield ev("response.output_item.done", output_index=index, item=done)
            output.append(done)
        if script and script.get("incomplete"):
            yield ev("response.incomplete", response=_response_obj(rid, body, "incomplete", output))
            return
        usage = _usage(body, output)
        yield ev(
            "response.completed",
            response=_response_obj(rid, body, "completed", output, usage=usage),
        )

    return StreamingResponse(stream(), media_type="text/event-stream")


def build_router(state: MockState) -> APIRouter:
    router = APIRouter(prefix="/v1")

    @router.get("/models")
    async def models(request: Request):
        _, err = _auth(state, request)
        if err:
            return err
        return {"models": state.config.models}

    @router.post("/responses")
    async def responses(request: Request):
        try:
            body = await request.json()
        except ValueError:
            return api_error(400, "invalid JSON body", code=None)
        state.record("responses", {"body": body})
        number = state.next_request_number()
        _, err = _auth(state, request)
        if err:
            return err
        mode = state.config.fail_mode
        if state.config.fail_on_request == number:
            mode = state.config.fail_on_request_mode
        if mode == "usage_limit":
            return api_error(
                429, "Usage limit reached", code="subscription_sharing_usage_limit_exceeded"
            )
        if mode == "unavailable":
            return api_error(503, "Unavailable", code="subscription_sharing_usage_unavailable")
        if mode == "unauthorized":
            return api_error(401, "Unauthorized", code="subscription_sharing_invalid_user")
        invalid = validate_request(state, body)
        if invalid is not None:
            return invalid
        script = state.pop_scripted(request_kind(body))
        if script and "error" in script:
            e = script["error"]
            return api_error(
                int(e.get("status", 400)),
                e.get("message", "Scripted error"),
                code=e.get("code"),
                param=e.get("param"),
            )
        if script and "fail" in script:
            plan = Plan()
        elif script:
            plan = _plan_from_script(script, body)
        else:
            plan = plan_response(body)
        return await _sse(state, body, plan, script, mode)

    return router
