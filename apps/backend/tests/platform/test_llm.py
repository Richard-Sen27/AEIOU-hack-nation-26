import asyncio

import pytest
from pydantic import BaseModel, Field

from backend.devtools.mock_openai.api import FORBIDDEN_FIELDS
from backend.llm import LLMClient, LLMError, StaticToken, Tool, ToolEvent

TOKEN = StaticToken("mock-static-test")


class Answer(BaseModel):
    summary: str
    edge_ids: list[str]


class Strict(BaseModel):
    count: int = Field(ge=10)


class SearchIn(BaseModel):
    query: str


class PathIn(BaseModel):
    from_id: str
    to_id: str


def _llm(mock) -> LLMClient:
    return LLMClient(TOKEN, base_url=mock.api_base)


def _bodies(mock):
    return [r["body"] for r in mock.state.recorded("responses")]


def _assert_plan_safe(body):
    assert body["store"] is False and body["stream"] is True
    assert not set(FORBIDDEN_FIELDS) & set(body)
    assert isinstance(body["input"], list)
    assert all(i.get("role") != "system" for i in body["input"] if isinstance(i, dict))


async def test_models_and_resolution(mock_openai):
    llm = _llm(mock_openai)
    models = await llm.list_models()
    assert [m.slug for m in models if m.visibility == "list"] == ["gpt-mock-main", "gpt-mock-mini"]
    assert await llm.resolve_model("main") == "gpt-mock-main"
    assert await llm.resolve_model("small") == "gpt-mock-mini"
    override = LLMClient(TOKEN, base_url=mock_openai.api_base, model_overrides={"main": "x"})
    assert await override.resolve_model("main") == "x"


async def test_complete_and_stream_text(mock_openai):
    llm = _llm(mock_openai)
    text = await llm.complete_text(instructions="Be brief.", input="See e_0123456789ab.")
    assert "e_0123456789ab" in text
    chunks = [c async for c in llm.stream_text(instructions="x", input="hello")]
    assert len(chunks) > 1 and "mock answer" in "".join(chunks)
    for body in _bodies(mock_openai):
        _assert_plan_safe(body)
        assert body["instructions"] in ("Be brief.", "x")


async def test_system_items_become_developer(mock_openai):
    llm = _llm(mock_openai)
    await llm.complete_text(
        instructions="x",
        input=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
    )
    assert _bodies(mock_openai)[-1]["input"][0]["role"] == "developer"


