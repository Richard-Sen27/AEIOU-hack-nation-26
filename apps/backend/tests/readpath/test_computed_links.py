"""Computed (inferred) links: new relations and tier, and the one-line explanation on every edge
payload. Synthetic graph only; the demo fixture is not touched."""

import pytest

from backend.api.services import graph as graph_service
from backend.api.services.chat.tools import _edge_view
from backend.api.services.explanation.pathdata import PathData
from backend.api.services.explanation.templates import (
    RELATION_PHRASES,
    TIER_WORDS,
    template_explanation,
)
from backend.api.services.path import _RELATION_PHRASES
from backend.schemas.enums import (
    RELATION_FAMILY,
    SYMMETRIC_RELATIONS,
    TIER_WEIGHTS,
    EdgeFamily,
    EvidenceTier,
    Polarity,
    Relation,
    Role,
    compute_confidence,
    edge_id,
)
from backend.schemas.graph import Edge, Evidence

D1, D2, D3 = "MONDO:9990001", "MONDO:9990002", "MONDO:9990003"
G1, G2 = "HGNC:99901", "HGNC:99902"
HP = "HP:9990001"

WHY_GENE = "Both are linked to variants in GENEA (ClinVar; HPO); a shared mechanism is unproven."
WHY_NEAR = "GENEA and GENEB lie 120 kb apart on chr9q34.11. Closeness alone is weak evidence."

NEW_RELATIONS = (
    Relation.shared_gene,
    Relation.near_on_chromosome,
    Relation.candidate_phenotype,
    Relation.suggested_by_neighbour,
)


def _node(nid: str, ntype: str, label: str) -> dict:
    return {"id": nid, "type": ntype, "label": label}


def _edge(source: str, relation: Relation, target: str, confidence: float, **extra) -> dict:
    return {
        "id": edge_id(source, relation, target),
        "source_id": source,
        "target_id": target,
        "relation": relation,
        "family": RELATION_FAMILY[relation],
        "confidence": confidence,
        "origin": extra.pop("origin", "inferred"),
        "status": "active",
        "data_version": "synthetic",
        **extra,
    }


SHARED_GENE = _edge(
    D1, Relation.shared_gene, D2, 0.68, features={"explanation": f"  {WHY_GENE} ", "gene": G1}
)
NEAR = _edge(G1, Relation.near_on_chromosome, G2, 0.2, features={"explanation": WHY_NEAR})
CAUSAL = _edge(D1, Relation.caused_by_variant_in, G1, 0.9, origin="observed")
PHENO = _edge(D3, Relation.candidate_phenotype, HP, 0.4, features={"explanation": "   "})
NEIGHBOUR = _edge(D3, Relation.suggested_by_neighbour, D1, 0.45, features={"method": "x"})


@pytest.fixture
def synthetic(restore_graph):
    store = graph_service.build_store(
        nodes=[
            _node(D1, "disease", "Disease One"),
            _node(D2, "disease", "Disease Two"),
            _node(D3, "disease", "Disease Three"),
            _node(G1, "gene", "GENEA"),
            _node(G2, "gene", "GENEB"),
            _node(HP, "phenotype", "Chronic cough"),
        ],
        edges=[SHARED_GENE, NEAR, CAUSAL, PHENO, NEIGHBOUR],
    )
    graph_service.set_graph(store)
    return store


def test_new_relations_have_families_phrases_and_symmetry():
    assert set(RELATION_FAMILY) == set(Relation)
    assert RELATION_FAMILY[Relation.shared_gene] == EdgeFamily.dna
    assert RELATION_FAMILY[Relation.near_on_chromosome] == EdgeFamily.dna
    assert RELATION_FAMILY[Relation.candidate_phenotype] == EdgeFamily.symptoms
    assert RELATION_FAMILY[Relation.suggested_by_neighbour] == EdgeFamily.symptoms
    assert {Relation.shared_gene, Relation.near_on_chromosome} <= SYMMETRIC_RELATIONS
    assert Relation.suggested_by_neighbour not in SYMMETRIC_RELATIONS
    assert edge_id(G2, Relation.near_on_chromosome, G1) == edge_id(G1, "near_on_chromosome", G2)
    for relation in NEW_RELATIONS:
        assert relation in _RELATION_PHRASES
        assert all(relation.value in RELATION_PHRASES[lang] for lang in ("en", "de"))


