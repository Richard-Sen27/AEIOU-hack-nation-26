import json

import pytest
from gapdata import ABSTRACT, EFETCH, ESEARCH, QUOTE

from backend.api.services import gap_search
from backend.api.services.gap_search import fetch
from backend.schemas.gap import GapSearchRequest

FROM, TO = "MONDO:0100135", "HGNC:11444"  # Dravet syndrome, STXBP1 (fixture graph)
PMID_URL = "https://pubmed.ncbi.nlm.nih.gov/40000001/"
MARKER = "Quokkamarker"  # user data that must never reach the model or a public API


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    async def _wait(host, interval):
        return None

    monkeypatch.setattr(fetch.throttle, "wait", _wait)


def _pubmed(net):
    net.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi").respond(json=ESEARCH)
    net.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi").respond(content=EFETCH)


def _candidate(**overrides) -> dict:
    c = {
        "source_id": FROM,
        "target_id": TO,
        "relation": "caused_by_variant_in",
        "quote": QUOTE,
        "source_url": PMID_URL,
    }
    c.update(overrides)
    return c


def _script(llm, *candidates):
    llm.enqueue(
        {"tool_calls": [{"name": "pubmed_search", "arguments": {"query": "Dravet STXBP1"}}]},
        {"json": {"candidates": list(candidates)}},
    )


def _events(resp) -> list[dict]:
    out = []
    for block in resp.text.replace("\r\n", "\n").split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                out.append(json.loads(line[5:].strip()))
    return out


async def _search(user, **body):
    return await user.client.post("/gap-search", json={"from_id": FROM, "to_id": TO, **body})


async def test_gap_search_streams_verified_candidates(make_user, llm, net, connect_as):
    conn = await connect_as("atlas")
    edges_before = await conn.fetchval("SELECT count(*) FROM edges")
    _pubmed(net)
    user = await make_user()
    _script(
        llm,
        _candidate(),
        _candidate(quote="Dravet syndrome is definitely caused by STXBP1 in every patient"),
        _candidate(source_url="https://pubmed.ncbi.nlm.nih.gov/99999999/"),
        _candidate(target_id="HGNC:10585"),  # not one of the two nodes
        _candidate(quote="short"),
    )
    resp = await _search(user)
    assert resp.status_code == 200
    events = _events(resp)
    assert [e["type"] for e in events] == ["progress", "progress", "candidate", "final"]
    assert events[1]["tool"] == "pubmed_search" and events[1]["step"] == 1
    cand = events[2]["candidate"]
    assert cand["quote"] == QUOTE and cand["source_url"] == PMID_URL
    assert cand["source_type"] == "pubmed" and cand["source_id_ref"] == "PMID:40000001"
    assert cand["status"] == "pending_review"
    final = events[3]
    assert final["candidate_count"] == 1 and final["stop_reason"] == "completed"

    # kept for the user on a job row; never written to graph tables
    job = await conn.fetchrow("SELECT * FROM jobs WHERE id = $1", final["job_id"])
    assert job["user_id"] == user.id and job["kind"] == "gap_search"
    assert job["status"] == "succeeded"
    result = json.loads(job["result"])
    assert result["candidates"][0]["quote"] == QUOTE and result["stop_reason"] == "completed"
    assert await conn.fetchval("SELECT count(*) FROM edges") == edges_before

    # the job is visible to its owner only
    other = await make_user()
    assert (await other.client.get(f"/jobs/{final['job_id']}")).status_code == 404
    job_stream = await user.client.get(f"/jobs/{final['job_id']}")
    assert _events(job_stream)[-1]["finding_count"] == 1


async def test_query_contains_no_user_data(make_user, llm, net, connect_as):
    _pubmed(net)
    user = await make_user()
    conn = await connect_as("atlas")
    await conn.execute(
        "INSERT INTO patient_profiles (user_id, profile) VALUES ($1, $2::jsonb)",
        user.id,
        json.dumps({"diseases": [{"id": FROM, "label": f"{MARKER} syndrome", "source": "chat"}]}),
    )
    sid = await conn.fetchval(
        "INSERT INTO chat_sessions (user_id, title) VALUES ($1, $2) RETURNING id", user.id, MARKER
    )
    await conn.execute(
        "INSERT INTO chat_messages (session_id, user_id, role, content)"
        " VALUES ($1, $2, 'user', $3)",
        sid,
        user.id,
        f"My son has {MARKER} and lives in Vienna",
    )
    _script(llm, _candidate())
    assert (await _search(user)).status_code == 200

    bodies = [json.dumps(r["body"]) for r in llm.state.recorded("responses")]
    assert bodies
    for body in bodies:
        assert MARKER not in body and str(user.id) not in body
    first = llm.state.recorded("responses")[0]["body"]
    user_items = [i for i in first["input"] if i.get("role") == "user"]
    terms = gap_search.PublicTerms.model_validate(
        {
            "source": json.loads(user_items[0]["content"])["node_a"],
            "target": json.loads(user_items[0]["content"])["node_b"],
            "family": "all",
        }
    )
    assert terms.source.label == "Dravet syndrome" and terms.target.label == "STXBP1"
    assert user_items[0]["content"] == gap_search.build_agent_input(terms)
    for call in net.calls:
        assert MARKER not in str(call.request.url)
        assert MARKER.encode() not in call.request.content


