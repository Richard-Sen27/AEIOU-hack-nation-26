"""Wide scope, stage A, on the fixture: core diseases stay off the Atlas tree but are found by
search, the summary panel and Dr. Wu's symptom matching; the term table loads at startup."""

import pytest

from backend.api.services import atlas_tree, phenotype_match
from backend.api.services import graph as graph_service
from backend.api.services.chat.postcheck import AgentDraft, check_reply
from backend.api.services.chat.tools import TurnState, match_phenotypes
from backend.db.session import user_transaction
from backend.fixtures.load import read_fixture
from backend.schemas.chat import Claim
from backend.schemas.common import Lens
from backend.schemas.enums import Origin, Role
from backend.schemas.profile import PatientProfile

CORE = "MONDO:9900002"  # Familial hemiplegic migraine type 3 (FHM3), CLUSTER:1
CORE_ORPHA = "ORPHA:569"  # fixture value, only in attrs.orpha_ids (no synonym row)


def fixture_store(mutate=None) -> graph_service.GraphStore:
    """The fixture graph as the API builds it, with optional changes to the node rows."""
    data = read_fixture()
    nodes = [{k: v for k, v in n.items() if k != "synonyms"} for n in data["nodes"]]
    for n in nodes:
        n["attrs"] = dict(n.get("attrs") or {})
    if mutate:
        mutate({n["id"]: n for n in nodes})
    return graph_service.build_store(
        nodes=nodes,
        edges=[{**e, "data_version": "fixture"} for e in data["edges"]],
        synonyms=[
            {"node_id": n["id"], "synonym": s["synonym"]}
            for n in data["nodes"]
            for s in n["synonyms"]
        ],
        clusters=data["clusters"],
        ingestion={"data_version": "fixture"},
    )


def _mark_core(*ids: str, **attrs):
    def mutate(by_id: dict) -> None:
        for nid in ids:
            by_id[nid]["attrs"].update({"tier": "core", **attrs})

    return mutate


@pytest.fixture
def core_store(restore_graph):
    store = fixture_store(_mark_core(CORE, orpha_ids=[CORE_ORPHA]))
    graph_service.set_graph(store)
    phenotype_match.set_terms(None)
    return store


def _tree_entities(tree) -> set[str]:
    return {n.id for n in tree.nodes if n.kind == "entity"}


# --- the tree shows the focus set only --------------------------------------------------------


def test_tier_focus_and_absent_give_the_same_tree():
    plain = atlas_tree.build_tree(fixture_store())

    def all_focus(by_id: dict) -> None:
        for n in by_id.values():
            n["attrs"]["tier"] = "focus"

    explicit = atlas_tree.build_tree(fixture_store(all_focus))
    assert plain.model_dump_json() == explicit.model_dump_json()


def test_core_disease_stays_off_the_tree():
    store = fixture_store(_mark_core(CORE))
    tree = atlas_tree.build_tree(store)
    entities = _tree_entities(tree)
    assert CORE not in entities
    assert entities == {n for n in store.nodes if n != CORE}
    assert all(e.source in entities and e.target in entities for e in tree.edges)
    touching = {e.id for e in store.edges.values() if CORE in (e.source_id, e.target_id)}
    assert touching and not touching & {e.id for e in tree.edges}
    assert "CLUSTER:1" in entities  # its other members are focus
    assert {c.id for c in tree.clusters} == set(store.clusters)


def test_cluster_without_focus_disease_is_dropped():
    members = ["MONDO:9900007", "MONDO:9900008", "MONDO:9900009"]  # all of CLUSTER:3
    store = fixture_store(_mark_core(*members))
    tree = atlas_tree.build_tree(store)
    entities = _tree_entities(tree)
    assert not entities & {*members, "CLUSTER:3"}
    assert "CLUSTER:3" not in {c.id for c in tree.clusters}
    assert not any(n.cluster_id == "CLUSTER:3" for n in tree.nodes if n.category == "diseases")


def test_papers_keep_their_publication_tier():
    """attrs.tier on papers is the publication tier ("review"), not the map tier."""

    def mark(by_id: dict) -> None:
        for n in by_id.values():
            if n["type"] == "paper":
                n["attrs"]["tier"] = "review"

    store = fixture_store(mark)
    papers = {n for n, node in store.nodes.items() if node.type == "paper"}
    assert papers and papers <= _tree_entities(atlas_tree.build_tree(store))


async def test_atlas_json_not_built_at_startup(restore_graph):
    async with user_transaction(None) as db:
        store = await graph_service.load_graph(db)
    assert store.atlas_cache is None and store.tree_cache is not None
    import gc

    assert gc.get_freeze_count() > 0  # the store is outside the cyclic collector


# --- findable: search, summary ----------------------------------------------------------------


@pytest.mark.parametrize(
    "q",
    ["Familial hemiplegic migraine type 3", "FHM3", "fhm3", CORE, "mondo:9900002", CORE_ORPHA],
)
async def test_core_disease_found_by_search(client, core_store, q):
    resp = await client.get("/search", params={"q": q})
    assert resp.status_code == 200
    assert resp.json()["results"][0]["id"] == CORE


