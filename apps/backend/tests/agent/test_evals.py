import io

import yaml

from backend.api.services.graph import get_graph
from backend.evals import runner
from backend.evals.runner import RecordingTracer, resolve_label, run_eval
from backend.schemas.enums import Origin, Relation

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
        {"json": draft([])},
        {"tool_calls": [{"name": "get_neighborhood", "arguments": {"node_id": DRAVET}}]},
        {
            "json": draft(
                [
                    {
                        "text": "These have similar signs.",
                        "edge_ids": [inferred.id],
                        "origin": "observed",  # the post-check must correct this
                        "confidence": "high",
                    }
                ]
            )
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


async def test_labels_resolve_on_fixture(app):
    assert resolve_label("Dravet syndrome") == ["MONDO:0100135"]
    assert resolve_label("STXBP1")
    assert resolve_label("no such thing") == []