async def test_structured_json_schema(mock_openai):
    llm = _llm(mock_openai)
    out = await llm.structured(Answer, instructions="x", input="edge e_aaaaaaaaaaaa")
    assert out.edge_ids == ["e_aaaaaaaaaaaa"]
    body = _bodies(mock_openai)[-1]
    fmt = body["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True
    assert fmt["schema"]["additionalProperties"] is False
    assert body["model"] == "gpt-mock-mini"


async def test_structured_fallback_when_json_schema_rejected(mock_openai):
    mock_openai.configure(reject_json_schema=True)
    llm = _llm(mock_openai)
    out = await llm.structured(Answer, instructions="x", input="edge e_bbbbbbbbbbbb")
    assert out.edge_ids == ["e_bbbbbbbbbbbb"]
    last = _bodies(mock_openai)[-1]
    assert "text" not in last and "<json_schema>" in last["instructions"]
    # capability is remembered: next call goes straight to JSON prompting
    before = len(_bodies(mock_openai))
    await llm.structured(Answer, instructions="x", input="e_cccccccccccc")
    assert len(_bodies(mock_openai)) == before + 1


async def test_structured_retries_with_validation_feedback(mock_openai):
    mock_openai.enqueue({"json": {"count": 1}}, {"text": "not json"}, {"json": {"count": 12}})
    llm = _llm(mock_openai)
    out = await llm.structured(Strict, instructions="x", input="count things")
    assert out.count == 12
    retry_input = _bodies(mock_openai)[-1]["input"]
    assert "invalid" in retry_input[-1]["content"]
    assert retry_input[-2]["role"] == "assistant"


async def test_structured_bad_output_after_retries(mock_openai):
    mock_openai.enqueue(*[{"json": {"count": 1}}] * 3)
    with pytest.raises(LLMError) as exc:
        await _llm(mock_openai).structured(Strict, instructions="x", input="y", max_retries=2)
    assert exc.value.code == "bad_output"


def _tools(log):
    async def search(p: SearchIn):
        log.append(("search_graph", p.query))
        return {"results": [{"id": "MONDO:0100135", "edge_id": "e_0123456789ab"}]}

    async def path(p: PathIn):
        log.append(("find_path", p.from_id, p.to_id))
        return {"status": "ok", "edge_ids": ["e_fedcba987654"]}

    return [
        Tool("search_graph", "Search the graph", SearchIn, search),
        Tool("find_path", "Find a path", PathIn, path),
    ]


async def test_run_tools_native_namespace(mock_openai):
    calls: list = []
    events: list[ToolEvent] = []
    llm = _llm(mock_openai)
    result = await llm.run_tools(
        instructions="You are Dr. Wu.",
        input="My daughter has STXBP1 and seizures",
        tools=_tools(calls),
        final_schema=Answer,
        on_event=events.append,
    )
    assert result.tool_mode == "namespace"
    assert [c.name for c in result.tool_calls] == ["search_graph", "find_path"]
    assert calls[0] == ("search_graph", "My daughter has STXBP1 and seizures")
    assert calls[1][1] == "MONDO:0100135"
    assert set(result.output.edge_ids) == {"e_0123456789ab", "e_fedcba987654"}
    assert result.usage.total_tokens > 0
    kinds = [e.type for e in events]
    assert kinds[:4] == ["tool_start", "tool_end", "tool_start", "tool_end"]
    assert "text_delta" in kinds
    bodies = _bodies(mock_openai)
    for body in bodies:
        _assert_plan_safe(body)
        assert body["tools"][0]["type"] == "namespace"
        assert body["include"] == ["reasoning.encrypted_content"]
    last_input = bodies[-1]["input"]
    types = [i.get("type") for i in last_input]
    assert types.count("function_call_output") == 2
    reasoning = [i for i in last_input if i.get("type") == "reasoning"]
    assert reasoning and all(r.get("encrypted_content") for r in reasoning)
    assert all("id" not in i for i in last_input if i.get("type") == "function_call")


async def test_run_tools_falls_back_to_top_level_functions(mock_openai):
    mock_openai.configure(reject_namespace_tools=True, allow_top_level_functions=True)
    result = await _llm(mock_openai).run_tools(
        instructions="x", input="STXBP1", tools=_tools([]), final_schema=Answer
    )
    assert result.tool_mode == "function"
    assert len(result.tool_calls) == 2
    assert _bodies(mock_openai)[-1]["tools"][0]["type"] == "function"


async def test_run_tools_falls_back_to_json_protocol(mock_openai):
    mock_openai.configure(reject_function_tools=True)
    calls: list = []
    events: list[ToolEvent] = []
    result = await _llm(mock_openai).run_tools(
        instructions="x",
        input="STXBP1 seizures",
        tools=_tools(calls),
        final_schema=Answer,
        on_event=events.append,
    )
    assert result.tool_mode == "json"
    assert [c[0] for c in calls] == ["search_graph", "find_path"]
    assert "e_0123456789ab" in result.output.edge_ids
    assert "tools" not in _bodies(mock_openai)[-1]
    assert [e.type for e in events].count("tool_end") == 2


async def test_run_tools_json_protocol_plain_text(mock_openai):
    mock_openai.configure(reject_function_tools=True)
    result = await _llm(mock_openai).run_tools(instructions="x", input="hi", tools=_tools([]))
    assert result.output is None and "mock answer" in result.text


async def test_run_tools_without_final_schema_and_reasoning_rejected(mock_openai):
    mock_openai.configure(reject_include=True)
    result = await _llm(mock_openai).run_tools(instructions="x", input="hi", tools=_tools([]))
    assert "mock answer" in result.text
    assert "include" not in _bodies(mock_openai)[-1]


async def test_run_tools_call_cap(mock_openai):
    script = {"tool_calls": [{"name": "search_graph", "arguments": {"query": "a"}}] * 3}
    mock_openai.enqueue(script, script, {"text": "done"})
    calls: list = []
    result = await _llm(mock_openai).run_tools(
        instructions="x", input="hi", tools=_tools(calls), max_tool_calls=4
    )
    assert len(result.tool_calls) == 4 and len(calls) == 4
    last = _bodies(mock_openai)[-1]
    assert last["tool_choice"] == "none"
    outputs = [i["output"] for i in last["input"] if i.get("type") == "function_call_output"]
    assert sum("budget exhausted" in o for o in outputs) == 2
    assert result.text == "done"


async def test_run_tools_invalid_arguments_and_tool_errors(mock_openai):
    async def boom(p: SearchIn):
        raise RuntimeError("secret detail")

    mock_openai.enqueue(
        {"tool_calls": [{"name": "search_graph", "arguments": {"nope": 1}}]},
        {"tool_calls": [{"name": "boom", "arguments": {"query": "x"}}]},
        {"tool_calls": [{"name": "missing", "arguments": {}}]},
        {"text": "ok"},
    )
    tools = [*_tools([]), Tool("boom", "fails", SearchIn, boom)]
    result = await _llm(mock_openai).run_tools(instructions="x", input="hi", tools=tools)
    errors = [c.error for c in result.tool_calls]
    assert errors == ["invalid_arguments", "RuntimeError", "unknown_tool"]
    outputs = [
        i["output"]
        for i in _bodies(mock_openai)[-1]["input"]
        if i.get("type") == "function_call_output"
    ]
    assert not any("secret detail" in o for o in outputs)


async def test_run_tools_deadline(mock_openai):
    async def slow(p: SearchIn):
        await asyncio.sleep(2)
        return {}

    with pytest.raises(LLMError) as exc:
        await _llm(mock_openai).run_tools(
            instructions="x",
            input="hi",
            tools=[Tool("search_graph", "slow", SearchIn, slow)],
            deadline_s=0.5,
        )
    assert exc.value.code == "timeout"


@pytest.mark.parametrize(
    "switch,code",
    [
        ("usage_limit", "usage_limit_exceeded"),
        ("usage_limit_stream", "usage_limit_exceeded"),
        ("unavailable", "usage_unavailable"),
        ("unauthorized", "reauth_required"),
    ],
)
async def test_error_mapping(mock_openai, switch, code):
    mock_openai.configure(fail_mode=switch)
    llm = _llm(mock_openai)
    await llm.resolve_model("main")
    with pytest.raises(LLMError) as exc:
        await llm.complete_text(instructions="x", input="y")
    assert exc.value.code == code


@pytest.mark.parametrize(
    "script,code",
    [
        ({"fail": "subscription_sharing_usage_unavailable"}, "usage_unavailable"),
        ({"fail": "server_error"}, "upstream"),
        ({"text": "partial", "incomplete": True}, "upstream"),
        (
            {"error": {"status": 403, "code": "subscription_sharing_user_not_eligible"}},
            "usage_unavailable",
        ),
        ({"error": {"status": 429, "code": "rate_limit_exceeded"}}, "usage_limit_exceeded"),
    ],
)
async def test_stream_failures(mock_openai, script, code):
    mock_openai.enqueue(script)
    with pytest.raises(LLMError) as exc:
        await _llm(mock_openai).complete_text(instructions="x", input="y")
    assert exc.value.code == code


async def test_invalid_token_is_reauth(mock_openai):
    llm = LLMClient(StaticToken("bogus"), base_url=mock_openai.api_base)
    with pytest.raises(LLMError) as exc:
        await llm.list_models()
    assert exc.value.code == "reauth_required"


async def test_401_triggers_one_forced_refresh(mock_openai):
    class Provider:
        def __init__(self):
            self.token = "bogus"
            self.refreshed = 0

        async def get_token(self):
            return self.token

        async def force_refresh(self):
            self.refreshed += 1
            self.token = "mock-static-fresh"

    provider = Provider()
    llm = LLMClient(
        provider, base_url=mock_openai.api_base, model_overrides={"main": "gpt-mock-main"}
    )
    assert "mock answer" in await llm.complete_text(instructions="x", input="y")
    assert provider.refreshed == 1


async def test_errors_do_not_leak_prompt(mock_openai):
    mock_openai.configure(fail_mode="usage_limit")
    llm = LLMClient(TOKEN, base_url=mock_openai.api_base, model_overrides={"main": "gpt-mock-main"})
    with pytest.raises(LLMError) as exc:
        await llm.complete_text(instructions="x", input="Patient Jane Roe has STXBP1")
    assert "Jane" not in str(exc.value) and "mock-static" not in str(exc.value)


async def test_agents_sdk_streamed_run(mock_openai):
    from agents import Agent, Runner, function_tool

    from backend.llm.agents_sdk import (
        build_agents_model,
        model_settings,
        namespaced_tools,
        run_config,
    )

    seen = []

    @function_tool
    def pubmed_search(query: str) -> str:
        """Search PubMed for a query."""
        seen.append(query)
        return '{"pmids": ["PMID:123"], "edge": "e_0123456789ab"}'

    model = await build_agents_model(_llm(mock_openai))
    agent = Agent(
        name="gap",
        instructions="Find missing evidence.",
        model=model,
        tools=namespaced_tools([pubmed_search]),
        model_settings=model_settings(),
    )
    run = Runner.run_streamed(agent, "SCN1A pathway", run_config=run_config(), max_turns=4)
    async for _ in run.stream_events():
        pass
    assert seen == ["SCN1A pathway"]
    assert "e_0123456789ab" in run.final_output
    for body in _bodies(mock_openai):
        _assert_plan_safe(body)
