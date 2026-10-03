import json

import pytest
from agent_helpers import DEMO, post_sse

from backend.api.services.graph import get_graph
from backend.schemas.enums import VUS_NOTICE, EdgeStatus, Origin

STXBP1 = "MONDO:9900007"
SCN2A_LOF = "MONDO:9900005"
SIMILAR = DEMO["path_edge_ids"][0]  # inferred similar_symptoms, 0.9
LOW = DEMO["low_confidence_edge_id"]  # inferred shared_pathway, 0.3
CONTRADICTED = DEMO["contradicted_edge_id"]
EVENT_ORDER = ["chips", "claims", "cards", "actions", "follow_up", "final"]


def draft(**fields) -> dict:
    base = {
        "summary": "Two groups share some signs.",
        "uncertainty": None,
        "claims": [],
        "contradictions": [],
        "missing_evidence": [],
        "cards": [],
        "graph_focus": None,
        "actions": [],
        "follow_up": None,
    }
    return {**base, **fields}


def claim(text, edge_ids, origin="observed", confidence="high") -> dict:
    return {"text": text, "edge_ids": edge_ids, "origin": origin, "confidence": confidence}


def action(title, edge_ids, viable=True) -> dict:
    return {
        "title": title,
        "type": "reuse_asset",
        "viable": viable,
        "edge_ids": edge_ids,
        "timeline_today": "2 years to build a registry",
        "timeline_proposed": "3 months to join one",
        "assumptions": ["The registry accepts new members."],
    }


def neighborhood(node_id: str) -> dict:
    return {"tool_calls": [{"name": "get_neighborhood", "arguments": {"node_id": node_id}}]}


def observed_edge(node_id: str) -> str:
    store = get_graph()
    for eid in sorted(store.incident[node_id]):
        e = store.edges[eid]
        if (
            e.origin == Origin.observed
            and e.status == EdgeStatus.active
            and not e.contradiction_count
            and e.relation.value in ("serves", "has_phenotype", "caused_by_variant_in")
        ):
            return eid
    raise AssertionError("no observed edge")


async def turn(user, message, **extra) -> list[dict]:
    status, events = await post_sse(user.client, "/chat", {"message": message, **extra})
    assert status == 200, events
    return events


def final(events: list[dict]) -> dict:
    assert events[-1]["type"] == "final", events[-1]
    return events[-1]["reply"]


@pytest.fixture
async def doctor(make_user, user_llm):
    return await make_user(role="doctor")


async def test_guest_gets_401(client):
    resp = await client.post("/chat", json={"message": "hello"})
    assert resp.status_code == 401 and resp.json()["error"]["code"] == "sign_in_required"


