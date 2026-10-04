import io

import yaml

from backend.api.services import phenotype_match
from backend.api.services.chat.agent import TurnResult
from backend.api.services.chat.postcheck import symptom_match
from backend.api.services.chat.tools import TurnState, match_phenotypes
from backend.api.services.graph import get_graph
from backend.evals import runner
from backend.evals.runner import RecordingTracer, resolve_label, run_eval, symptom_failures
from backend.schemas.chat import AgentReply, Claim
from backend.schemas.common import Lens
from backend.schemas.enums import Origin, Relation, Role
from backend.schemas.profile import PatientProfile

DRAVET = "MONDO:0100135"


def draft(claims: list[dict]) -> dict:
    return {
        "summary": "Two groups share some signs.",
        "uncertainty": None,
        "claims": claims,
        "contradictions": [],
        "missing_evidence": [],
        "cards": [],
        "graph_focus": None,
        "actions": [],
        "follow_up": None,
    }


async def test_eval_harness_on_mock(app, mock_llm):
    out = io.StringIO()
    checks = await run_eval(
        mock_llm, only=["refusal", "citations", "inference"], mock=True, out=out
    )
    by_name = {c.name: c for c in checks}
    assert by_name["refusal"].ok and by_name["refusal"].total == 5
    assert by_name["citations"].ok
    # The unscripted mock never cites an inferred edge, so the check must not pass vacuously.
    inference = by_name["inference"]
    assert inference.total == 0
    assert not inference.ok and "vacuously" in inference.failures[0]
    assert not inference.gating  # informational on the mock only
    assert "PASS refusal" in out.getvalue()
    assert isinstance(mock_llm.tracer, RecordingTracer) and mock_llm.tracer.records


async def test_inference_seeds_and_unresolved_labels(
    app, mock_llm, mock_openai_env, tmp_path, monkeypatch
):
    store = get_graph()
    inferred = next(
        e
        for eid in sorted(store.incident[DRAVET])
        if (e := store.edges[eid]).relation == Relation.similar_symptoms
        and e.origin == Origin.inferred
    )
    spec = yaml.safe_load(runner.GOLDEN_PATH.read_text())
    spec["questions"] = [
        {"persona": "test", "role": "patient", "expect": ["No such disease"], "question": "Hi?"}
    ]
    spec["inference_questions"] = [
        q for q in spec["inference_questions"] if q["relation"] == "similar_symptoms"
    ]
    path = tmp_path / "golden.yaml"
    path.write_text(yaml.safe_dump(spec))
    monkeypatch.setattr(runner, "GOLDEN_PATH", path)
    mock_openai_env.enqueue(
        {"kind": "tools", "json": draft([])},
        {
            "kind": "tools",
            "tool_calls": [{"name": "get_neighborhood", "arguments": {"node_id": DRAVET}}],
        },
        {
            "kind": "tools",
            "json": draft(
                [
                    {
                        "text": "These have similar signs.",
                        "edge_ids": [inferred.id],
                        "origin": "observed",  # the post-check must correct this
                        "confidence": "high",
                    }
                ]
            ),
        },
    )
    out = io.StringIO()
    checks = await run_eval(mock_llm, only=["golden", "inference"], mock=True, out=out)
    by_name = {c.name: c for c in checks}
    golden = by_name["golden"]
    assert golden.total == 1 and golden.passed == 0
    assert golden.unresolved == ["test: No such disease"]
    assert "not in graph: test: No such disease" in out.getvalue()
    inference = by_name["inference"]
    assert inference.ok and inference.total == 1 and inference.passed == 1


async def test_inference_questions_target_inferred_relations(app):
    spec = yaml.safe_load(runner.GOLDEN_PATH.read_text())
    relations = {q["relation"] for q in spec["inference_questions"]}
    assert relations == {"similar_symptoms", "shared_pathway", "same_gene_same_mechanism"}
    for q in spec["inference_questions"]:
        for label in q["expect"]:
            assert runner.has_inferred(resolve_label(label), Relation(q["relation"]))


SYMPTOMS = "My son has seizures, hypotonia and a developmental delay."


