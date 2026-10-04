import httpx
import pytest

AUTH = {"Authorization": "Bearer mock-static-test"}
BASE = {"model": "gpt-mock-main", "input": [{"role": "user", "content": "hi"}]}


async def _post(mock, body, headers=AUTH):
    async with httpx.AsyncClient() as client:
        return await client.post(f"{mock.api_base}/responses", json=body, headers=headers)


@pytest.mark.parametrize(
    "body,param",
    [
        ({**BASE, "stream": True}, "store"),
        ({**BASE, "store": False}, "stream"),
        ({**BASE, "store": False, "stream": True, "temperature": 0.2}, "temperature"),
        ({**BASE, "store": False, "stream": True, "max_output_tokens": 10}, "max_output_tokens"),
        (
            {**BASE, "store": False, "stream": True, "previous_response_id": "r"},
            "previous_response_id",
        ),
        ({**BASE, "store": False, "stream": True, "input": "plain string"}, "input"),
        (
            {**BASE, "store": False, "stream": True, "input": [{"role": "system", "content": "s"}]},
            "input[0]",
        ),
        (
            {
                **BASE,
                "store": False,
                "stream": True,
                "tools": [{"type": "function", "name": "f", "parameters": {}}],
            },
            "tools",
        ),
        ({**BASE, "store": False, "stream": True, "tools": [{"type": "file_search"}]}, "tools"),
        (
            {
                **BASE,
                "store": False,
                "stream": True,
                "input": [{"type": "reasoning", "id": "rs_1", "summary": []}],
            },
            "input[0]",
        ),
    ],
)
async def test_rejects_requests_the_preview_rejects(mock_openai, body, param):
    resp = await _post(mock_openai, body)
    assert resp.status_code == 400
    assert resp.json()["error"]["param"] == param


async def test_streams_sse(mock_openai):
    resp = await _post(mock_openai, {**BASE, "store": False, "stream": True})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert "response.output_text.delta" in resp.text and "response.completed" in resp.text


async def test_requires_valid_bearer(mock_openai):
    resp = await _post(mock_openai, {**BASE, "store": False, "stream": True}, headers={})
    assert resp.status_code == 401


async def test_control_endpoints(mock_openai):
    async with httpx.AsyncClient(base_url=mock_openai.url) as client:
        assert (await client.post("/_mock/queue", json={"text": "scripted"})).json()["queued"] == 1
        await client.post("/_mock/config", json={"stream_delay_s": 0})
        users = (await client.get("/_mock/users")).json()
        assert {u["key"] for u in users} == {"alice", "bob", "carol"}
    resp = await _post(mock_openai, {**BASE, "store": False, "stream": True})
    assert '"delta": "scripted"' in resp.text
    async with httpx.AsyncClient(base_url=mock_openai.url) as client:
        recorded = (await client.get("/_mock/requests", params={"kind": "responses"})).json()
    assert recorded[-1]["body"]["store"] is False


async def test_consent_page_without_mock_user(mock_openai, oai_settings):
    from backend.openai_auth import DYNAMIC_CLIENT_ID, AuthTransaction, OIDCClient, new_host_id

    oidc = OIDCClient(oai_settings)
    tx = AuthTransaction.new(
        redirect_uri="http://127.0.0.1:9/auth/callback", client_id=DYNAMIC_CLIENT_ID
    )
    url = oidc.authorize_url(await oidc.discovery(), tx, ext_agent_host_id=new_host_id())
    async with httpx.AsyncClient() as client:
        page = await client.get(url)
        bad = await client.get(url.replace("127.0.0.1%3A9", "localhost%3A9"))
    assert page.status_code == 200 and "development only" in page.text
    assert bad.status_code == 400


# ---- auto responder: chat-like tool loop -----------------------------------------------------

from typing import Literal  # noqa: E402

from pydantic import BaseModel, Field  # noqa: E402

from backend.llm import LLMClient, LLMError, StaticToken, Tool  # noqa: E402


class Mention(BaseModel):
    text: str
    english: str | None
    negated: bool


class Extraction(BaseModel):
    diseases: list[Mention]
    genes: list[Mention]
    variants: list[Mention]
    symptoms: list[Mention]
    age_years: int | None
    onset: str | None
    country: str | None


class ExtractIn(BaseModel):
    text: str | None = None


class MentionIn(BaseModel):
    text: str
    type: Literal["disease", "gene", "variant", "symptom"]
    negated: bool


