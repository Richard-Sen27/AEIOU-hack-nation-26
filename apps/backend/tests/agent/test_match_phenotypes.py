"""Dr. Wu ranks conditions by symptom overlap for a symptoms-only message: match_phenotypes runs
before the first model round (no extra model call), its has_phenotype edges are citable, and the
reply stays an overlap ranking, never a diagnosis."""

import json
import re

import pytest
from agent_helpers import post_sse

from backend.api.services import phenotype_match
from backend.api.services.chat import postcheck
from backend.api.services.chat.tools import (
    Extraction,
    Mention,
    TurnState,
    match_phenotypes,
    symptoms_only,
)
from backend.api.services.graph import get_graph
from backend.schemas.chat import stored_reply
from backend.schemas.common import Lens
from backend.schemas.enums import Role
from backend.schemas.profile import PatientProfile

MESSAGE = "My son has seizures, hypotonia and a developmental delay. No feeding problems."


@pytest.fixture
async def patient(make_user, user_llm):
    phenotype_match.set_terms(None)  # the fixture has no term table: phenotype nodes stand in
    return await make_user(role="patient", consents=["health_data"])


async def _turn(user, message: str) -> list[dict]:
    status, events = await post_sse(user.client, "/chat", {"message": message})
    assert status == 200, events
    return events


def _context(body: dict) -> list[str]:
    return [i["content"] for i in body["input"] if i.get("role") == "developer"]


def _match_result(content: str) -> dict:
    return json.loads(re.sub(r"^<tool_result[^>]*>|</tool_result>$", "", content))


async def test_symptoms_only_turn_ranks_before_the_first_round(patient, llm_calls):
    events = await _turn(patient, MESSAGE)
    bodies = llm_calls()
    assert bodies[0].get("text", {}).get("format", {}).get("name") == "Extraction"
    rounds = [b for b in bodies[1:] if b.get("tools")]
    context = _context(rounds[0])
    assert [c.split('"')[1] for c in context] == ["resolve_to_ids", "match_phenotypes"]
    result = _match_result(context[1])
    assert {r["label"] for r in result["resolved"]} >= {"Seizure", "Hypotonia"}
    assert any(r["absent"] and r["label"] == "Feeding difficulties" for r in result["resolved"])
    top = result["results"][0]
    assert top["overlap"] >= 2 and top["shared"] and "probability" in result["note"]
    tools = [e.get("tool") for e in events if e["type"] == "status" and e.get("tool")]
    assert tools[:3] == ["extract_entities", "resolve_to_ids", "match_phenotypes"]
    assert "not a diagnosis" in events[-1]["reply"]["summary"]


async def test_ranking_answers_in_the_first_round_with_citable_edges(patient, user_llm, llm_calls):
    """The model can answer from the ranking at once: one tool-enabled call, and the
    has_phenotype edges it cites survive the post-check."""
    state = TurnState(lens=Lens(role=Role.patient), message="", profile=PatientProfile())
    expected = match_phenotypes(
        state, ["Seizure", "Hypotonia", "Global developmental delay"], ["Feeding difficulties"]
    )
    top = expected["results"][0]
    eids = [s["edge_id"] for s in top["shared"]]
    text = (
        f"{top['label']} is a condition in the atlas whose recorded symptoms overlap: "
        f"{top['overlap']} of your {top['of']} symptoms are recorded for it."
    )
    user_llm.enqueue(
        {
            "kind": "tools",
            "json": {
                "summary": "Some conditions in the atlas have recorded symptoms that overlap.",
                "uncertainty": None,
                "claims": [
                    {"text": text, "edge_ids": eids, "origin": "observed", "confidence": "high"}
                ],
                "contradictions": [],
                "missing_evidence": [],
                "cards": [{"type": "open_in_atlas", "node_ids": [top["id"]], "edge_ids": []}],
                "graph_focus": None,
                "actions": [],
                "follow_up": None,
            },
        }
    )
    reply = (await _turn(patient, MESSAGE))[-1]["reply"]
    assert len([b for b in llm_calls() if b.get("tools")]) == 1
    assert [c["edge_ids"] for c in reply["claims"]] == [eids]
    assert all(get_graph().edges[e].relation == "has_phenotype" for e in eids)
    assert reply["cards"][0]["node_ids"] == [top["id"]]
    assert "not a diagnosis" in reply["summary"]


async def test_disease_message_does_not_rank_symptoms(patient, llm_calls):
    events = await _turn(patient, "STXBP1 encephalopathy with seizures")
    rounds = [b for b in llm_calls() if b.get("tools")]
    context = _context(rounds[0])
    assert len(context) == 1 and context[0].startswith('<tool_result name="resolve_to_ids">')
    assert events[-1]["reply"]["symptom_match"] is None


def _ranking() -> dict:
    state = TurnState(lens=Lens(role=Role.patient), message="", profile=PatientProfile())
    return match_phenotypes(
        state, ["Seizure", "Hypotonia", "Global developmental delay"], ["Feeding difficulties"]
    )


