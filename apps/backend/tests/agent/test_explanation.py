import io
import json

from agent_helpers import DEMO, post_sse
from sqlalchemy import text

from backend.api.services.explanation.common import reading_grade
from backend.api.services.explanation.pathdata import load_path_data
from backend.api.services.explanation.templates import template_explanation
from backend.db.session import user_transaction
from backend.schemas.enums import VUS_NOTICE, Role, path_id

COUNTEREXAMPLE = DEMO["counterexample_edge_id"]  # inferred, same gene different mechanism
CONTRADICTED = DEMO["contradicted_edge_id"]
PENDING = DEMO["pending_review_edge_id"]

COMPLEX = (
    "The heterogeneous electrophysiological characterization of voltage-gated sodium channel "
    "dysfunction demonstrates that pathophysiologically distinct gain-of-function and "
    "loss-of-function mechanisms possibly produce divergent neurodevelopmental "
    f"manifestations [{COUNTEREXAMPLE}]."
)
SIMPLE = (
    f"These two conditions may share one gene [{COUNTEREXAMPLE}]. "
    f"The gene may work in a different way in each [{COUNTEREXAMPLE}]."
)


async def test_cached_replay_for_guest(client):
    status, events = await post_sse(
        client, "/explain", {"edge_ids": DEMO["path_edge_ids"], "role": "guest"}
    )
    assert status == 200
    assert [e["type"] for e in events][-1] == "final"
    final = events[-1]
    assert final["cached"] is True and final["path_id"] == DEMO["path_id"]
    assert "".join(e["text"] for e in events[:-1]) == final["text"]
    assert set(final["citations"]) <= set(DEMO["path_edge_ids"])