@pytest.mark.parametrize("q", ["MONDO:100135", "MONDO_100135", "mondo 0100135"])
async def test_unpadded_mondo_ids_resolve(client, q):
    first = (await client.get("/search", params={"q": q})).json()["results"][0]
    assert first["id"] == "MONDO:0100135" and first["match_kind"] == "exact"


async def test_unpadded_hp_id_resolves(client):
    first = (await client.get("/search", params={"q": "HP:1250"})).json()["results"][0]
    assert first["id"] == "HP:0001250"


async def test_core_disease_resolved_for_dr_wu(core_store, app):
    from backend.api.services.chat.tools import MentionIn, resolve
    from backend.schemas.enums import ChipType

    state = TurnState(lens=Lens(role=Role.patient), message="", profile=PatientProfile())
    out = await resolve(state, [MentionIn(text="FHM3", type=ChipType.disease, negated=False)])
    assert out["resolved"][0]["id"] == CORE


async def test_core_disease_summary(client, core_store):
    resp = await client.get(f"/atlas/summary/{CORE}", params={"role": "patient"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["node"]["id"] == CORE and body["tree_path"] == []
    keys = {s["key"] for s in body["sections"]}
    assert {"genes", "symptoms"} <= keys
    focus_diseases = sum(1 for n in core_store.nodes.values() if n.type == "disease") - 1
    assert body["coverage"] == "core" and body["focus_disease_count"] == focus_diseases


async def test_focus_and_untiered_nodes_report_focus_coverage(client, core_store):
    for nid in ("MONDO:0100135", "HGNC:10585", "CLUSTER:1"):
        body = (await client.get(f"/atlas/summary/{nid}")).json()
        assert body["coverage"] == "focus", nid


# --- Dr. Wu's symptom matching ----------------------------------------------------------------


def _state() -> TurnState:
    return TurnState(lens=Lens(role=Role.patient), message="", profile=PatientProfile())


def test_match_phenotypes_finds_the_core_disease(core_store):
    state = _state()
    out = match_phenotypes(state, ["migraine", "seizures"], [])
    assert [r["label"] for r in out["resolved"]] == ["Migraine", "Seizure"]
    top = out["results"][0]
    assert top["id"] == CORE and top["overlap"] == 2 and top["of"] == 2
    assert 0 < top["score"] <= 1
    shared = {s["recorded_as"]: s["edge_id"] for s in top["shared"]}
    assert set(shared) == {"Migraine", "Seizure"}
    for eid in shared.values():
        edge = core_store.edges[eid]
        assert edge.relation == "has_phenotype" and edge.source_id == CORE
        assert eid in state.edge_ids
    assert CORE in state.node_ids
    assert len(out["results"]) <= phenotype_match.TOP_K
    assert "probability" in out["note"] and "diagnosis" in out["note"]


def test_absent_symptom_lowers_the_score(core_store):
    plain = match_phenotypes(_state(), ["seizures", "hypotonia"], [])["results"]
    absent = match_phenotypes(_state(), ["seizures", "hypotonia"], ["feeding difficulties"])
    score = {r["id"]: r["score"] for r in plain}
    lowered = {r["id"]: r for r in absent["results"]}
    stxbp1 = lowered["MONDO:9900007"]  # records feeding difficulties
    assert stxbp1["score"] < score["MONDO:9900007"]
    assert stxbp1["recorded_but_absent_for_user"][0]["recorded_as"] == "Feeding difficulties"
    kcnq2 = lowered["MONDO:9900008"]  # does not
    assert kcnq2["score"] == score["MONDO:9900008"]


def test_excluded_term_lowers_the_score(restore_graph):
    store = fixture_store(
        _mark_core(
            CORE, excluded_phenotypes=[{"id": "HP:0001252", "label": "Hypotonia", "sources": []}]
        )
    )
    graph_service.set_graph(store)
    phenotype_match.set_terms(None)
    before = phenotype_match.rank(["HP:0002076"], [], store=fixture_store())
    after = phenotype_match.rank(["HP:0002076", "HP:0001252"], [])
    core = next(m for m in after if m.disease_id == CORE)
    assert core.excluded == ["HP:0001252"] and core.score < core.similarity
    assert before and before[0].disease_id == CORE


def test_unknown_symptom_is_unresolved(core_store):
    out = match_phenotypes(_state(), ["purple elbows"], [])
    assert out["unresolved"] == ["purple elbows"] and out["results"] == []


async def test_postcheck_accepts_match_citations(core_store, app):
    state = _state()
    out = match_phenotypes(state, ["migraine", "seizures"], [])
    eids = [s["edge_id"] for s in out["results"][0]["shared"]]
    other = next(e for e in core_store.edges.values() if e.id not in state.edge_ids)
    claims = [
        Claim(
            text="Migraine and seizures are recorded for this condition.",
            edge_ids=eids,
            origin=Origin.observed,
            confidence="high",
        ),
        Claim(text="Unrelated.", edge_ids=[other.id], origin=Origin.observed, confidence="high"),
    ]
    draft = AgentDraft(
        summary="Two conditions in the atlas have recorded symptoms that overlap yours.",
        uncertainty=None,
        claims=claims,
        contradictions=[],
        missing_evidence=[],
        cards=[],
        graph_focus=None,
        actions=[],
        follow_up=None,
    )
    reply, report = await check_reply(draft, state, None, asked=set())
    assert [c.edge_ids for c in reply.claims] == [eids]
    assert report.removed_claims == 1


# --- the term table ---------------------------------------------------------------------------


TERM_ROWS = [
    ("HP:0000118", "Phenotypic abnormality", [], [], 0.0),
    ("HP:0000707", "Abnormality of the nervous system", [], ["HP:0000118"], 0.4),
    ("HP:0001250", "Seizure", ["Seizures", "Epileptic seizure"], ["HP:0000707"], 1.2),
    ("HP:0002076", "Migraine", ["Migraine headache"], ["HP:0000707"], 3.1),
    ("HP:0011987", "Ectopic ossification in muscle tissue", ["Muscle ossification"], [], None),
]


async def test_term_table_loads_at_startup(connect_as, restore_graph):
    pipe = await connect_as("atlas_pipeline")
    await pipe.executemany(
        "INSERT INTO hpo_terms (id, label, synonyms, parents, ic) VALUES ($1, $2, $3, $4, $5)",
        TERM_ROWS,
    )
    try:
        async with user_transaction(None) as db:
            store = await graph_service.load_graph(db)
        terms = phenotype_match.get_terms(store)
        assert terms.source == "table" and len(terms.labels) == len(TERM_ROWS)
        assert terms.ancestors_of("HP:0001250") == {"HP:0000707", "HP:0000118"}
        assert terms.ic["HP:0002076"] == 3.1 and "HP:0011987" not in terms.ic
        assert terms.resolve("muscle ossification") == "HP:0011987"  # not a graph node
        assert terms.resolve("epileptic seizures") == "HP:0001250"
        assert store.phenotype_index.terms is terms
    finally:
        await pipe.execute("TRUNCATE hpo_terms")
        async with user_transaction(None) as db:
            await phenotype_match.load_terms(db)
    assert phenotype_match.get_terms().source == "graph"


async def test_app_cannot_write_term_table_or_changes(connect_as):
    import asyncpg

    app = await connect_as("atlas_app")
    assert await app.fetchval("SELECT count(*) >= 0 FROM hpo_terms")
    assert await app.fetchval("SELECT count(*) >= 0 FROM graph_changes")
    for sql in (
        "INSERT INTO hpo_terms (id, label) VALUES ('HP:1', 'x')",
        "INSERT INTO graph_changes (data_version, disease_id, node_id, node_type, change)"
        " VALUES ('v', 'MONDO:1', 'HGNC:1', 'gene', 'added')",
    ):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app.execute(sql)
    pipe = await connect_as("atlas_pipeline")
    tr = pipe.transaction()
    await tr.start()
    await pipe.execute(
        "INSERT INTO graph_changes (data_version, disease_id, node_id, node_type, change)"
        " VALUES ('v', 'MONDO:1', 'HGNC:1', 'gene', 'added')"
    )
    await tr.rollback()


def test_resolve_wording():
    table = phenotype_match.table_from_rows(
        [
            {"id": i, "label": label, "synonyms": syn, "parents": par, "ic": ic}
            for i, label, syn, par, ic in TERM_ROWS
        ]
    )
    assert table is not None
    assert table.resolve("HP:1250") == "HP:0001250"
    assert table.resolve("seizures") == "HP:0001250"
    assert table.resolve("frequent seizures") == "HP:0001250"
    assert table.resolve("migraine headaches") == "HP:0002076"
    assert table.resolve("ossification") == "HP:0011987"
    assert table.resolve("purple elbows") is None
    assert phenotype_match.table_from_rows([]) is None


# --- hub neighbourhoods -----------------------------------------------------------------------


async def test_neighborhood_capped_with_header(client, monkeypatch):
    monkeypatch.setattr(graph_service, "MAX_NEIGHBORS", 3)
    resp = await client.get("/neighborhood/HP:0001250")
    assert resp.status_code == 200
    body = resp.json()
    store = graph_service.get_graph()
    incident = graph_service._incident_edges(store, "HP:0001250")
    total = len({graph_service._other(e, "HP:0001250") for e in incident})
    assert len(body["nodes"]) == 4
    assert resp.headers["x-neighborhood-total"] == str(total)
    assert resp.headers["x-neighborhood-truncated"] == "true"
    ids = {n["id"] for n in body["nodes"]}
    assert all(e["source_id"] in ids and e["target_id"] in ids for e in body["edges"])


async def test_small_neighborhood_has_no_header(client):
    resp = await client.get("/neighborhood/MONDO:9900009")
    assert resp.status_code == 200
    assert "x-neighborhood-truncated" not in resp.headers
