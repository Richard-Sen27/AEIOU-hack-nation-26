import io

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
