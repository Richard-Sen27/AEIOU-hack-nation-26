import pytest

from backend.api.services import graph as graph_service
from backend.api.services import path as path_service
from backend.schemas.enums import CONFIDENCE_THRESHOLD, PathFamily, path_id
from readpath.conftest import DEMO, as_user, refresh_overlays

STXBP1_DEE = "MONDO:9900007"
SCN2A_LOF = "MONDO:9900005"
SEIZURE = "HP:0001250"


async def _path(client, a, b, **params):
    resp = await client.get("/path", params={"from": a, "to": b, **params})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _nodes(path):
    return [s["from_node"]["id"] for s in path["steps"]] + [path["steps"][-1]["to_node"]["id"]]


async def test_demo_path_and_deterministic_ids(client):
    body = await _path(client, STXBP1_DEE, "REG:fx-sodium-channel-registry")
    assert body["status"] == "ok" and body["coverage"] is None
    top = body["paths"][0]
    assert top["edge_ids"] == DEMO["path_edge_ids"]
    assert top["path_id"] == DEMO["path_id"] == path_id(top["edge_ids"])
    assert top["supported"] and top["all_active"]
    again = await _path(client, STXBP1_DEE, "REG:fx-sodium-channel-registry")
    assert [p["path_id"] for p in again["paths"]] == [p["path_id"] for p in body["paths"]]


async def test_paths_are_well_formed(client):
    body = await _path(client, STXBP1_DEE, "REG:fx-sodium-channel-registry", k=5)
    assert 1 <= len(body["paths"]) <= 5
    costs = [p["total_cost"] for p in body["paths"]]
    for p in body["paths"]:
        assert p["min_confidence"] >= CONFIDENCE_THRESHOLD
        assert p["all_observed"] == all(s["edge"]["origin"] == "observed" for s in p["steps"])
        for step in p["steps"]:
            e = step["edge"]
            ends = {e["source_id"], e["target_id"]}
            assert ends == {step["from_node"]["id"], step["to_node"]["id"]}
            assert step["reversed"] == (e["source_id"] != step["from_node"]["id"])
    assert len({p["path_id"] for p in body["paths"]}) == len(costs)


async def test_trustworthy_beats_short(client):
    """A direct 0.7 link exists, but the longer 0.9+ route wins."""
    direct = graph_service.get_graph().edges["e_8a65297ef0be"]
    assert {direct.source_id, direct.target_id} == {STXBP1_DEE, SCN2A_LOF}
    body = await _path(client, STXBP1_DEE, SCN2A_LOF)
    top = body["paths"][0]
    assert len(top["edge_ids"]) > 1
    assert top["total_cost"] < path_service.edge_cost(direct.confidence)


async def test_family_filter(client):
    for family in (PathFamily.dna, PathFamily.symptoms, PathFamily.research):
        body = await _path(client, STXBP1_DEE, "MONDO:9900003", family=family.value)
        assert body["family"] == family
        for p in body["paths"]:
            assert {s["edge"]["family"] for s in p["steps"]} == {family.value}
    symptoms = await _path(client, STXBP1_DEE, "MONDO:9900003", family="symptoms")
    assert symptoms["paths"][0]["edge_ids"] == ["e_3b8845b635b8"]
    research = await _path(client, STXBP1_DEE, "MONDO:9900003", family="research")
    assert research["paths"][0]["edge_ids"] == ["e_7491e499de92"]


async def test_vus_excluded_unless_requested(client):
    vus = DEMO["vus_variant_id"]
    default = await _path(client, "HGNC:11444", STXBP1_DEE, k=10)
    assert all(vus not in _nodes(p) for p in default["paths"])
    included = await _path(client, "HGNC:11444", STXBP1_DEE, k=10, include_vus="true")
    assert any(vus in _nodes(p) for p in included["paths"])


