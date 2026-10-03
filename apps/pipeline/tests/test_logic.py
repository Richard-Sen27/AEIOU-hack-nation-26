import json

import polars as pl
import pytest
from backend.schemas.enums import edge_id

from pipeline import analytics, bio, build, linking, scope, validate
from pipeline.contracts import ASSERTION_SCHEMA, NODE_SCHEMA, SYNONYM_SCHEMA, assertion


def _nodes(*rows):
    return pl.DataFrame(
        [
            {"id": i, "type": t, "label": i, "description": None, "url": None, "attrs": "{}"}
            for i, t in rows
        ],
        schema=NODE_SCHEMA,
    )


def _assertions(rows):
    return pl.DataFrame(
        [
            {c: (json.dumps(r[c]) if isinstance(r[c], dict) else r[c]) for c in ASSERTION_SCHEMA}
            for r in rows
        ],
        schema=ASSERTION_SCHEMA,
    )


EMPTY_SYN = pl.DataFrame(schema=SYNONYM_SCHEMA)


# ---------------------------------------------------------------- Stage 4 confidence merge


def test_merge_combines_evidence_into_one_edge_with_confidence():
    nodes = _nodes(("MONDO:1", "disease"), ("HGNC:1", "gene"), ("HP:1", "phenotype"))
    rows = [
        assertion(
            "MONDO:1",
            "HGNC:1",
            "caused_by_variant_in",
            tier="curated_db",
            source_type="clinvar",
            source_ref="a",
        ),
        assertion(
            "MONDO:1",
            "HGNC:1",
            "caused_by_variant_in",
            tier="peer_reviewed",
            source_type="pubmed",
            source_ref="PMID:1",
        ),
        assertion(
            "MONDO:1",
            "HGNC:1",
            "caused_by_variant_in",
            tier="peer_reviewed",
            source_type="pubmed",
            source_ref="PMID:2",
            polarity="contradicts",
        ),
        # exact duplicate evidence must not count twice
        assertion(
            "MONDO:1",
            "HGNC:1",
            "caused_by_variant_in",
            tier="curated_db",
            source_type="clinvar",
            source_ref="a",
        ),
        assertion(
            "MONDO:1",
            "HP:1",
            "has_phenotype",
            tier="llm_inferred",
            source_type="pubmed",
            source_ref="PMID:3",
        ),
    ]
    t = build.merge(nodes, EMPTY_SYN, _assertions(rows))
    e = {r["relation"]: r for r in t["edges"].iter_rows(named=True)}
    cbv = e["caused_by_variant_in"]
    assert cbv["id"] == edge_id("MONDO:1", "caused_by_variant_in", "HGNC:1")
    # 1 - (0.1 * 0.3) - 0.1 * 1
    assert cbv["confidence"] == pytest.approx(0.87)
    assert cbv["n_evidence"] == 3 and cbv["family"] == "dna"
    assert e["has_phenotype"]["confidence"] == pytest.approx(0.3)
    assert t["evidence"].height == 4


def test_merge_symmetric_relations_share_one_edge_and_weight_override():
    nodes = _nodes(("MONDO:1", "disease"), ("MONDO:2", "disease"))
    rows = [
        assertion(
            "MONDO:2",
            "MONDO:1",
            "similar_symptoms",
            tier="curated_db",
            source_type="hpo",
            origin="inferred",
            features={"weight": 0.5, "score": 0.5},
        ),
        assertion(
            "MONDO:1",
            "MONDO:2",
            "similar_symptoms",
            tier="curated_db",
            source_type="orphanet",
            origin="inferred",
            features={"weight": 0.5, "score": 0.5},
        ),
    ]
    t = build.merge(nodes, EMPTY_SYN, _assertions(rows))
    assert t["edges"].height == 1
    edge = t["edges"].row(0, named=True)
    assert (edge["source_id"], edge["target_id"]) == ("MONDO:1", "MONDO:2")
    assert edge["confidence"] == pytest.approx(0.75)
    assert edge["origin"] == "inferred"
    assert "weight" not in json.loads(edge["features"])


