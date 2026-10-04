"""Clusters at the wide data set's shape (pipeline analytics.node_clusters): member diseases
plus genes, symptoms and the cluster node itself carrying the cluster's id as their map
colour, single-disease clusters, and clusters with and without focus diseases."""

import gzip

import pytest

from backend.api.services import atlas_summary, atlas_tree
from backend.api.services import graph as graph_service
from backend.api.services import search as search_service
from backend.schemas.atlas import SummarySectionKey
from backend.schemas.common import Lens
from backend.schemas.enums import Role

BIG, SMALL, SINGLE = "CLUSTER:1", "CLUSTER:7", "CLUSTER:149"
BIG_MEMBERS, SMALL_MEMBERS = 320, 12
SYMPTOM = "HP:0001263"
SINGLE_DISEASE = "MONDO:0007289"


def _node(nid, ntype, label, cluster_id=None, **attrs):
    return {"id": nid, "type": ntype, "label": label, "attrs": attrs, "cluster_id": cluster_id}


def _edge(eid, s, relation, t, family, conf=0.9):
    return {
        "id": eid,
        "source_id": s,
        "target_id": t,
        "relation": relation,
        "family": family,
        "confidence": conf,
        "origin": "observed",
        "status": "active",
        "features": {},
        "data_version": "clusters",
    }


def _rows():
    nodes, edges, clusters = [], [], []
    big = [f"MONDO:{8100000 + i:07d}" for i in range(BIG_MEMBERS)]
    small = [f"MONDO:{8200000 + i:07d}" for i in range(SMALL_MEMBERS)]
    for i, did in enumerate(big):  # the first 5 are on the map
        nodes.append(_node(did, "disease", f"big {i}", BIG, tier="focus" if i < 5 else "core"))
    for i, did in enumerate(small):
        nodes.append(_node(did, "disease", f"small {i}", SMALL, tier="core"))
    nodes.append(_node(SINGLE_DISEASE, "disease", "cataract 13", SINGLE, tier="core"))
    # Genes and symptoms with the big cluster's colour (majority vote), not members.
    for g in range(400):
        gid = f"HGNC:{90000 + g}"
        nodes.append(_node(gid, "gene", f"G{g}", BIG, tier="core"))
        edges.append(_edge(f"g{g}", big[g % BIG_MEMBERS], "caused_by_variant_in", gid, "dna"))
    nodes.append(_node(SYMPTOM, "phenotype", "Global developmental delay", BIG, tier="focus"))
    for i, did in enumerate(big + small):
        edges.append(_edge(f"p{i}", did, "has_phenotype", SYMPTOM, "symptoms"))
    for i in range(BIG_MEMBERS - 1):
        edges.append(_edge(f"s{i}", big[i], "similar_symptoms", big[i + 1], "symptoms", 0.6))
    for cid, label, count in (
        (BIG, "Mitochondrial disorders · MT-ATP6", BIG_MEMBERS),
        (SMALL, "Small group · ABC1", SMALL_MEMBERS),
        (SINGLE, "cataract 13 with adult I phenotype", 1),
    ):
        # The cluster node points at itself, as the pipeline writes it.
        nodes.append(_node(cid, "cluster", label, cid))
        clusters.append(
            {
                "id": cid,
                "label": label,
                "mechanism_summary": "Mostly loss of function",
                "member_count": count,
                "attrs": {},
            }
        )
    return nodes, edges, clusters


@pytest.fixture(scope="module")
def store():
    nodes, edges, clusters = _rows()
    return graph_service.build_store(
        nodes=nodes, edges=edges, clusters=clusters, ingestion={"data_version": "clusters"}
    )


@pytest.fixture
def installed(store):
    previous = graph_service.get_graph()
    graph_service.set_graph(store)
    yield store
    graph_service.set_graph(previous)


@pytest.fixture
async def served(app, store):
    """The cluster store installed for API requests (the app fixture's store restored)."""
    previous = graph_service.get_graph()
    graph_service.set_graph(store)
    yield store
    graph_service.set_graph(previous)