def test_computed_tier_has_weight_and_words():
    assert EvidenceTier.computed in TIER_WEIGHTS
    assert set(TIER_WEIGHTS) == set(EvidenceTier)
    assert TIER_WEIGHTS[EvidenceTier.computed] < 0.8  # a hypothesis never reaches "High"
    assert "hypothesis" in TIER_WORDS["computed"]


def test_edge_explanation_comes_from_features():
    def edge(features):
        return Edge.model_validate({**NEIGHBOUR, "features": features, "confidence_level": "low"})

    assert edge({"explanation": f" {WHY_NEAR} "}).explanation == WHY_NEAR
    assert edge({"explanation": "  "}).explanation is None
    assert edge({"explanation": 3}).explanation is None
    assert edge(None).explanation is None


def test_computed_rows_share_the_link_score():
    def row(i: int, tier: EvidenceTier) -> Evidence:
        return Evidence(
            id=i,
            edge_id="e_x",
            tier=tier,
            tier_weight=TIER_WEIGHTS[tier],
            source_type="analysis",
            polarity=Polarity.supports,
        )

    for n in (1, 2, 3):
        rows = [row(i, EvidenceTier.computed) for i in range(n)]
        graph_service._weight_computed_rows(rows, 0.42)
        assert compute_confidence([r.tier_weight for r in rows], 0) == pytest.approx(0.42, abs=1e-5)
    rows = [row(0, EvidenceTier.computed), row(1, EvidenceTier.curated_db)]
    graph_service._weight_computed_rows(rows, 0.95)
    assert rows[0].tier_weight == TIER_WEIGHTS[EvidenceTier.computed]  # capped at the ceiling
    assert rows[1].tier_weight == TIER_WEIGHTS[EvidenceTier.curated_db]


async def test_neighbourhood_and_evidence_expose_explanation(client, synthetic):
    hood = (await client.get(f"/neighborhood/{D1}")).json()
    edges = {e["id"]: e for e in hood["edges"]}
    assert edges[SHARED_GENE["id"]]["explanation"] == WHY_GENE
    assert edges[SHARED_GENE["id"]]["relation"] == "shared_gene"
    assert edges[CAUSAL["id"]]["explanation"] is None
    assert edges[NEIGHBOUR["id"]]["explanation"] is None

    body = (await client.get(f"/edge/{NEAR['id']}/evidence")).json()
    assert body["edge"]["explanation"] == WHY_NEAR
    assert body["edge"]["family"] == "dna"


async def test_atlas_payloads_expose_explanation(client, synthetic):
    atlas = {e["id"]: e for e in (await client.get("/atlas.json")).json()["edges"]}
    assert atlas[SHARED_GENE["id"]]["explanation"] == WHY_GENE
    assert atlas[CAUSAL["id"]]["explanation"] is None

    tree = {e["id"]: e for e in (await client.get("/atlas/tree.json")).json()["edges"]}
    assert tree[NEAR["id"]]["explanation"] == WHY_NEAR
    assert tree[PHENO["id"]]["explanation"] is None


async def test_summary_item_explains_a_single_inferred_link(client, synthetic):
    body = (await client.get(f"/atlas/summary/{D2}", params={"role": "patient"})).json()
    items = {i["id"]: i for s in body["sections"] for i in s["items"]}
    assert items[D1]["inferred"] is True and items[D1]["via"] == [SHARED_GENE["id"]]
    assert items[D1]["explanation"] == WHY_GENE

    body = (await client.get(f"/atlas/summary/{D1}", params={"role": "patient"})).json()
    items = {i["id"]: i for s in body["sections"] for i in s["items"]}
    assert items[G1]["inferred"] is False and items[G1]["explanation"] is None


async def test_path_steps_carry_explanation(client, synthetic):
    body = (await client.get("/path", params={"from": D2, "to": D1})).json()
    paths = body["paths"] or [body["coverage"]["closest_partial_path"]]
    steps = [s for p in paths for s in p["steps"] if s["edge"]["id"] == SHARED_GENE["id"]]
    assert steps and all(s["edge"]["explanation"] == WHY_GENE for s in steps)


def test_chat_edge_view_and_templates(synthetic):
    view = _edge_view(synthetic.edges[SHARED_GENE["id"]])
    assert view["explanation"] == WHY_GENE and view["origin"] == "inferred"
    assert "explanation" not in _edge_view(synthetic.edges[CAUSAL["id"]])

    near = synthetic.edges[NEAR["id"]]
    data = PathData(edge_ids=[near.id], edges={near.id: near}, nodes=dict(synthetic.nodes))
    text = template_explanation(data, Role.researcher, "en")
    assert "weak evidence" in text and "hypothesis" in text