def test_merge_drops_unknown_endpoints_and_prunes_orphans():
    nodes = _nodes(("MONDO:1", "disease"), ("HGNC:1", "gene"), ("HP:9", "phenotype"))
    rows = [
        assertion("MONDO:1", "HGNC:1", "caused_by_variant_in", tier="curated_db", source_type="x"),
        assertion(
            "MONDO:1", "HGNC:404", "caused_by_variant_in", tier="curated_db", source_type="x"
        ),
    ]
    t = build.merge(nodes, EMPTY_SYN, _assertions(rows))
    assert t["edges"].height == 1
    assert set(t["nodes"]["id"]) == {"MONDO:1", "HGNC:1"}


def test_people_pruning_keeps_connected_researchers_only():
    nodes = _nodes(
        ("RES:a", "researcher"),
        ("RES:b", "researcher"),
        ("RES:c", "researcher"),
        ("PMID:1", "paper"),
        ("PMID:2", "paper"),
        ("PMID:3", "paper"),
        ("MONDO:1", "disease"),
        ("MONDO:2", "disease"),
        ("INST:x", "institution"),
    )
    a = lambda s, r, t: assertion(s, t, r, tier="curated_db", source_type="pubmed")  # noqa: E731
    rows = [
        a("RES:a", "authored", "PMID:1"),
        a("RES:a", "authored", "PMID:2"),  # two works: kept
        a("RES:b", "authored", "PMID:3"),  # one paper about two diseases: kept
        a("RES:c", "authored", "PMID:1"),
        a("RES:c", "affiliated_with", "INST:x"),  # pruned
        a("PMID:1", "about", "MONDO:1"),
        a("PMID:2", "about", "MONDO:1"),
        a("PMID:3", "about", "MONDO:1"),
        a("PMID:3", "about", "MONDO:2"),
    ]
    t = build.merge(nodes, EMPTY_SYN, _assertions(rows))
    ids = set(t["nodes"]["id"])
    assert {"RES:a", "RES:b"} <= ids
    assert "RES:c" not in ids and "INST:x" not in ids


def test_version_bumps_only_on_change(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "VERSION_FILE", tmp_path / "v.json")
    v1 = build.assign_version("h1")
    assert build.assign_version("h1") == v1
    v2 = build.assign_version("h2")
    assert (
        v2.split(".")[0] == v1.split(".")[0] and int(v2.split(".")[1]) == int(v1.split(".")[1]) + 1
    )


# ---------------------------------------------------------------- id resolution


def test_resolve_gene_prefers_approved_symbol(monkeypatch):
    monkeypatch.setattr(bio, "gene_lookup", lambda: {"SCN1A": "HGNC:10585", "FHM3": "HGNC:10585"})
    assert bio.resolve_gene("scn1a") == "HGNC:10585"
    assert bio.resolve_gene("FHM3") == "HGNC:10585"
    assert bio.resolve_gene("HGNC:10588") == "HGNC:10588"
    assert bio.resolve_gene("NOTAGENE") is None


def test_clinvar_disease_ids(monkeypatch):
    monkeypatch.setattr(
        bio,
        "xref_to_mondo",
        lambda: {"OMIM:607208": "MONDO:0100079", "ORPHA:33069": "MONDO:0100135"},
    )
    ids = ["MONDO:MONDO:0100135", "OMIM:607208", "Orphanet:33069", "MedGen:C0000", "OMIM:999999"]
    assert bio.clinvar_disease_ids(ids) == ["MONDO:0100079", "MONDO:0100135"]


def test_resolve_disease_label_and_synonym():
    index = {"dravet syndrome": ["MONDO:0100135"], "sme": ["MONDO:0100135"]}
    assert scope.resolve_disease("Dravet Syndrome", index) == "MONDO:0100135"
    assert scope.resolve_disease("mondo:0000001", index) == "MONDO:0000001"
    assert scope.resolve_disease("unknown", index) is None


def test_trigram_similarity_ranks_close_names_first():
    pool = [
        ("MONDO:1", "Dravet syndrome"),
        ("MONDO:2", "Rett syndrome"),
        ("MONDO:3", "Doose syndrome"),
    ]
    c = linking.candidates("dravet syndrom", pool)
    assert c[0]["mondo_id"] == "MONDO:1"


# ---------------------------------------------------------------- variants and mechanism


@pytest.mark.parametrize(
    "name,expected",
    [
        ("NM_001165963.4(SCN1A):c.2792G>A (p.Arg931His)", "missense"),
        ("NM_001165963.4(SCN1A):c.664C>T (p.Arg222Ter)", "nonsense"),
        ("NM_001165963.4(SCN1A):c.1234del (p.Leu412fs)", "frameshift"),
        ("NM_001165963.4(SCN1A):c.264+1G>A", "splice"),
        ("NM_001165963.4(SCN1A):c.1000A>G (p.Lys334=)", "synonymous"),
    ],
)
def test_consequence(name, expected):
    assert bio.consequence(name, "single nucleotide variant") == expected