LENS = Lens(role=Role.researcher)


def test_members_are_diseases_only(store):
    assert len(store.members[BIG]) == BIG_MEMBERS
    assert all(store.nodes[m].type == "disease" for ms in store.members.values() for m in ms)
    assert BIG not in store.members.get(BIG, [])


def test_cluster_neighborhood_keeps_its_members(installed):
    """The cap (300) holds members first; genes and symptoms with the colour are not members."""
    hood, total = graph_service.neighborhood_with_total(BIG, LENS)
    ids = [n.id for n in hood.nodes[1:]]
    assert len(ids) == graph_service.MAX_NEIGHBORS and total == BIG_MEMBERS
    assert all(installed.nodes[i].type == "disease" for i in ids)
    assert set(ids) <= set(installed.members[BIG])
    focus = {f"MONDO:{8100000 + i:07d}" for i in range(5)}
    assert focus <= set(ids)  # focus members win the cap
    assert len(hood.edges) >= graph_service.MAX_NEIGHBORS - 10  # their links come along

    small, total = graph_service.neighborhood_with_total(SMALL, LENS)
    assert {n.id for n in small.nodes[1:]} == set(installed.members[SMALL])
    assert total == SMALL_MEMBERS


async def test_cluster_neighborhood_headers(client, served):
    resp = await client.get(f"/neighborhood/{BIG}")
    assert resp.status_code == 200
    assert resp.headers["x-neighborhood-total"] == str(BIG_MEMBERS)
    assert resp.headers["x-neighborhood-truncated"] == "true"
    small = await client.get(f"/neighborhood/{SMALL}")
    assert "x-neighborhood-truncated" not in small.headers
    assert len(small.json()["nodes"]) == SMALL_MEMBERS + 1


def test_cluster_summary_counts_member_diseases(installed):
    assert f"Groups {BIG_MEMBERS} diseases" in graph_service.node_detail(BIG, LENS).summary
    patient = graph_service.node_detail(SMALL, Lens(role=Role.patient))
    assert f"Groups {SMALL_MEMBERS} conditions" in patient.summary
    single = graph_service.node_detail(SINGLE, Lens(role=Role.patient)).summary
    assert "single condition" in single and "Groups" not in single


def test_single_disease_cluster_is_not_a_group(installed):
    detail = graph_service.node_detail(SINGLE_DISEASE, LENS)
    assert detail.cluster is None
    assert graph_service.neighborhood(SINGLE_DISEASE, LENS).cluster is None
    summary = atlas_summary.atlas_summary(SINGLE_DISEASE, LENS)
    assert not any(s.key == SummarySectionKey.clusters for s in summary.sections)
    # The cluster itself stays reachable by id.
    own = graph_service.node_detail(SINGLE, LENS)
    assert own.cluster is not None and own.cluster.id == SINGLE
    assert graph_service.neighborhood(SINGLE, LENS).nodes[1].id == SINGLE_DISEASE


def test_group_member_keeps_its_group(installed):
    did = installed.members[SMALL][0]
    assert graph_service.node_detail(did, LENS).cluster.id == SMALL
    summary = atlas_summary.atlas_summary(did, LENS)
    section = next(s for s in summary.sections if s.key == SummarySectionKey.clusters)
    assert [i.id for i in section.items] == [SMALL]


@pytest.mark.parametrize("node_id", [SYMPTOM, "HGNC:90000"])
def test_symptoms_and_genes_have_no_mechanism_group(installed, node_id):
    """Their cluster_id is the pipeline's majority-vote colour (analytics.node_clusters)."""
    assert installed.nodes[node_id].cluster_id == BIG  # as loaded
    assert graph_service.node_detail(node_id, LENS).cluster is None
    assert graph_service.neighborhood(node_id, LENS).cluster is None
    summary = atlas_summary.atlas_summary(node_id, LENS)
    assert not any(s.key == SummarySectionKey.clusters for s in summary.sections)


