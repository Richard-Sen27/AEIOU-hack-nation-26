import pytest

from backend.api.services import graph as graph_service
from backend.schemas.common import Lens
from backend.schemas.enums import (
    VUS_NOTICE,
    EdgeStatus,
    LabelStyle,
    NodeType,
    Origin,
    Role,
    StartLayout,
)
from readpath.conftest import DEMO, as_user, refresh_overlays

DRAVET = "MONDO:0100135"
SCN2A_DEE = "MONDO:9900003"


async def test_store_loaded_from_fixture(client):
    store = graph_service.get_graph()
    assert len(store.nodes) == 69 and len(store.edges) == 136
    assert store.data_version == "fixture"
    assert store.edges[DEMO["contradicted_edge_id"]].contradiction_count == 1


@pytest.mark.parametrize("node_id", [DRAVET, "HGNC:10588", "HP:0001250", "CLUSTER:2"])
async def test_neighborhood_identical_across_roles(client, node_id):
    views = {}
    for role in Role:
        resp = await client.get(f"/neighborhood/{node_id}", params={"role": role.value})
        assert resp.status_code == 200
        views[role] = resp.json()
    node_sets = {r: {n["id"] for n in v["nodes"]} for r, v in views.items()}
    edge_sets = {r: {e["id"] for e in v["edges"]} for r, v in views.items()}
    assert len({frozenset(s) for s in node_sets.values()}) == 1
    assert len({frozenset(s) for s in edge_sets.values()}) == 1
    stripped = [{k: v for k, v in view.items() if k != "hints"} for view in views.values()]
    assert all(s == stripped[0] for s in stripped)
    hints = {r: v["hints"] for r, v in views.items()}
    assert hints[Role.researcher]["show_ids"] is True
    assert hints[Role.patient]["show_ids"] is False
    assert hints[Role.researcher]["label_style"] == LabelStyle.technical
    assert hints[Role.guest]["start_layout"] == StartLayout.tour
    assert hints[Role.doctor]["label_style"] == LabelStyle.clinical


async def test_neighborhood_contents(client):
    body = (await client.get(f"/neighborhood/{DRAVET}")).json()
    ids = {n["id"] for n in body["nodes"]}
    assert body["center"]["id"] == DRAVET and body["nodes"][0]["id"] == DRAVET
    assert {"HGNC:10585", "HP:0001250", "ORG:fx-dravet-families", "MONDO:9900001"} <= ids
    assert all(n["x"] is not None and n["y"] is not None for n in body["nodes"])
    for e in body["edges"]:
        assert e["source_id"] in ids and e["target_id"] in ids
    assert body["cluster"]["id"] == "CLUSTER:2"


async def test_cluster_neighborhood_is_its_members(client):
    body = (await client.get("/neighborhood/CLUSTER:3")).json()
    ids = {n["id"] for n in body["nodes"]} - {"CLUSTER:3"}
    assert ids == {"MONDO:9900007", "MONDO:9900008", "MONDO:9900009"}
    assert DEMO["low_confidence_edge_id"] not in {e["id"] for e in body["edges"]}


async def test_unknown_node_404(client):
    resp = await client.get("/node/MONDO:0000000")
    assert resp.status_code == 404
    assert "MONDO" not in resp.text


async def test_node_detail_and_vus_notice(client):
    body = (await client.get(f"/node/{DEMO['vus_variant_id']}")).json()
    assert body["classification"] == "uncertain_significance"
    assert body["vus_notice"] == VUS_NOTICE
    plain = (await client.get("/node/CLINVAR:FX0001")).json()
    assert plain["classification"] == "pathogenic" and plain["vus_notice"] is None

    dravet = (await client.get(f"/node/{DRAVET}")).json()
    assert "SMEI" in dravet["synonyms"]
    assert dravet["cluster"]["id"] == "CLUSTER:2"
    counts = {c["relation"]: c["count"] for c in dravet["relation_counts"]}
    assert counts["has_phenotype"] == 6
    assert dravet["degree"] == sum(counts.values())
    assert "symptoms" in dravet["summary"]


async def test_clusters(client):
    body = (await client.get("/clusters")).json()
    assert [c["id"] for c in body] == ["CLUSTER:1", "CLUSTER:2", "CLUSTER:3"]
    assert body[0]["member_count"] == 4 and body[0]["mechanism_summary"]
    assert all(c["origin"] == Origin.inferred for c in body)