def test_classify_and_stars():
    assert bio.classify("Pathogenic/Likely pathogenic") == "likely_pathogenic"
    assert bio.classify("Uncertain significance") == "uncertain_significance"
    assert bio.classify("not provided") is None
    assert bio.review_stars("reviewed by expert panel") == 3


def test_select_variants_keeps_vus_and_caps():
    rows = [
        {
            "variation_id": str(i),
            "hgnc_id": "HGNC:1",
            "classification": "pathogenic",
            "stars": 1,
            "submitters": i,
            "phenotype_ids": [],
        }
        for i in range(10)
    ] + [
        {
            "variation_id": f"v{i}",
            "hgnc_id": "HGNC:1",
            "classification": "uncertain_significance",
            "stars": 0,
            "submitters": 1,
            "phenotype_ids": [],
        }
        for i in range(5)
    ]
    out = bio.select_variants(pl.DataFrame(rows), per_gene=6, vus=2)
    assert out.height == 6
    assert (out["classification"] == "uncertain_significance").sum() == 2


def test_clinvar_label_rules():
    assert analytics.clinvar_label({"n_pathogenic": 3, "truncating_share": 1.0})[0] is None
    assert (
        analytics.clinvar_label({"n_pathogenic": 40, "truncating_share": 0.6})[0]
        == "loss_of_function"
    )
    assert analytics.clinvar_label({"n_pathogenic": 40, "truncating_share": 0.0})[0] == "non_lof"
    assert analytics.clinvar_label({"n_pathogenic": 40, "truncating_share": 0.2})[0] is None


def test_compatible_mechanisms():
    assert analytics.compatible("loss_of_function", "loss_of_function") is True
    assert analytics.compatible("gain_of_function", "loss_of_function") is False
    assert analytics.compatible("non_lof", "loss_of_function") is False
    assert analytics.compatible("non_lof", "gain_of_function") is None


def test_same_gene_edges_separate_gof_and_lof():
    dg = {
        "MONDO:gof1": {"HGNC:2"},
        "MONDO:gof2": {"HGNC:2"},
        "MONDO:lof": {"HGNC:2"},
        "MONDO:x": {"HGNC:2"},
    }
    m = lambda mech: {"mechanism": mech, "basis": {"kind": "literature"}, "weight": 0.7}  # noqa: E731
    mech = {
        ("HGNC:2", "MONDO:gof1"): m("gain_of_function"),
        ("HGNC:2", "MONDO:gof2"): m("gain_of_function"),
        ("HGNC:2", "MONDO:lof"): m("loss_of_function"),
    }
    rows, unknown = analytics.same_gene_edges(dg, mech, {"HGNC:2": "SCN2A"})
    rel = {(r["source_id"], r["target_id"]): r["relation"] for r in rows}
    assert rel[("MONDO:gof1", "MONDO:gof2")] == "same_gene_same_mechanism"
    assert rel[("MONDO:gof1", "MONDO:lof")] == "same_gene_different_mechanism"
    assert rel[("MONDO:gof2", "MONDO:lof")] == "same_gene_different_mechanism"
    assert len(unknown) == 3  # MONDO:x has no mechanism


def test_clustering_never_joins_different_mechanism_pair():
    ds = ["A", "B", "C", "D"]
    f = lambda s: {"score": s}  # noqa: E731
    inferred = [
        {"source_id": "A", "target_id": "B", "relation": "similar_symptoms", "features": f(0.9)},
        {"source_id": "A", "target_id": "C", "relation": "similar_symptoms", "features": f(0.9)},
        {"source_id": "B", "target_id": "C", "relation": "similar_symptoms", "features": f(0.9)},
        {
            "source_id": "A",
            "target_id": "C",
            "relation": "same_gene_different_mechanism",
            "features": f(0.7),
        },
        {
            "source_id": "C",
            "target_id": "D",
            "relation": "same_gene_same_mechanism",
            "features": f(0.9),
        },
    ]
    m = analytics.cluster_diseases(ds, inferred, [])
    assert m["A"] != m["C"]


# ---------------------------------------------------------------- scope expansion