def test_clusters_carry_counts_and_a_stable_order(installed):
    got = graph_service.clusters()
    assert [c.id for c in got] == [BIG, SMALL, SINGLE]  # on the map first, then by size
    by_id = {c.id: c for c in got}
    assert by_id[BIG].member_count == BIG_MEMBERS
    assert by_id[BIG].focus_member_count == 5 and by_id[BIG].on_map
    assert by_id[SMALL].focus_member_count == 0 and not by_id[SMALL].on_map
    assert by_id[SINGLE].member_count == 1 and not by_id[SINGLE].on_map
    assert graph_service.clusters() == got


def test_cluster_order_by_size_and_number():
    nodes = [
        _node(f"MONDO:{9000000 + i:07d}", "disease", f"d{i}", cid, tier=tier)
        for i, (cid, tier) in enumerate(
            [("CLUSTER:10", "core")] * 2
            + [("CLUSTER:9", "core")] * 2
            + [("CLUSTER:100", "core")] * 3
            + [("CLUSTER:2", "focus")]
        )
    ]
    clusters = [
        {"id": c, "label": c, "member_count": 0, "attrs": {}}
        for c in ("CLUSTER:10", "CLUSTER:9", "CLUSTER:100", "CLUSTER:2")
    ]
    store = graph_service.build_store(nodes=nodes, edges=[], clusters=clusters)
    previous = graph_service.get_graph()
    graph_service.set_graph(store)
    try:
        ids = [c.id for c in graph_service.clusters()]
    finally:
        graph_service.set_graph(previous)
    assert ids == ["CLUSTER:2", "CLUSTER:100", "CLUSTER:9", "CLUSTER:10"]


async def test_clusters_route_lists_the_new_fields(client, served):
    body = (await client.get("/clusters")).json()
    assert [c["id"] for c in body] == [BIG, SMALL, SINGLE]
    assert body[0]["on_map"] is True and body[0]["focus_member_count"] == 5
    assert body[2]["member_count"] == 1 and body[2]["on_map"] is False


def test_exact_symbol_beats_an_exact_synonym():
    """A gene whose symbol is the query ranks above a disease that has it as a synonym."""
    store = graph_service.build_store(
        nodes=[
            _node("HGNC:11444", "gene", "STXBP1", symbol="STXBP1"),
            _node("MONDO:0012812", "disease", "developmental and epileptic encephalopathy, 4"),
        ],
        edges=[],
        synonyms=[{"node_id": "MONDO:0012812", "synonym": "STXBP1"}],
    )
    store.nodes["MONDO:0012812"] = store.nodes["MONDO:0012812"].model_copy(
        update={"centrality": 1.0}
    )
    hits = search_service._exact_hits(store, "stxbp1")
    ranked = sorted(hits, key=lambda h: -search_service._final_score(h))
    assert [h.node_id for h in ranked] == ["HGNC:11444", "MONDO:0012812"]


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ("MONDO:0007606", True),
        ("hp_0001263", True),
        ("ORPHA:337", True),
        ("PMID:2317429", True),
        ("STXBP1", False),
        ("Dravet syndrome", False),
        ("SCN1A GOF", False),
    ],
)
def test_id_queries(q, expected):
    assert search_service._is_id_query(q) is expected


def test_tree_gzip_is_cached(installed, monkeypatch):
    installed.tree_cache = None
    calls = []
    real = gzip.compress
    monkeypatch.setattr(gzip, "compress", lambda *a, **k: calls.append(1) or real(*a, **k))
    body, etag = atlas_tree.tree_payload()
    for _ in range(3):
        gz, gz_etag = atlas_tree.tree_payload_gzip()
        assert gz_etag == etag and gzip.decompress(gz) == body
    assert len(calls) == 1
    installed.tree_cache = None  # a new data version (a reload) compresses again
    atlas_tree.tree_payload_gzip()
    assert len(calls) == 2