def test_agent_input_is_built_from_public_terms_only():
    import inspect

    params = inspect.signature(gap_search.build_agent_input).parameters
    assert list(params) == ["terms"]
    assert set(gap_search.PublicTerms.model_fields) == {"source", "target", "family"}
    assert set(gap_search.PublicNode.model_fields) == {"id", "type", "label", "synonyms"}


async def test_step_budget(make_user, llm, net, monkeypatch):
    _pubmed(net)
    monkeypatch.setattr(gap_search, "MAX_STEPS", 2)
    monkeypatch.setattr(gap_search, "MAX_TURNS", 4)
    call = {"tool_calls": [{"name": "pubmed_search", "arguments": {"query": "Dravet STXBP1"}}]}
    llm.enqueue(*[call] * 6)
    user = await make_user()
    events = _events(await _search(user))
    steps = [e for e in events if e["type"] == "progress" and e["tool"]]
    assert len(steps) == 2
    assert events[-1] == {**events[-1], "type": "final", "stop_reason": "max_steps"}


async def test_token_budget(make_user, llm, net, monkeypatch):
    _pubmed(net)
    monkeypatch.setattr(gap_search, "MAX_TOKENS", 10)
    _script(llm, _candidate())
    user = await make_user()
    events = _events(await _search(user))
    assert events[-1]["type"] == "final"
    assert events[-1]["stop_reason"] == "max_tokens"
    assert events[-1]["candidate_count"] == 0


async def test_timeout(make_user, llm, net, monkeypatch):
    monkeypatch.setattr(gap_search, "TIMEOUT_S", 0.5)
    llm.configure(stream_delay_s=0.4)
    _script(llm, _candidate())
    user = await make_user()
    events = _events(await _search(user))
    assert events[-1]["type"] == "final"
    assert events[-1]["stop_reason"] == "timeout"


async def test_falls_back_to_gateway_tool_loop(make_user, llm, net):
    _pubmed(net)
    llm.enqueue(
        {
            "error": {
                "status": 400,
                "code": "subscription_sharing_unsupported_capability",
                "param": "tools",
                "message": "Unsupported parameter",
            }
        }
    )
    _script(llm, _candidate())
    user = await make_user()
    events = _events(await _search(user))
    assert [e["type"] for e in events] == ["progress", "progress", "candidate", "final"]
    assert events[-1]["stop_reason"] == "completed"


async def test_usage_limit_is_an_error_event(make_user, llm, connect_as):
    llm.configure(fail_mode="usage_limit")
    user = await make_user()
    events = _events(await _search(user))
    assert events[-1]["type"] == "error" and events[-1]["code"] == "rate_limited"
    conn = await connect_as("atlas")
    job = await conn.fetchrow(
        "SELECT status, error FROM jobs WHERE user_id = $1 AND kind = 'gap_search'", user.id
    )
    assert job["status"] == "failed" and job["error"] == "llm_usage_limit_exceeded"


async def test_quote_must_come_from_a_fetched_page(llm):
    """A quote that only occurs in a page the agent never fetched is dropped."""
    ctx = gap_search.ToolContext(settings=None, max_steps=8)  # type: ignore[arg-type]
    ctx.keep(gap_search.gap_tools.Source(PMID_URL, ABSTRACT, "pubmed", "PMID:40000001"))
    terms = gap_search.PublicTerms(
        source=gap_search.PublicNode(id=FROM, type="disease", label="Dravet syndrome"),
        target=gap_search.PublicNode(id=TO, type="gene", label="STXBP1"),
        family="dna",
    )
    drafts = [
        gap_search.CandidateDraft(**_candidate()),
        gap_search.CandidateDraft(**_candidate(quote=QUOTE.upper())),  # same, case-insensitive
        gap_search.CandidateDraft(**_candidate(source_url="https://example.org/never-fetched")),
        gap_search.CandidateDraft(**_candidate(relation="authored")),  # wrong family
        # in the source, but does not name STXBP1
        gap_search.CandidateDraft(**_candidate(quote="Dravet syndrome share early-onset seizures")),
    ]
    out = gap_search.verify(drafts, terms, ctx)
    assert len(out) == 1 and out[0].quote == QUOTE


async def test_guest_gets_401(client):
    resp = await client.post("/gap-search", json={"from_id": FROM, "to_id": TO})
    assert resp.status_code == 401


async def test_unknown_node_404_and_same_node_422(make_user, llm):
    user = await make_user()
    resp = await user.client.post("/gap-search", json={"from_id": FROM, "to_id": "MONDO:0000000"})
    assert resp.status_code == 404
    resp = await user.client.post("/gap-search", json={"from_id": FROM, "to_id": FROM})
    assert resp.status_code == 422


async def test_without_openai_sign_in_401(make_user, mock_openai_env):
    user = await make_user()  # no stored OpenAI tokens
    resp = await _search(user)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "sign_in_required"


def test_request_model():
    assert GapSearchRequest(from_id=FROM, to_id=TO).family == "all"
