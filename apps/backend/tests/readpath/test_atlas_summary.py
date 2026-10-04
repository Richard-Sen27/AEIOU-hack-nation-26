import pytest

from backend.api.services import atlas_summary as summary_service
from backend.api.services import atlas_tree
from backend.api.services import graph as graph_service
from backend.schemas.atlas import AtlasSummary, SummarySectionKey, TreeNodeKind
from backend.schemas.common import Lens
from backend.schemas.enums import VUS_NOTICE, Role, edge_id
from readpath.conftest import DEMO

DRAVET = "MONDO:0100135"
SCN2A_DEE = "MONDO:9900003"


async def _summary(client, node_id: str, role: str = "patient") -> AtlasSummary:
    resp = await client.get(f"/atlas/summary/{node_id}", params={"role": role})
    assert resp.status_code == 200, resp.text
    return AtlasSummary.model_validate(resp.json())


def _section(summary: AtlasSummary, key: SummarySectionKey):
    return next((s for s in summary.sections if s.key == key), None)


def _ids(summary: AtlasSummary, key: SummarySectionKey) -> list[str]:
    section = _section(summary, key)
    return [i.id for i in section.items] if section else []


async def test_disease_summary_contract(client):
    summary = await _summary(client, DRAVET)
    assert summary.node.id == DRAVET and summary.data_version == "fixture"
    assert summary.headline
    assert [p.kind for p in summary.tree_path][:2] == [TreeNodeKind.root, TreeNodeKind.category]
    assert summary.tree_path[1].id == "T:diseases"

    keys = [s.key for s in summary.sections]
    assert keys == [k for k in SummarySectionKey if k in keys]  # fixed order
    assert {SummarySectionKey.genes, SummarySectionKey.symptoms} <= set(keys)
    assert SummarySectionKey.similar_diseases in keys
    for section in summary.sections:
        assert 0 < len(section.items) <= 10 and section.total >= len(section.items)
        assert all(item.type == section.node_type for item in section.items)
        ranks = [(-i.score, -i.best_confidence, i.label.casefold()) for i in section.items]
        assert ranks == sorted(ranks)
    assert 0 < len(summary.explain_edge_ids) <= 20
    assert len(set(summary.explain_edge_ids)) == len(summary.explain_edge_ids)
    assert summary.vus_notice is None


async def test_disease_reaches_people_and_institutions_through_chains(client):
    summary = await _summary(client, DRAVET)
    store = graph_service.get_graph()

    researchers = _section(summary, SummarySectionKey.researchers)
    assert {i.id for i in researchers.items} == {"RES:fx-alpha", "RES:fx-gamma"}
    for item in researchers.items:
        assert item.hops == 2 and item.via_label == "via 1 paper"
        first, second = (store.edges[e] for e in item.via)
        assert (first.relation, first.target_id) == ("about", DRAVET)  # subject outward
        assert (second.relation, second.source_id) == ("authored", item.id)

    doctors = _section(summary, SummarySectionKey.doctors)
    assert [(i.id, i.hops, i.via_label) for i in doctors.items] == [
        ("DOC:fx-one", 2, "via 1 trial")
    ]

    institutions = {i.id: i for i in _section(summary, SummarySectionKey.institutions).items}
    assert set(institutions) == {"INST:fx-childrens", "INST:fx-epilepsy", "INST:fx-neuro"}
    assert institutions["INST:fx-childrens"].via_label == "via doctor Clinician One (fixture)"
    assert institutions["INST:fx-neuro"].via_label.startswith("via researcher ")
    assert all(i.hops == 3 and len(i.via) == 3 for i in institutions.values())


async def test_researchers_ranked_by_supporting_chains(client):
    summary = await _summary(client, SCN2A_DEE)
    researchers = _section(summary, SummarySectionKey.researchers).items
    alpha = next(i for i in researchers if i.id == "RES:fx-alpha")
    assert researchers[0].id == "RES:fx-alpha"
    assert alpha.score == 2 and alpha.via_label == "via 1 grant and 1 paper"
    assert all(i.score < alpha.score for i in researchers[1:])