class ResolveIn(BaseModel):
    mentions: list[MentionIn]


class SearchIn(BaseModel):
    query: str
    limit: int | None = None


class NeighborhoodIn(BaseModel):
    node_id: str


class PathIn(BaseModel):
    from_id: str
    to_id: str


class FollowupIn(BaseModel):
    candidate_cluster_ids: list[str]


class Claim(BaseModel):
    text: str
    edge_ids: list[str]
    origin: Literal["observed", "inferred", "patient_reported", "user_contributed"]
    confidence: Literal["high", "medium", "low"]


class Card(BaseModel):
    type: Literal["mini_graph", "patient_group", "evidence", "open_in_atlas"]
    node_ids: list[str]
    edge_ids: list[str]


class Focus(BaseModel):
    node_ids: list[str]
    highlight_path: list[str]


class FollowUp(BaseModel):
    question: str
    quick_replies: list[str]


class Draft(BaseModel):
    summary: str = Field(description="Plain-language answer.")
    uncertainty: str | None
    claims: list[Claim]
    contradictions: list[dict]
    missing_evidence: list[str]
    cards: list[Card]
    graph_focus: Focus | None
    actions: list[dict]
    follow_up: FollowUp | None


STXBP1, DEE4, DRAVET = "HGNC:11444", "MONDO:0100143", "MONDO:0100135"
USER_TEXT = (
    "My daughter is 2, diagnosed with STXBP1 last month. Lots of seizures, not walking yet, "
    "no problems with eating."
)


def _chat_tools(llm: LLMClient, calls: list, extractions: list):
    async def extract_entities(p: ExtractIn):
        calls.append(("extract_entities", p.text))
        out = await llm.structured(Extraction, instructions="Extract.", input=p.text or "")
        extractions.append(out)
        return out.model_dump()

    async def resolve_to_ids(p: ResolveIn):
        calls.append(("resolve_to_ids", [(m.text, m.type) for m in p.mentions]))
        return {"resolved": [{"id": STXBP1, "label": "STXBP1", "type": "gene"}]}

    async def search_graph(p: SearchIn):
        calls.append(("search_graph", p.query))
        return {
            "results": [
                {"id": DEE4, "label": "STXBP1 encephalopathy", "type": "disease"},
                {"id": DRAVET, "label": "Dravet syndrome", "type": "disease"},
            ]
        }

    async def get_neighborhood(p: NeighborhoodIn):
        calls.append(("get_neighborhood", p.node_id))
        return {
            "node": {"id": p.node_id, "label": "STXBP1"},
            "edges": [
                {
                    "id": "e_aaaaaaaaaaa1",
                    "source": DEE4,
                    "relation": "caused_by_variant_in",
                    "target": STXBP1,
                    "confidence": 0.92,
                    "origin": "observed",
                },
                {
                    "id": "e_bbbbbbbbbbb2",
                    "source": DEE4,
                    "relation": "similar_symptoms",
                    "target": DRAVET,
                    "confidence": 0.4,
                    "origin": "inferred",
                },
            ],
        }

    async def find_path(p: PathIn):
        calls.append(("find_path", p.from_id, p.to_id))
        return {"status": "ok", "paths": [{"edge_ids": ["e_bbbbbbbbbbb2"]}]}

    async def ask_followup(p: FollowupIn):
        calls.append(("ask_followup",))
        return {}

    specs = [
        ("extract_entities", ExtractIn, extract_entities),
        ("resolve_to_ids", ResolveIn, resolve_to_ids),
        ("search_graph", SearchIn, search_graph),
        ("get_neighborhood", NeighborhoodIn, get_neighborhood),
        ("find_path", PathIn, find_path),
        ("ask_followup", FollowupIn, ask_followup),
    ]
    return [Tool(n, n, m, h) for n, m, h in specs]