def test_expand_respects_eligibility_and_caps():
    gd = pl.DataFrame(
        {
            "mondo_id": ["M:seed", "M:a", "M:b", "M:common", "M:c"],
            "hgnc_id": ["G:1", "G:1", "G:2", "G:1", "G:2"],
        }
    )
    cfg = {"max_hops": 2, "via": ["shared_gene"], "max_new_per_hop": [5, 5], "max_diseases": 10}
    out = scope.expand({"M:seed"}, {"G:2"}, gd, cfg, eligible=lambda m: m != "M:common")
    assert "M:common" not in out
    assert out["M:a"]["hop"] == 1 and out["M:b"]["hop"] == 0


def test_next_version():
    v = scope.next_version(None, "h", None)
    assert v.endswith(".1")
    assert scope.next_version(v, "h", "h") == v
    assert scope.next_version(v, "h2", "h").endswith(".2")


# ---------------------------------------------------------------- validation rules


def _graph(edges, nodes, evidence, clusters=None):
    return {
        "nodes": pl.DataFrame(nodes),
        "edges": pl.DataFrame(edges),
        "evidence": pl.DataFrame(evidence),
        "synonyms": pl.DataFrame(
            {"node_id": [], "synonym": []}, schema={"node_id": pl.String, "synonym": pl.String}
        ),
    }


def _edge(s, r, t, conf=0.9, origin="observed", features=None):
    return {
        "id": edge_id(s, r, t),
        "source_id": s,
        "target_id": t,
        "relation": r,
        "family": "dna",
        "confidence": conf,
        "origin": origin,
        "status": "active",
        "features": features,
    }


def test_structure_checks_catch_missing_evidence_and_orphans():
    nodes = [
        {"id": "MONDO:1", "type": "disease", "cluster_id": "CLUSTER:1"},
        {"id": "HGNC:1", "type": "gene", "cluster_id": None},
        {"id": "HP:1", "type": "phenotype", "cluster_id": None},
        {"id": "CLUSTER:1", "type": "cluster", "cluster_id": "CLUSTER:1"},
    ]
    e = _edge("MONDO:1", "caused_by_variant_in", "HGNC:1")
    ev = [{"edge_id": "e_other", "tier": "curated_db"}]
    res = {r["check"]: r["ok"] for r in validate.check_structure(_graph([e], nodes, ev))}
    assert res["every edge has evidence"] is False
    assert res["no orphan nodes"] is False  # HP:1 (the cluster node is exempt)
    assert res["deterministic edge ids"] is True


def test_counterexample_check():
    nodes = [
        {"id": "MONDO:g", "type": "disease", "cluster_id": "CLUSTER:1"},
        {"id": "MONDO:l", "type": "disease", "cluster_id": "CLUSTER:2"},
    ]
    e = _edge(
        "MONDO:g", "same_gene_different_mechanism", "MONDO:l", origin="inferred", features="{}"
    )
    t = _graph([e], nodes, [{"edge_id": e["id"], "tier": "curated_db"}])
    resolve = lambda n: n  # noqa: E731
    case = {"gene": "SCN2A", "gain_of_function": ["MONDO:g"], "loss_of_function": ["MONDO:l"]}
    assert validate.check_counterexamples(t, resolve, [case])[0]["ok"]
    t["nodes"] = pl.DataFrame([{**n, "cluster_id": "CLUSTER:1"} for n in nodes])
    assert not validate.check_counterexamples(t, resolve, [case])[0]["ok"]


def test_golden_check_requires_supported_edge():
    e = _edge("MONDO:1", "caused_by_variant_in", "HGNC:1", conf=0.55)
    t = _graph([e], [{"id": "MONDO:1", "type": "disease"}, {"id": "HGNC:1", "type": "gene"}], [])
    fact = {"source": "MONDO:1", "relation": "caused_by_variant_in", "target": "HGNC:1"}
    assert not validate.check_golden(t, lambda n: n, [fact])[0]["ok"]
    t["edges"] = pl.DataFrame([{**e, "confidence": 0.9}])
    assert validate.check_golden(t, lambda n: n, [fact])[0]["ok"]


def test_stage3_report_counts():
    assert validate._report_counts({"accepted": 8, "rejected": {"quote_not_found": 2}}) == (
        10,
        8,
        2,
    )
    assert validate._report_counts({"checked": 5, "passed": 4, "rejected": 1}) == (5, 4, 1)