async def test_inferred_flag_is_carried(client):
    similar = _section(await _summary(client, DRAVET), SummarySectionKey.similar_diseases)
    assert similar.items and all(i.inferred and i.hops == 1 for i in similar.items)


async def test_under_review_flag_is_carried(client):
    pending = graph_service.get_edge(DEMO["pending_review_edge_id"])
    summary = await _summary(client, pending.source_id)
    items = [i for s in summary.sections for i in s.items if pending.id in i.via]
    assert items and all(i.under_review for i in items)


async def test_open_flags_mark_items_under_review(client, restore_graph):
    store = restore_graph
    paper_edge = edge_id("PMID:FX0003", "about", DRAVET)
    assert paper_edge in store.edges
    store.flag_counts[paper_edge] = 1
    try:
        summary = await _summary(client, DRAVET)
    finally:
        store.flag_counts.pop(paper_edge)
    for key in (SummarySectionKey.papers, SummarySectionKey.researchers):
        items = [i for i in _section(summary, key).items if paper_edge in i.via]
        assert items and all(i.under_review for i in items)


async def test_no_node_listed_twice(client):
    for node_id in [DRAVET, SCN2A_DEE, "HP:0001250", "HGNC:10588", "INST:fx-neuro", "CLUSTER:1"]:
        summary = await _summary(client, node_id)
        ids = [i.id for s in summary.sections for i in s.items]
        assert len(ids) == len(set(ids)), node_id
        assert node_id not in ids


async def test_cluster_items(client):
    own = _section(await _summary(client, DRAVET), SummarySectionKey.clusters)
    assert [i.id for i in own.items] == ["CLUSTER:2"]
    item = own.items[0]
    assert item.via == [] and item.hops == 1 and item.inferred and item.via_label

    cluster = await _summary(client, "CLUSTER:1")
    diseases = _section(cluster, SummarySectionKey.diseases)
    assert diseases.total == 4
    assert all(i.via == [] and i.inferred and i.via_label for i in diseases.items)
    genes = _section(cluster, SummarySectionKey.genes)
    assert {i.id for i in genes.items} == {"HGNC:10585", "HGNC:10588", "HGNC:10597"}
    assert all("top gene" in i.via_label for i in genes.items)
    assert cluster.explain_edge_ids == []


async def test_claims_section(client):
    summary = await _summary(client, "HGNC:10588")
    assert _ids(summary, SummarySectionKey.claims) == ["CLAIM:fx0001"]


async def test_gene_and_phenotype_chains_through_diseases(client):
    gene = await _summary(client, "HGNC:10588")
    trials = _section(gene, SummarySectionKey.trials).items
    assert [i.id for i in trials] == ["NCT99000002"] and trials[0].hops == 2
    assert trials[0].via_label.startswith("via condition ")

    seizure = await _summary(client, "HP:0001250")
    genes = _section(seizure, SummarySectionKey.genes).items
    assert genes[0].score == 3 and genes[0].via_label.startswith("via 3 conditions")
    assert _ids(seizure, SummarySectionKey.patient_orgs)


async def test_same_facts_for_every_role(client):
    bodies = [(await _summary(client, DRAVET, role)) for role in Role]
    first = bodies[0]
    for other in bodies[1:]:
        assert other.sections == first.sections
        assert other.explain_edge_ids == first.explain_edge_ids
    assert len({b.headline for b in bodies}) > 1  # wording follows the lens


async def test_vus_notice(client):
    body = (await client.get(f"/atlas/summary/{DEMO['vus_variant_id']}")).json()
    assert body["vus_notice"] == VUS_NOTICE


@pytest.mark.parametrize("node_id", ["MONDO:0000000", "T:root", "T:diseases"])
async def test_unknown_and_group_ids_404(client, node_id):
    resp = await client.get(f"/atlas/summary/{node_id}")
    assert resp.status_code == 404