def _symptom_spec(tmp_path, monkeypatch, expect: list[str]) -> None:
    spec = yaml.safe_load(runner.GOLDEN_PATH.read_text())
    spec["symptom_questions"] = [{"role": "patient", "expect_any": expect, "question": SYMPTOMS}]
    path = tmp_path / "golden.yaml"
    path.write_text(yaml.safe_dump(spec))
    monkeypatch.setattr(runner, "GOLDEN_PATH", path)


def _top_ranked() -> dict:
    state = TurnState(lens=Lens(role=Role.patient), message="", profile=PatientProfile())
    return match_phenotypes(state, ["Seizure", "Hypotonia", "Global developmental delay"], [])[
        "results"
    ][0]


async def test_symptoms_check_passes_a_cited_overlap_answer(
    app, mock_llm, mock_openai_env, tmp_path, monkeypatch
):
    phenotype_match.set_terms(None)  # the fixture has no term table
    top = _top_ranked()
    _symptom_spec(tmp_path, monkeypatch, [top["label"]])
    eids = [s["edge_id"] for s in top["shared"]]
    claim = {
        "text": f"{top['overlap']} of your {top['of']} symptoms are recorded for {top['label']}.",
        "edge_ids": eids,
        "origin": "observed",
        "confidence": "high",
    }
    mock_openai_env.enqueue({"kind": "tools", "json": draft([claim])})
    out = io.StringIO()
    checks = await run_eval(mock_llm, only=["symptoms"], mock=True, out=out)
    symptoms = checks[0]
    assert symptoms.name == "symptoms" and symptoms.total == 1
    assert symptoms.ok and symptoms.passed == 1, symptoms.failures


async def test_symptoms_check_fails_without_citations_or_with_a_percentage(
    app, mock_llm, mock_openai_env, tmp_path, monkeypatch
):
    phenotype_match.set_terms(None)
    top = _top_ranked()
    _symptom_spec(tmp_path, monkeypatch, [top["label"]])
    mock_openai_env.enqueue({"kind": "tools", "json": draft([])})
    checks = await run_eval(mock_llm, only=["symptoms"], mock=True, out=io.StringIO())
    assert checks[0].passed == 0
    assert "no claim cites a has_phenotype edge" in checks[0].failures[0]
    assert not checks[0].gating  # informational on the mock only


def test_symptom_failures_flag_probability_wording(app):
    phenotype_match.set_terms(None)
    state = TurnState(lens=Lens(role=Role.patient), message="", profile=PatientProfile())
    match_phenotypes(state, ["Seizure", "Hypotonia"], [])
    edges = {e: get_graph().edges[e] for e in state.edge_ids}
    ranking = symptom_match(state, edges)
    assert ranking is not None
    item = ranking.items[0]
    reply = AgentReply(
        summary="About 70% of your symptoms are recorded for it.",
        uncertainty=None,
        chips=[],
        claims=[
            Claim(
                text="Recorded for it.",
                edge_ids=[item.shared[0].edge_id],
                origin=Origin.observed,
                confidence="high",
            )
        ],
        contradictions=[],
        missing_evidence=[],
        cards=[],
        graph_focus=None,
        actions=[],
        follow_up=None,
        symptom_match=ranking,
    )
    failures = symptom_failures(TurnResult(reply=reply), {item.id})
    assert failures == ["overlap worded as a probability or percentage"]
    unranked = reply.model_copy(update={"symptom_match": None})
    assert symptom_failures(TurnResult(reply=unranked), set()) == [
        "no symptom-overlap ranking (match_phenotypes not used)"
    ]


async def test_chronic_cough_case_is_in_the_golden_file(app):
    spec = yaml.safe_load(runner.GOLDEN_PATH.read_text())
    (case,) = spec["symptom_questions"]
    assert "chronic cough" in case["question"].lower()
    assert "primary ciliary dyskinesia 25" in case["expect_any"]


async def test_labels_resolve_on_fixture(app):
    assert resolve_label("Dravet syndrome") == ["MONDO:0100135"]
    assert resolve_label("STXBP1")
    assert resolve_label("no such thing") == []
