import io

from backend.evals.runner import RecordingTracer, resolve_label, run_eval


async def test_eval_harness_on_mock(app, mock_llm):
    out = io.StringIO()
    checks = await run_eval(
        mock_llm, only=["refusal", "citations", "inference"], mock=True, out=out
    )
    by_name = {c.name: c for c in checks}
    assert by_name["refusal"].ok and by_name["refusal"].total == 5
    assert by_name["citations"].ok and by_name["inference"].ok
    assert "PASS refusal" in out.getvalue()
    assert isinstance(mock_llm.tracer, RecordingTracer) and mock_llm.tracer.records


async def test_labels_resolve_on_fixture(app):
    assert resolve_label("Dravet syndrome") == ["MONDO:0100135"]
    assert resolve_label("STXBP1")
    assert resolve_label("no such thing") == []