async def test_hub_phenotype_not_used_as_shortcut(client):
    store = graph_service.get_graph()
    assert graph_service.is_hub(store, store.nodes[SEIZURE])
    body = await _path(client, "MONDO:9900009", "MONDO:9900004", k=5)
    assert body["status"] == "ok"
    for p in body["paths"]:
        assert SEIZURE not in _nodes(p)[1:-1]
    # endpoints may still be hubs
    direct = await _path(client, SEIZURE, "MONDO:9900004")
    assert direct["paths"][0]["edge_ids"] == ["e_ced02afcc635"]


async def test_hub_penalty_applies_to_generic_nodes_only(client):
    store = graph_service.get_graph()
    assert graph_service.hub_penalty(store, store.nodes["MECH:loss_of_function"]) > 0
    assert graph_service.hub_penalty(store, store.nodes["MONDO:9900003"]) == 0


async def test_pending_review_edge_never_used(client):
    pending = DEMO["pending_review_edge_id"]
    body = await _path(client, "MONDO:9900003", "MONDO:9900008", k=10)
    for p in body["paths"]:
        assert pending not in p["edge_ids"]


async def test_flagged_edges_excluded(client, make_user, connect_as):
    user = await make_user(role="doctor")
    flagged = ["e_3b8845b635b8", "e_7491e499de92"]
    before = await _path(client, STXBP1_DEE, "MONDO:9900003")
    assert before["paths"][0]["edge_ids"][0] in flagged
    for eid in flagged:
        await as_user(
            connect_as,
            user.id,
            "INSERT INTO edge_flags (edge_id, user_id, reason) VALUES ($1, $2, 'test')",
            eid,
            user.id,
        )
    try:
        await refresh_overlays()
        after = await _path(client, STXBP1_DEE, "MONDO:9900003", k=10)
        for p in after["paths"]:
            assert not set(flagged) & set(p["edge_ids"])
            assert p["all_active"]
    finally:
        await as_user(connect_as, user.id, "DELETE FROM edge_flags WHERE user_id = $1", user.id)
        await refresh_overlays()


async def test_no_supported_route_coverage(client):
    pair = DEMO["no_supported_route"]
    body = await _path(client, pair["from"], pair["to"])
    assert body["status"] == "no_supported_route" and body["paths"] == []
    cov = body["coverage"]
    assert cov["sources_queried"] and all(s["count"] >= 0 for s in cov["sources_queried"])
    assert (
        cov["sources_queried"][0]["source"] == "fixture" and cov["sources_queried"][0]["count"] > 0
    )
    partial = cov["closest_partial_path"]
    assert partial["supported"] is False
    assert _nodes(partial)[0] == pair["from"] and _nodes(partial)[-1] == pair["to"]
    assert DEMO["low_confidence_edge_id"] in partial["edge_ids"]
    assert partial["min_confidence"] < CONFIDENCE_THRESHOLD
    missing = cov["missing_link"]
    assert {missing["from_id"], missing["to_id"]} == {pair["from"], STXBP1_DEE}
    assert "0.30" in missing["description"]
    assert "SYNGAP1" in cov["suggested_question"]


async def test_no_route_at_all_reports_reach(client):
    body = await _path(client, "MONDO:9900010", "MONDO:0100135", family="symptoms")
    assert body["status"] == "no_supported_route"
    cov = body["coverage"]
    assert cov["closest_partial_path"] is None
    assert cov["missing_link"]["from_id"] == "MONDO:9900010"
    assert "reaches" in cov["missing_link"]["description"]
    assert cov["suggested_question"]


async def test_errors(client):
    assert (
        await client.get("/path", params={"from": "MONDO:0", "to": STXBP1_DEE})
    ).status_code == 404
    same = await client.get("/path", params={"from": STXBP1_DEE, "to": STXBP1_DEE})
    assert same.status_code == 400
    assert (await client.get("/path", params={"from": STXBP1_DEE})).status_code == 422


def test_service_signature_for_chat_tools(app):
    resp = path_service.find_paths(STXBP1_DEE, SCN2A_LOF, family=PathFamily.all, k=1)
    assert len(resp.paths) == 1


@pytest.mark.parametrize("k", [1, 3])
async def test_k_respected(client, k):
    assert len((await _path(client, STXBP1_DEE, SCN2A_LOF, k=k))["paths"]) == k