async def test_auto_responder_runs_chat_like_tool_loop(mock_openai):
    llm = LLMClient(StaticToken("mock-static-test"), base_url=mock_openai.api_base)
    calls, extractions = [], []
    result = await llm.run_tools(
        instructions="You are Dr. Wu.",
        input=USER_TEXT,
        tools=_chat_tools(llm, calls, extractions),
        final_schema=Draft,
    )
    names = [c[0] for c in calls]
    assert names == [
        "extract_entities",
        "resolve_to_ids",
        "search_graph",
        "get_neighborhood",
        "find_path",
    ]
    assert calls[0][1] == USER_TEXT
    assert ("STXBP1", "gene") in calls[1][1]
    assert calls[2][1] == "STXBP1"
    assert calls[3][1] == STXBP1
    assert calls[4][1:] == (DEE4, DRAVET)

    ext = extractions[0]
    assert [g.text for g in ext.genes] == ["STXBP1"]
    assert ext.age_years == 2 and ext.country is None
    symptoms = {s.english: s.negated for s in ext.symptoms}
    assert symptoms["Seizure"] is False and symptoms["Feeding difficulties"] is True

    draft = result.output
    assert "STXBP1" in draft.summary and "Dravet syndrome" in draft.summary
    assert draft.claims and all(c.origin == "observed" for c in draft.claims)
    assert draft.claims[0].edge_ids == ["e_aaaaaaaaaaa1"]
    assert draft.claims[0].confidence == "high"
    assert "caused by variant in" in draft.claims[0].text
    assert set(draft.graph_focus.node_ids) >= {STXBP1, DEE4}
    assert draft.graph_focus.highlight_path == ["e_bbbbbbbbbbb2"]
    assert draft.cards and STXBP1 in draft.cards[0].node_ids
    assert draft.follow_up is None and draft.uncertainty is None


async def test_queue_kind_filter(mock_openai):
    llm = LLMClient(StaticToken("mock-static-test"), base_url=mock_openai.api_base)

    async def nested(p: SearchIn):
        inner = await llm.structured(Mention, instructions="x", input="STXBP1 seizures")
        return {"inner": inner.text}

    mock_openai.enqueue(
        {"kind": "tools", "tool_calls": [{"name": "search_graph", "arguments": {"query": "q"}}]},
        {"kind": "tools", "text": "scripted final"},
    )
    result = await llm.run_tools(
        instructions="x", input="hi", tools=[Tool("search_graph", "s", SearchIn, nested)]
    )
    assert result.text == "scripted final"
    assert result.tool_calls[0].output == {"inner": "STXBP1"}
    assert not mock_openai.state.queue


async def test_fail_nth_request_and_clear_requests(mock_openai, oai_settings, authorize):
    from backend.openai_auth import DYNAMIC_CLIENT_ID, AuthTransaction, OIDCClient, new_host_id

    oidc = OIDCClient(oai_settings)
    tx = AuthTransaction.new(
        redirect_uri="http://127.0.0.1:9/auth/callback", client_id=DYNAMIC_CLIENT_ID
    )
    params = await authorize(
        oidc.authorize_url(await oidc.discovery(), tx, ext_agent_host_id=new_host_id())
    )
    tokens, _ = await oidc.exchange_code(tx, params["code"], client_id=params["client_id"])

    mock_openai.configure(fail_on_request=2, fail_on_request_mode="usage_limit")
    llm = LLMClient(
        StaticToken(tokens.access_token),
        base_url=mock_openai.api_base,
        model_overrides={"main": "gpt-mock-main"},
    )
    await llm.complete_text(instructions="x", input="one")
    with pytest.raises(LLMError) as exc:
        await llm.complete_text(instructions="x", input="two")
    assert exc.value.code == "usage_limit_exceeded"
    await llm.complete_text(instructions="x", input="three")

    mock_openai.clear_requests()
    assert mock_openai.state.recorded() == []
    assert params["client_id"] in mock_openai.state.clients
    assert await oidc.refresh(tokens)
    async with httpx.AsyncClient(base_url=mock_openai.url) as client:
        assert (await client.delete("/_mock/requests")).json() == {"ok": True}


async def test_file_inputs_rejected_only_when_switched_on(mock_openai):
    image = {
        **BASE,
        "store": False,
        "stream": True,
        "input": [{"role": "user", "content": [{"type": "input_image", "image_url": "data:,x"}]}],
    }
    assert (await _post(mock_openai, image)).status_code == 200
    mock_openai.configure(reject_file_inputs=True)
    resp = await _post(mock_openai, image)
    assert resp.status_code == 400 and resp.json()["error"]["param"] == "input[0].content"


async def test_usage_numbers_are_plausible(mock_openai):
    llm = LLMClient(StaticToken("mock-static-test"), base_url=mock_openai.api_base)
    long_input = "word " * 400
    result = await llm.run_tools(instructions="x", input=long_input, tools=[], final_schema=None)
    assert 400 <= result.usage.input_tokens <= 800
    assert result.usage.output_tokens > 0
    assert result.usage.reasoning_tokens > 0  # include=reasoning.encrypted_content was sent