async def test_symptoms_only_reply_carries_the_ranking_as_stored(patient, llm_calls):
    """The ranking reaches the reply in code (whatever the model wrote): the top conditions in
    the tool's order with their overlap counts, each shared or contradicting symptom backed by
    a has_phenotype edge of that condition; the stored reply is the same."""
    events = await _turn(patient, MESSAGE)
    final = events[-1]
    match = final["reply"]["symptom_match"]
    expected = _ranking()["results"]
    assert match is not None and 1 <= len(match["items"]) <= postcheck.MAX_RANKED
    assert [i["id"] for i in match["items"]] == [r["id"] for r in expected][: len(match["items"])]
    edges = get_graph().edges
    for item, result in zip(match["items"], expected, strict=False):
        assert (item["label"], item["overlap"], item["of"]) == (
            result["label"],
            result["overlap"],
            result["of"],
        )
        assert item["on_map"] is True  # fixture nodes carry no tier: all on the map
        assert item["shared"]
        for term in item["shared"] + item["absent"]:
            edge = edges[term["edge_id"]]
            assert edge.relation == "has_phenotype" and edge.source_id == item["id"]
        assert "score" not in item  # an overlap count only, no similarity number
        assert [t["edge_id"] for t in item["absent"]] == [
            t["edge_id"] for t in result.get("recorded_but_absent_for_user", [])
        ]
    detail = (await patient.client.get(f"/chat/sessions/{final['session_id']}")).json()
    stored = detail["messages"][-1]["reply"]
    assert stored["symptom_match"] == match


async def test_postcheck_still_enforces_the_rules_on_a_ranking_turn(patient, user_llm):
    """Diagnosis and probability wording is removed, an uncited claim is dropped, the
    geneticist line is added; the ranking card stays, built from the tool's edges only."""
    top = _ranking()["results"][0]
    eids = [s["edge_id"] for s in top["shared"]]
    label = top["label"]
    user_llm.enqueue(
        {
            "kind": "tools",
            "json": {
                "summary": f"Your son has {label}. There is an 80% chance it is {label}.",
                "uncertainty": None,
                "claims": [
                    {
                        "text": f"{top['overlap']} of your {top['of']} symptoms are recorded for "
                        f"{label}.",
                        "edge_ids": eids,
                        "origin": "observed",
                        "confidence": "high",
                    },
                    {
                        "text": f"The probability that your son has {label} is high.",
                        "edge_ids": eids,
                        "origin": "observed",
                        "confidence": "high",
                    },
                    {
                        "text": f"{label} explains these symptoms.",
                        "edge_ids": ["e_not_from_a_tool"],
                        "origin": "observed",
                        "confidence": "high",
                    },
                ],
                "contradictions": [],
                "missing_evidence": [],
                "cards": [],
                "graph_focus": None,
                "actions": [],
                "follow_up": None,
            },
        }
    )
    reply = (await _turn(patient, MESSAGE))[-1]["reply"]
    assert [c["edge_ids"] for c in reply["claims"]] == [eids]
    assert reply["kind"] == "declined"
    summary = reply["summary"]
    assert "80%" not in summary and f"has {label}" not in summary
    assert "not a diagnosis" in summary
    match = reply["symptom_match"]
    assert match["items"][0]["id"] == top["id"]
    assert {t["edge_id"] for t in match["items"][0]["shared"]} <= set(eids)


def test_ranking_keeps_only_cited_has_phenotype_links():
    """symptom_match drops terms whose edge the turn did not return, and conditions left
    without a shared symptom; at most MAX_RANKED conditions."""
    state = TurnState(lens=Lens(role=Role.patient), message="", profile=PatientProfile())
    result = match_phenotypes(state, ["Seizure", "Hypotonia", "Global developmental delay"], [])
    edges = {e: get_graph().edges[e] for e in state.edge_ids}
    full = postcheck.symptom_match(state, edges)
    assert full is not None and len(full.items) == min(postcheck.MAX_RANKED, len(result["results"]))
    first = result["results"][0]
    dropped = {s["edge_id"] for s in first["shared"]}
    partial = postcheck.symptom_match(state, {k: v for k, v in edges.items() if k not in dropped})
    assert partial is None or first["id"] not in [i.id for i in partial.items]
    empty = TurnState(lens=Lens(), message="", profile=PatientProfile())
    assert postcheck.symptom_match(empty, {}) is None


def test_replies_stored_before_the_ranking_still_load():
    old = {
        "summary": "Hi.",
        "uncertainty": None,
        "chips": [],
        "claims": [],
        "contradictions": [],
        "missing_evidence": [],
        "cards": [],
        "graph_focus": None,
        "actions": [],
        "follow_up": None,
    }
    reply, failure = stored_reply(old)
    assert failure is None and reply is not None and reply.symptom_match is None


def test_symptoms_only_rule():
    def ex(**fields) -> Extraction:
        base = {
            "diseases": [],
            "genes": [],
            "variants": [],
            "symptoms": [],
            "age_years": None,
            "onset": None,
            "country": None,
        }
        return Extraction(**{**base, **fields})

    seizure = Mention(text="seizures", english="Seizure", negated=False)
    no_fever = Mention(text="no fever", english="Fever", negated=True)
    assert symptoms_only(ex(symptoms=[seizure, no_fever]))
    assert not symptoms_only(ex(symptoms=[no_fever]))
    assert not symptoms_only(ex(symptoms=[seizure], genes=[Mention(text="SCN1A", negated=False)]))