def _node(nid: str, ntype: str, label: str | None = None) -> dict:
    return {"id": nid, "type": ntype, "label": label or nid}


def _edge(source: str, relation: str, target: str, family: str, conf: float = 0.9) -> dict:
    return {
        "id": edge_id(source, relation, target),
        "source_id": source,
        "target_id": target,
        "relation": relation,
        "family": family,
        "confidence": conf,
        "origin": "observed",
        "status": "active",
    }


@pytest.fixture
def synthetic_store(restore_graph, monkeypatch):
    """A disease with many papers, people, trials and genes, plus a node that is both a direct
    neighbour and the end of a chain."""
    nodes = [_node("D:1", "disease", "Disease One"), _node("G:1", "gene", "GENE1")]
    edges = [_edge("D:1", "caused_by_variant_in", "G:1", "dna")]
    for i in range(15):
        nodes += [_node(f"P:{i}", "paper"), _node(f"NCT{i}", "trial"), _node(f"S:{i}", "phenotype")]
        edges += [
            _edge(f"P:{i}", "about", "D:1", "research"),
            _edge(f"NCT{i}", "studies", "D:1", "research"),
            _edge("D:1", "has_phenotype", f"S:{i}", "symptoms"),
        ]
    # R:0 wrote 3 papers, R:1 two, R:2 one; R:2 also writes about the gene.
    for r, papers in enumerate([3, 2, 1]):
        nodes.append(_node(f"R:{r}", "researcher", f"Researcher {r}"))
        edges += [_edge(f"R:{r}", "authored", f"P:{p}", "research") for p in range(papers)]
    nodes += [_node("P:gene", "paper"), _node("ORG:1", "patient_org"), _node("REG:1", "registry")]
    edges += [
        _edge("P:gene", "about", "G:1", "research"),
        _edge("R:2", "authored", "P:gene", "research"),
        _edge("ORG:1", "serves", "D:1", "community"),
        _edge("REG:1", "studies", "D:1", "research"),
        _edge("ORG:1", "runs", "REG:1", "community"),
    ]
    store = graph_service.build_store(nodes=nodes, edges=edges)
    graph_service.set_graph(store)
    monkeypatch.setattr(atlas_tree, "ancestors", lambda node_id: [])
    return store


def test_synthetic_ranking_dedup_and_explain_spread(synthetic_store):
    store = synthetic_store
    summary = summary_service.atlas_summary("D:1", Lens(role=Role.guest))

    researchers = _section(summary, SummarySectionKey.researchers).items
    assert [(i.id, i.score) for i in researchers] == [("R:0", 3), ("R:1", 2), ("R:2", 2)]
    assert researchers[0].via_label == "via 3 papers"
    assert researchers[2].via_label == "via 1 paper and gene GENE1"
    assert researchers[2].hops == 2  # the 2-hop paper chain beats the 3-hop gene chain

    papers = _section(summary, SummarySectionKey.papers)
    assert papers.total == 15 and len(papers.items) == 10

    org = _section(summary, SummarySectionKey.patient_orgs).items
    assert [(i.id, i.hops, i.score) for i in org] == [("ORG:1", 1, 2)]
    assert org[0].via_label == "direct link, also via registry REG:1"

    explain = summary.explain_edge_ids
    assert len(explain) == 20 and len(set(explain)) == 20
    sections_covered = {
        s.key for s in summary.sections for i in s.items if i.via and set(i.via) <= set(explain)
    }
    assert {
        SummarySectionKey.genes,
        SummarySectionKey.symptoms,
        SummarySectionKey.researchers,
        SummarySectionKey.papers,
        SummarySectionKey.trials,
        SummarySectionKey.patient_orgs,
        SummarySectionKey.registries,
    } <= sections_covered
    # the first round takes the top item of every section, in section order
    tops = [s.items[0].via for s in summary.sections]
    flat = [e for via in tops for e in dict.fromkeys(via)]
    assert explain[: len(dict.fromkeys(flat))] == list(dict.fromkeys(flat))
    assert all(store.edges[e] for e in explain)