async def test_unconfirmed_age_gets_403(make_user, user_llm):
    user = await make_user(role="patient", age_confirmed=False)
    resp = await user.client.post("/chat", json={"message": "hello"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "age_confirmation_required"


async def test_no_plan_tokens_gets_401(make_user, mock_openai_env):
    user = await make_user(role="patient")
    resp = await user.client.post("/chat", json={"message": "STXBP1 encephalopathy"})
    assert resp.status_code == 401 and resp.json()["error"]["code"] == "sign_in_required"


@pytest.mark.parametrize(
    "message,needle",
    [
        ("My son is not breathing and his lips are turning blue", "112"),
        ("Meine Tochter krampft seit 10 Minuten und hört nicht auf", "Notruf"),
        ("I want to end my life", "emergency"),
    ],
)
async def test_emergency_short_circuit(make_user, mock_openai_env, llm_calls, message, needle):
    user = await make_user(role="patient")  # no tokens: proves no LLM client is even needed
    events = await turn(user, message)
    reply = final(events)
    assert needle in reply["summary"]
    assert reply["claims"] == [] and reply["graph_focus"] is None
    assert reply["ai_notice"]
    assert llm_calls() == []


async def test_redaction_before_model(doctor, user_llm, llm_calls):
    user_llm.enqueue({"json": draft()})
    message = (
        "Patient: Johanna Mustermann, DOB 03.04.2019, MRN 88812345. "
        "She has STXBP1 encephalopathy. Call me at +43 660 1234567."
    )
    events = await turn(doctor, message)
    final(events)
    sent = json.dumps(llm_calls())
    for secret in ("Johanna", "Mustermann", "03.04.2019", "88812345", "1234567"):
        assert secret not in sent
    assert "STXBP1" in sent
    detail = (await doctor.client.get(f"/chat/sessions/{events[-1]['session_id']}")).json()
    stored = json.dumps(detail)
    assert "Mustermann" not in stored and "88812345" not in stored
    assert "STXBP1" in detail["messages"][0]["content"]


async def test_tool_loop_with_mock(doctor, user_llm, llm_calls):
    events = await turn(doctor, "STXBP1 encephalopathy and seizures")
    types = [e["type"] for e in events]
    tools = [e.get("tool") for e in events if e["type"] == "status" and e.get("tool")]
    assert tools[:3] == ["extract_entities", "resolve_to_ids", "search_graph"]
    first_delta = types.index("summary_delta")
    assert all(t == "status" for t in types[:first_delta])
    tail = [t for t in types[first_delta:] if t != "summary_delta"]
    assert tail == [t for t in EVENT_ORDER if t in tail]
    reply = final(events)
    deltas = "".join(e["text"] for e in events if e["type"] == "summary_delta")
    assert deltas == reply["summary"]
    store = get_graph()
    assert all(e in store.edges for c in reply["claims"] for e in c["edge_ids"])
    assert reply["chips"] and all(c["confirmed"] is False for c in reply["chips"])
    bodies = llm_calls()
    assert all(b["store"] is False and b["stream"] is True for b in bodies)
    assert any("Dr. Henry Wu" in (b.get("instructions") or "") for b in bodies)


async def test_uncited_claim_removed(doctor, user_llm):
    outside = DEMO["path_edge_ids"][2]  # real edge, not returned by any tool this turn
    good = observed_edge(STXBP1)
    user_llm.enqueue(
        neighborhood(STXBP1),
        {
            "json": draft(
                claims=[
                    claim("Invented link.", ["e_ffffffffffff"]),
                    claim("Real but not from tools.", [outside]),
                    claim("No citation.", []),
                    claim("Backed by the graph.", [good]),
                ],
                contradictions=[{"claim_index": 3, "edge_ids": [good], "note": "x"}],
            )
        },
    )
    reply = final(await turn(doctor, "STXBP1 encephalopathy"))
    assert [c["text"] for c in reply["claims"]] == ["Backed by the graph."]
    assert all(c["claim_index"] == 0 for c in reply["contradictions"])


async def test_origin_and_confidence_recomputed(doctor, user_llm):
    user_llm.enqueue(
        neighborhood(STXBP1),
        {
            "json": draft(
                claims=[
                    claim("Similar symptoms.", [SIMILAR], "observed", "low"),
                    claim("Shared pathway.", [LOW], "observed", "high"),
                ]
            )
        },
    )
    reply = final(await turn(doctor, "STXBP1 encephalopathy"))
    by_text = {c["text"]: c for c in reply["claims"]}
    assert by_text["Similar symptoms."]["origin"] == "inferred"
    assert by_text["Similar symptoms."]["confidence"] == "high"
    assert by_text["Shared pathway."]["origin"] == "inferred"
    assert by_text["Shared pathway."]["confidence"] == "low"


async def test_contradiction_added(doctor, user_llm):
    user_llm.enqueue(
        neighborhood(SCN2A_LOF),
        {"json": draft(claims=[claim("Seizures are part of it.", [CONTRADICTED])])},
    )
    reply = final(await turn(doctor, "SCN2A loss of function"))
    assert reply["claims"][0]["edge_ids"] == [CONTRADICTED]
    assert reply["contradictions"] and reply["contradictions"][0]["edge_ids"] == [CONTRADICTED]
    assert reply["contradictions"][0]["claim_index"] == 0


async def test_action_viability(doctor, user_llm):
    good = observed_edge(STXBP1)
    user_llm.enqueue(
        neighborhood(STXBP1),
        {
            "json": draft(
                actions=[
                    action("Join via a hypothesis", [SIMILAR], viable=True),
                    action("Reuse the group's work", [good], viable=True),
                    action("Made up", ["e_ffffffffffff"]),
                ]
            )
        },
    )
    reply = final(await turn(doctor, "STXBP1 encephalopathy"))
    by_title = {a["title"]: a for a in reply["actions"]}
    assert set(by_title) == {"Join via a hypothesis", "Reuse the group's work"}
    assert by_title["Join via a hypothesis"]["viable"] is False
    assert by_title["Reuse the group's work"]["viable"] is True
    assert reply["actions"][0]["viable"] is True  # viable leads first


async def test_diagnosis_declined_with_graph_context(doctor, user_llm, llm_calls):
    good = observed_edge(STXBP1)
    user_llm.enqueue(
        neighborhood(STXBP1),
        {
            "json": draft(
                summary="Your daughter has STXBP1 encephalopathy. Groups exist.",
                claims=[claim("A patient group exists.", [good])],
            )
        },
    )
    reply = final(await turn(doctor, "Does my daughter have STXBP1 encephalopathy?"))
    assert reply["summary"].startswith("I can't say if this is the diagnosis")
    assert "Your daughter has" not in reply["summary"]
    assert reply["claims"]
    assert "Do not answer that part" in llm_calls()[0]["instructions"]


async def test_treatment_statement_removed(doctor, user_llm):
    good = observed_edge(STXBP1)
    user_llm.enqueue(
        neighborhood(STXBP1),
        {
            "json": draft(
                summary="You should start stiripentol at 50 mg/kg. A group exists.",
                claims=[claim("A patient group exists.", [good])],
            )
        },
    )
    reply = final(await turn(doctor, "Tell me about STXBP1 encephalopathy"))
    assert "stiripentol" not in reply["summary"] and "mg" not in reply["summary"]
    assert reply["summary"].startswith("I can't choose a treatment")


async def test_followup_limited_to_one(doctor, user_llm, llm_calls):
    ask = {
        "name": "ask_followup",
        "arguments": {"candidate_cluster_ids": ["CLUSTER:1", "CLUSTER:2", "CLUSTER:3"]},
    }
    user_llm.enqueue(
        {"tool_calls": [ask, ask]},
        {"json": draft()},
    )
    reply = final(await turn(doctor, "Which cluster fits?"))
    assert reply["follow_up"] is not None
    assert reply["follow_up"]["skippable"] is True
    assert reply["follow_up"]["question"].startswith("Have you noticed signs of")
    outputs = [
        i["output"] for i in llm_calls()[-1]["input"] if i.get("type") == "function_call_output"
    ]
    assert len(outputs) == 2 and "already chosen" in outputs[1]


async def test_followup_dropped_without_tool(doctor, user_llm):
    user_llm.enqueue(
        {"json": draft(follow_up={"question": "Q?", "quick_replies": ["a"], "skippable": False})}
    )
    reply = final(await turn(doctor, "Hello"))
    assert reply["follow_up"] is None


async def test_tool_call_cap(doctor, user_llm, llm_calls):
    user_llm.enqueue(*[neighborhood(STXBP1)] * 10, {"json": draft()})
    final(await turn(doctor, "STXBP1 encephalopathy"))
    outputs = [
        i["output"] for i in llm_calls()[-1]["input"] if i.get("type") == "function_call_output"
    ]
    assert len(outputs) == 10
    assert sum("budget exhausted" in o for o in outputs) == 2


async def test_turn_timeout(doctor, user_llm, monkeypatch):
    from backend.api.services.chat import agent

    monkeypatch.setattr(agent, "TURN_DEADLINE_S", 0.3)
    user_llm.configure(stream_delay_s=0.2)
    events = await turn(doctor, "STXBP1 encephalopathy")
    assert events[-1]["type"] == "error" and events[-1]["code"] == "upstream_error"
    assert "too long" in events[-1]["message"]


async def test_usage_limit_error(doctor, user_llm):
    user_llm.configure(fail_mode="usage_limit")
    events = await turn(doctor, "STXBP1 encephalopathy")
    assert events[-1] == {
        "type": "error",
        "code": "rate_limited",
        "message": "Your ChatGPT plan's usage limit is reached. Please try again later.",
    }


async def test_no_supported_route(doctor, user_llm):
    route = DEMO["no_supported_route"]
    user_llm.enqueue(
        {
            "tool_calls": [
                {"name": "find_path", "arguments": {"from_id": route["from"], "to_id": route["to"]}}
            ]
        },
        {"json": draft(summary="Here is what I found.")},
    )
    reply = final(await turn(doctor, "How is SYNGAP1 linked to Dravet?"))
    assert reply["summary"].startswith("I found no supported route between"), reply
    assert reply["gap_search"] == {"from_id": route["from"], "to_id": route["to"], "family": "all"}
    assert reply["uncertainty"]
    assert any("gap search" in m.lower() for m in reply["missing_evidence"])


async def test_vus_notice(doctor, user_llm):
    store = get_graph()
    vus_edge = next(
        e for e in store.edges.values() if DEMO["vus_variant_id"] in (e.source_id, e.target_id)
    )
    user_llm.enqueue(
        neighborhood(DEMO["vus_variant_id"]),
        {"json": draft(claims=[claim("The variant is in STXBP1.", [vus_edge.id])])},
    )
    reply = final(await turn(doctor, "What about my STXBP1 variant?"))
    assert VUS_NOTICE in reply["summary"]


async def test_patient_summary_reading_gate(make_user, user_llm, llm_calls):
    user = await make_user(role="patient")
    hard = (
        "Heterogeneous electrophysiological characterization demonstrates pathophysiologically "
        "distinct neurodevelopmental manifestations across voltage-gated channelopathies."
    )
    user_llm.enqueue({"json": draft(summary=hard)}, {"text": "These conditions can look alike."})
    reply = final(await turn(user, "Tell me about channel diseases"))
    assert reply["summary"] == "These conditions can look alike."
    assert "grade 8" in llm_calls()[-1]["instructions"]


async def test_sessions_persist_and_are_isolated(make_user, user_llm, llm_calls):
    alice = await make_user(role="doctor")
    bob = await make_user(role="doctor")
    user_llm.enqueue({"json": draft(summary="First answer.")})
    events = await turn(alice, "STXBP1 encephalopathy")
    sid = events[-1]["session_id"]
    user_llm.enqueue({"json": draft(summary="Second answer.")})
    events2 = await turn(alice, "And the registry?", session_id=sid)
    assert events2[-1]["session_id"] == sid
    second_input = llm_calls()[-1]["input"]
    assert [i["content"] for i in second_input if i.get("role") == "assistant"] == ["First answer."]

    sessions = (await alice.client.get("/chat/sessions")).json()
    assert [s["id"] for s in sessions] == [sid]
    detail = (await alice.client.get(f"/chat/sessions/{sid}")).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"] * 2
    assert detail["messages"][1]["reply"]["summary"] == "First answer."

    assert (await bob.client.get("/chat/sessions")).json() == []
    assert (await bob.client.get(f"/chat/sessions/{sid}")).status_code == 404
    assert (await bob.client.delete(f"/chat/sessions/{sid}")).status_code == 404
    resp = await bob.client.post("/chat", json={"message": "hi", "session_id": sid})
    assert resp.status_code == 404

    assert (await alice.client.delete(f"/chat/sessions/{sid}")).status_code == 204
    assert (await alice.client.get(f"/chat/sessions/{sid}")).status_code == 404