async def test_atlas_etag_and_caching(client):
    resp = await client.get("/atlas.json")
    assert resp.status_code == 200
    etag = resp.headers["etag"]
    assert etag.startswith('"fixture.')
    assert "max-age" in resp.headers["cache-control"]
    body = resp.json()
    # other suites may leave shared contributions behind; count the pipeline graph only
    assert len([n for n in body["nodes"] if not n["id"].startswith("CONTRIB:")]) == 69
    assert len([e for e in body["edges"] if not e["id"].startswith("c_")]) == 136
    assert body["data_version"] == "fixture"
    assert all(n["x"] is not None for n in body["nodes"])
    again = await client.get("/atlas.json", headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.headers["etag"] == etag


@pytest.mark.parametrize("edge_key", ["contradicted_edge_id", "path_edge_ids"])
async def test_evidence_breakdown_reproduces_confidence(client, edge_key):
    ids = DEMO[edge_key] if isinstance(DEMO[edge_key], list) else [DEMO[edge_key]]
    for eid in ids:
        body = (await client.get(f"/edge/{eid}/evidence")).json()
        bd = body["confidence_breakdown"]
        assert bd["result"] == pytest.approx(body["edge"]["confidence"], abs=1e-6)
        assert len(bd["supporting"]) == len(body["supporting"])
        assert bd["n_contradicting"] == len(body["contradicting"])
        assert bd["penalty"] == pytest.approx(0.1 * bd["n_contradicting"])


async def test_every_fixture_edge_breakdown_matches(client):
    for eid, edge in graph_service.get_graph().edges.items():
        body = (await client.get(f"/edge/{eid}/evidence")).json()
        assert body["confidence_breakdown"]["result"] == pytest.approx(edge.confidence, abs=1e-6)


async def test_contradiction_surfaced(client):
    body = (await client.get(f"/edge/{DEMO['contradicted_edge_id']}/evidence")).json()
    assert len(body["contradicting"]) == 1
    assert body["contradicting"][0]["polarity"] == "contradicts"
    assert "0.1 × 1" in body["confidence_breakdown"]["formula"]


async def test_unknown_edge_404(client):
    assert (await client.get("/edge/e_000000000000/evidence")).status_code == 404


async def test_flagged_edge_is_under_review(client, make_user, connect_as):
    eid = DEMO["path_edge_ids"][0]
    user = await make_user(role="patient")
    await as_user(
        connect_as,
        user.id,
        "INSERT INTO edge_flags (edge_id, user_id, reason) VALUES ($1, $2, 'test')",
        eid,
        user.id,
    )
    try:
        await refresh_overlays()
        edge = (await client.get(f"/edge/{eid}/evidence")).json()
        assert edge["edge"]["status"] == EdgeStatus.under_review
        assert edge["edge"]["flagged"] is True and edge["open_flags"] == 1
        hood = (await client.get(f"/neighborhood/{SCN2A_DEE}")).json()
        presented = next(e for e in hood["edges"] if e["id"] == eid)
        assert presented["status"] == "under_review" and presented["flagged"]
        atlas = (await client.get("/atlas.json")).json()
        assert next(e for e in atlas["edges"] if e["id"] == eid)["status"] == "under_review"
        assert graph_service.get_graph().edges[eid].status == EdgeStatus.active  # not rewritten
    finally:
        await as_user(connect_as, user.id, "DELETE FROM edge_flags WHERE user_id = $1", user.id)
        await refresh_overlays()
    edge = (await client.get(f"/edge/{eid}/evidence")).json()
    assert edge["edge"]["status"] == "active" and edge["edge"]["flagged"] is False


async def test_contributions_overlay_appears_and_disappears(client, make_user, connect_as):
    user = await make_user(role="patient", consents=["contribute"])
    consent = (
        await as_user(connect_as, user.id, "SELECT id FROM consents WHERE user_id = $1", user.id)
    )[0]["id"]
    await as_user(
        connect_as,
        user.id,
        "INSERT INTO contributions (user_id, kind, payload, consent_id) VALUES"
        " ($1, 'phenotype_profile', $2::jsonb, $3), ($1, 'asset', $4::jsonb, $3)",
        user.id,
        '{"disease_id": "MONDO:9900010", "phenotype_ids": ["HP:0001250", "HP:9999999"],'
        ' "excluded_phenotype_ids": ["HP:0011968"], "age_range": "1-5"}',
        consent,
        '{"asset_type": "registry", "name": "SYNGAP1 family registry",'
        ' "disease_ids": ["MONDO:9900010"]}',
    )
    try:
        await refresh_overlays()
        hood = (await client.get("/neighborhood/MONDO:9900010")).json()
        overlay = [e for e in hood["edges"] if e["id"].startswith("c_")]
        assert {e["origin"] for e in overlay} == {"patient_reported", "user_contributed"}
        assert all(e["status"] == "pending_review" for e in overlay)
        assert all(e["confidence"] == pytest.approx(0.2) for e in overlay)
        pheno = next(e for e in overlay if e["relation"] == "has_phenotype")
        assert pheno["target_id"] == "HP:0001250" and pheno["features"]["reports"] == 1
        asset = next(n for n in hood["nodes"] if n["id"].startswith("CONTRIB:"))
        assert asset["type"] == NodeType.registry and asset["attrs"]["contributed"] is True
        assert not any(n["type"] == "patient" for n in hood["nodes"])
        # other edges' confidence untouched
        base = graph_service.get_graph().edges[DEMO["low_confidence_edge_id"]]
        assert base.confidence == pytest.approx(0.3)
        ev = (await client.get(f"/edge/{pheno['id']}/evidence")).json()
        assert ev["supporting"][0]["tier"] == "patient_reported"
        detail = (await client.get(f"/node/{asset['id']}")).json()
        assert detail["degree"] == 1
        export = (await client.get("/export/graph", params={"node": "MONDO:9900010"})).text
        assert "c_" not in export and "CONTRIB:" not in export
    finally:
        await as_user(
            connect_as,
            user.id,
            "UPDATE consents SET revoked_at = now() WHERE user_id = $1",
            user.id,
        )
        await refresh_overlays()
    hood = (await client.get("/neighborhood/MONDO:9900010")).json()
    assert not [e for e in hood["edges"] if e["id"].startswith("c_")]
    assert not [n for n in hood["nodes"] if n["id"].startswith("CONTRIB:")]


async def test_empty_store_does_not_crash(restore_graph):
    graph_service.set_graph(graph_service.build_store(nodes=[], edges=[]))
    assert graph_service.clusters() == []
    assert graph_service.atlas_layout().nodes == []
    with pytest.raises(Exception) as exc:
        graph_service.neighborhood(DRAVET, Lens())
    assert getattr(exc.value, "status_code", None) == 404