async def test_guest_without_cache_gets_401(client):
    resp = await client.post("/explain", json={"edge_ids": [COUNTEREXAMPLE], "role": "guest"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "sign_in_required"


async def test_unconfirmed_age_gets_403_unless_cached(make_user, user_llm):
    user = await make_user(role="patient", age_confirmed=False)
    resp = await user.client.post("/explain", json={"edge_ids": [COUNTEREXAMPLE, PENDING]})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "age_confirmation_required"
    status, events = await post_sse(
        user.client, "/explain", {"edge_ids": DEMO["path_edge_ids"], "role": "guest"}
    )
    assert status == 200 and events[-1]["cached"] is True


async def test_unknown_edge_404(make_user, user_llm):
    user = await make_user(role="patient")
    resp = await user.client.post("/explain", json={"edge_ids": ["e_ffffffffffff"]})
    assert resp.status_code == 404


async def test_invalid_citation_is_regenerated_and_cached(make_user, user_llm, llm_calls, client):
    user = await make_user(role="patient")
    user_llm.enqueue(
        {"text": "These diseases share a gene [e_ffffffffffff]."},
        {"text": SIMPLE},
    )
    status, events = await post_sse(user.client, "/explain", {"edge_ids": [COUNTEREXAMPLE]})
    assert status == 200, events
    final = events[-1]
    assert final["type"] == "final" and final["cached"] is False
    assert final["citations"] == [COUNTEREXAMPLE]
    assert "e_ffffffffffff" not in final["text"]
    bodies = llm_calls()
    assert len(bodies) == 2
    feedback = bodies[1]["input"][-1]["content"]
    assert "e_ffffffffffff" in feedback and "not part of this path" in feedback
    assert bodies[0]["store"] is False and bodies[0]["stream"] is True
    assert "temperature" not in bodies[0]

    # cache write + hit: a guest now gets the patient-lens text from the cache
    status, events = await post_sse(
        client, "/explain", {"edge_ids": [COUNTEREXAMPLE], "role": "patient"}
    )
    assert status == 200 and events[-1]["cached"] is True
    assert events[-1]["text"] == final["text"]
    async with user_transaction(None) as db:
        n = await db.scalar(
            text("SELECT count(*) FROM explanations_cache WHERE path_id = :p AND role = 'patient'"),
            {"p": path_id([COUNTEREXAMPLE])},
        )
    assert n == 1


async def test_reading_level_regeneration(make_user, user_llm, llm_calls):
    user = await make_user(role="patient")
    assert reading_grade(COMPLEX, "en") > 8
    user_llm.enqueue({"text": COMPLEX}, {"text": SIMPLE})
    status, events = await post_sse(
        user.client, "/explain", {"edge_ids": [COUNTEREXAMPLE], "language": "en-GB"}
    )
    assert status == 200
    final = events[-1]
    assert final["reading_grade"] is not None and final["reading_grade"] <= 8
    bodies = llm_calls()
    assert len(bodies) == 2
    assert "simpler" in bodies[1]["input"][-1]["content"]


async def test_citation_failure_gives_error_event(make_user, user_llm):
    user = await make_user(role="doctor")
    user_llm.enqueue(*[{"text": "No citations here at all."}] * 3)
    status, events = await post_sse(user.client, "/explain", {"edge_ids": [CONTRADICTED]})
    assert status == 200
    assert events[-1]["type"] == "error" and events[-1]["code"] == "upstream_error"


async def test_trust_rules_appended(make_user, user_llm):
    user = await make_user(role="researcher")
    user_llm.enqueue(
        {"text": f"Seizures occur here [{CONTRADICTED}]. A user link exists [{PENDING}]."}
    )
    status, events = await post_sse(user.client, "/explain", {"edge_ids": [CONTRADICTED, PENDING]})
    final = events[-1]
    assert final["type"] == "final", events
    assert f"Some sources contradict the link [{CONTRADICTED}]" in final["text"]
    assert f"The link [{PENDING}] is under review" in final["text"]
    assert f"The link [{PENDING}] was reported by users" in final["text"]


async def test_llm_usage_limit_maps_to_error(make_user, user_llm):
    user = await make_user(role="patient")
    user_llm.configure(fail_mode="usage_limit")
    status, events = await post_sse(user.client, "/explain", {"edge_ids": [PENDING]})
    assert events[-1]["type"] == "error" and events[-1]["code"] == "rate_limited"


async def test_template_wording(app):
    async with user_transaction(None) as db:
        data = await load_path_data(db, [COUNTEREXAMPLE, CONTRADICTED, PENDING])
    out = template_explanation(data, Role.patient, "en")
    assert f"[{COUNTEREXAMPLE}]" in out and "hypothesis" in out
    assert "under review" in out and "contradict" in out
    de = template_explanation(data, Role.patient, "de")
    assert "Hypothese" in de


async def test_template_vus_notice(app):
    from backend.api.services.graph import get_graph

    store = get_graph()
    vus_edge = next(
        e.id for e in store.edges.values() if DEMO["vus_variant_id"] in (e.source_id, e.target_id)
    )
    async with user_transaction(None) as db:
        data = await load_path_data(db, [vus_edge])
    assert VUS_NOTICE in template_explanation(data, Role.guest, "en")


async def test_cli_precompute_template_fallback(app):
    from backend.cli import precompute_explanations, select_demo_paths

    paths = select_demo_paths(3)
    assert paths and all(p.supported for p in paths)
    out = io.StringIO()
    first = await precompute_explanations(["en", "de"], limit=3, use_llm=False, out=out)
    assert "template mode" in out.getvalue()
    assert first.paths == len(paths) and first.model == 0
    assert first.template + first.skipped == len(paths) * 4 * 2
    async with user_transaction(None) as db:
        rows = (
            await db.execute(
                text("SELECT role, language, citations FROM explanations_cache WHERE path_id = :p"),
                {"p": paths[0].path_id},
            )
        ).all()
    roles = ("guest", "patient", "doctor", "researcher")
    expected = {(r, lang) for r in roles for lang in ("en", "de")}
    assert {(r.role, r.language) for r in rows} >= expected
    second = await precompute_explanations(["en", "de"], limit=3, use_llm=False, out=io.StringIO())
    assert second.template == 0 and second.skipped == len(paths) * 4 * 2


COMPLEX_DE = (
    "Die heterogene elektrophysiologische Charakterisierung spannungsabhängiger "
    "Natriumkanalfunktionsstörungen demonstriert pathophysiologisch unterschiedliche "
    f"Funktionsgewinn- und Funktionsverlustmechanismen [{COUNTEREXAMPLE}]."
)
SIMPLE_DE = (
    f"Diese zwei Leiden haben wohl ein Gen gemeinsam [{COUNTEREXAMPLE}]. "
    f"Das Gen wirkt bei jedem anders [{COUNTEREXAMPLE}]."
)


def test_reading_grade_languages():
    assert reading_grade(COMPLEX_DE, "de") > reading_grade(SIMPLE_DE, "de-AT")
    assert reading_grade(SIMPLE_DE, "de") is not None
    # textstat has no calibrated grade formula for these: no gate.
    assert reading_grade("Ces deux maladies partagent un gène.", "fr") is None


async def test_reading_level_regeneration_german(make_user, user_llm, llm_calls):
    user = await make_user(role="patient")
    user_llm.enqueue({"text": COMPLEX_DE}, {"text": SIMPLE_DE})
    status, events = await post_sse(
        user.client, "/explain", {"edge_ids": [COUNTEREXAMPLE], "language": "de"}
    )
    assert status == 200, events
    final = events[-1]
    assert final["reading_grade"] is not None and final["reading_grade"] <= 10
    bodies = llm_calls()
    assert len(bodies) == 2
    assert "simpler" in bodies[1]["input"][-1]["content"]


# ---- subject summaries (Atlas "Write a summary") --------------------------------------------

DRAVET = "MONDO:0100135"


async def _dravet_edges(client) -> list[str]:
    resp = await client.get(f"/atlas/summary/{DRAVET}")
    assert resp.status_code == 200
    return resp.json()["explain_edge_ids"]


async def test_subject_summary_has_its_own_cache_key(make_user, user_llm, llm_calls, client):
    from backend.api.services.explanation.pathdata import cache_key

    edges = await _dravet_edges(client)
    subject_key = cache_key(edges, DRAVET)
    assert subject_key == path_id([f"subject:{DRAVET}", *edges]) != path_id(edges)

    user = await make_user(role="patient")
    body = {"edge_ids": edges, "subject_node_id": DRAVET}
    status, events = await post_sse(user.client, "/explain", body)  # default mock responder
    assert status == 200, events
    final = events[-1]
    assert final["type"] == "final" and final["cached"] is False
    assert final["path_id"] == subject_key
    assert final["citations"] and set(final["citations"]) <= set(edges)

    sent = llm_calls()[0]
    assert "Summarise how the subject node" in sent["instructions"]
    assert "link by link" not in sent["instructions"]
    payload = json.loads(sent["input"][0]["content"])
    assert payload["subject"]["id"] == DRAVET and "path_edge_ids" not in payload
    assert sorted(payload["link_edge_ids"]) == sorted(edges)
    confidences = [link["confidence"] for link in payload["links"]]
    assert confidences == sorted(confidences, reverse=True)  # strongest first

    # cached for guests under the subject key only, never under the bare path key
    status, events = await post_sse(client, "/explain", {**body, "role": "patient"})
    assert status == 200 and events[-1]["cached"] is True
    assert events[-1]["path_id"] == subject_key
    resp = await client.post("/explain", json={"edge_ids": edges, "role": "patient"})
    assert resp.status_code == 401


async def test_subject_summary_guest_without_cache_gets_401(client):
    edges = await _dravet_edges(client)
    resp = await client.post(
        "/explain", json={"edge_ids": edges, "subject_node_id": DRAVET, "role": "guest"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "sign_in_required"


async def test_subject_summary_unknown_subject_404(make_user, user_llm, client):
    edges = await _dravet_edges(client)
    for subject in ("MONDO:0000000", "T:diseases"):
        body = {"edge_ids": edges, "subject_node_id": subject}
        assert (await client.post("/explain", json=body)).status_code == 404
    user = await make_user(role="patient")
    resp = await user.client.post(
        "/explain", json={"edge_ids": edges, "subject_node_id": "MONDO:0000000"}
    )
    assert resp.status_code == 404


async def test_template_subject_summary(app, client):
    edges = await _dravet_edges(client)
    async with user_transaction(None) as db:
        data = await load_path_data(db, edges, subject_id=DRAVET)
    out = template_explanation(data, Role.patient, "en")
    assert out.startswith(
        "Here is how Dravet syndrome is connected in the atlas, strongest links first."
    )
    assert "link by link" not in out
    assert all(f"[{e}]" in out for e in edges)
    assert "hypothesis" in out  # the inferred similar-disease links are labelled
    de = template_explanation(data, Role.patient, "de")
    assert de.startswith("So ist Dravet syndrome im Atlas verbunden")


# ---- steps (the Atlas panel's streamed "Write a summary") -----------------------------------


def _types(events: list[dict]) -> list[str]:
    return [e["type"] for e in events]


async def test_steps_stream_status_then_checked_text(make_user, user_llm, client):
    edges = await _dravet_edges(client)
    user = await make_user(role="doctor")  # the patient text is cached by an earlier test
    body = {"edge_ids": edges, "subject_node_id": DRAVET, "steps": True}
    status, events = await post_sse(user.client, "/explain", body)
    assert status == 200, events
    statuses = [e for e in events if e["type"] == "status"]
    assert [e["step"] for e in statuses][:3] == ["reading", "writing", "checking"]
    assert statuses[0]["message"] == f"Reading {len(edges)} links"
    # every status comes before the first text: no text is shown before the checks passed
    first_delta = _types(events).index("delta")
    assert set(_types(events)[:first_delta]) == {"status"}
    assert set(_types(events)[first_delta:-1]) == {"delta"}
    final = events[-1]
    assert final["type"] == "final" and final["cached"] is False
    assert "".join(e["text"] for e in events[first_delta:-1]) == final["text"]


async def test_steps_report_a_rewrite(make_user, user_llm):
    user = await make_user(role="researcher")  # patient texts are cached by earlier tests
    user_llm.enqueue({"text": "These diseases share a gene [e_ffffffffffff]."}, {"text": SIMPLE})
    status, events = await post_sse(
        user.client, "/explain", {"edge_ids": [COUNTEREXAMPLE], "steps": True, "language": "de"}
    )
    steps = [e["step"] for e in events if e["type"] == "status"]
    assert steps == ["reading", "writing", "checking", "fixing_sources", "checking"]
    assert events[2]["message"] == "Prüft die Quellen"
    assert "e_ffffffffffff" not in "".join(e.get("text", "") for e in events)


async def test_steps_off_keeps_the_plain_stream(make_user, user_llm):
    user = await make_user(role="patient")
    user_llm.enqueue({"text": SIMPLE})
    status, events = await post_sse(user.client, "/explain", {"edge_ids": [COUNTEREXAMPLE]})
    assert status == 200
    assert set(_types(events)[:-1]) == {"delta"} and events[-1]["type"] == "final"


async def test_steps_on_a_cached_text_replay_it(client):
    body = {"edge_ids": DEMO["path_edge_ids"], "role": "guest", "steps": True}
    status, events = await post_sse(client, "/explain", body)
    assert status == 200
    assert set(_types(events)[:-1]) == {"delta"} and events[-1]["cached"] is True


async def test_steps_error_is_an_event(make_user, user_llm):
    user = await make_user(role="patient")
    user_llm.configure(fail_mode="usage_limit")
    status, events = await post_sse(user.client, "/explain", {"edge_ids": [PENDING], "steps": True})
    assert status == 200
    assert events[0]["type"] == "status" and events[0]["step"] == "reading"
    assert "delta" not in _types(events)
    assert events[-1]["type"] == "error" and events[-1]["code"] == "rate_limited"


async def test_steps_errors_before_the_stream_stay_http(make_user, user_llm, client):
    resp = await client.post(
        "/explain", json={"edge_ids": [COUNTEREXAMPLE], "role": "guest", "steps": True}
    )
    assert resp.status_code == 401
    user = await make_user(role="patient", age_confirmed=False)
    resp = await user.client.post("/explain", json={"edge_ids": [PENDING], "steps": True})
    assert resp.status_code == 403


async def test_steps_closing_the_stream_cancels_the_model_call(app, monkeypatch, mock_llm):
    import asyncio

    from backend.api.services import explanation
    from backend.schemas.common import Lens

    started, cancelled = asyncio.Event(), asyncio.Event()

    async def slow(llm, data, role, language, *, on_step=None, **_):
        on_step("writing")
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(explanation, "generate_explanation", slow)
    async with user_transaction(None) as db:
        data = await load_path_data(db, [COUNTEREXAMPLE])
    lens = Lens(role=Role.patient, language="en")
    user = type("U", (), {"id": "00000000-0000-0000-0000-000000000000"})()
    stream = explanation._stream(data, lens, user, mock_llm, steps=True)
    first = await anext(stream)
    second = await anext(stream)
    assert (first.root.step, second.root.step) == ("reading", "writing")
    await started.wait()
    await stream.aclose()  # the client went away
    await asyncio.wait_for(cancelled.wait(), 2)
