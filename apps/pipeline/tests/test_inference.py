"""Computed links: corpus IC, the shared similarity, proximity, shared gene precedence, caps and
explanations. Toy ontologies and synthetic coordinates only; no cached data is read."""

import json
import math

import polars as pl
import pytest
from backend.phenotype_similarity import phenotype_similarity

from pipeline import analytics, build, hpo_sim, validate
from pipeline.contracts import ASSERTION_SCHEMA, NODE_SCHEMA, SYNONYM_SCHEMA

# HP:R
# ├── HP:N  nervous
# │   ├── HP:S  seizure
# │   │   ├── HP:F  focal seizure
# │   │   └── HP:I  infantile spasms
# │   └── HP:A  ataxia
# └── HP:E  eye
#     ├── HP:Y  nystagmus
#     └── HP:P  ptosis
PARENTS = {
    "HP:R": [],
    "HP:N": ["HP:R"],
    "HP:S": ["HP:N"],
    "HP:F": ["HP:S"],
    "HP:I": ["HP:S"],
    "HP:A": ["HP:N"],
    "HP:E": ["HP:R"],
    "HP:Y": ["HP:E"],
    "HP:P": ["HP:E"],
}
LABELS = {
    "HP:F": "Focal seizure",
    "HP:I": "Infantile spasms",
    "HP:A": "Ataxia",
    "HP:Y": "Nystagmus",
    "HP:P": "Ptosis",
    "HP:S": "Seizure",
}


def _corpus(n_filler: int = 40) -> hpo_sim.Corpus:
    """Corpus where seizures are common, the leaf terms rare (IC well above 2)."""
    ann: dict[str, dict[str, float | None]] = {
        "D:1": {"HP:F": 0.9, "HP:I": 0.9, "HP:Y": 0.5},
        "D:2": {"HP:F": 0.8, "HP:I": None, "HP:P": 0.3},
        "D:3": {"HP:A": 1.0},
    }
    for i in range(n_filler):
        ann[f"D:fill{i}"] = {"HP:S": None} if i % 2 else {"HP:N": None}
    return hpo_sim.corpus_from(ann, PARENTS, LABELS)


def test_corpus_ic_counts_descendants_and_fills_unannotated_terms():
    c = _corpus()
    n = c.n_diseases
    assert n == 43
    assert c.counts["HP:S"] == 2 + 20  # D:1, D:2 via leaves + 20 fillers
    assert c.ic["HP:S"] == pytest.approx(-math.log(22 / n))
    assert c.ic["HP:R"] == 0.0
    assert c.ic["HP:F"] == pytest.approx(-math.log(2 / n))
    assert c.ic["HP:E"] < c.ic["HP:Y"]  # monotone along is_a
    # every ontology term has an IC; never annotated -> as specific as a single disease
    assert set(PARENTS) <= set(c.ic)
    assert c.annotations["D:2"]["HP:I"] == 0.5  # unknown frequency -> 0.5


def test_similarity_frequency_ic_symmetry_and_range_on_corpus_ic():
    c = _corpus()

    def sim(a, b):
        return phenotype_similarity(a, b, c.ic, c.ancestors)

    b = {"HP:Y": 1.0}
    assert sim({"HP:Y": 0.9, "HP:A": 0.1}, b) > sim({"HP:Y": 0.1, "HP:A": 0.9}, b)
    assert sim({"HP:F": 1, "HP:A": 1}, {"HP:F": 1, "HP:P": 1}) > sim(
        {"HP:S": 1, "HP:A": 1}, {"HP:S": 1, "HP:P": 1}
    )
    a, b = c.annotations["D:1"], c.annotations["D:2"]
    assert sim(a, b) == pytest.approx(sim(b, a))
    for x in c.annotations.values():
        for y in list(c.annotations.values())[:5]:
            assert 0.0 <= sim(x, y) <= 1.0


def test_symptom_similarity_names_only_terms_both_record():
    c = _corpus()
    dterms = {
        "MONDO:1": {"HP:F": 0.9, "HP:I": 0.9, "HP:Y": 0.5},
        "MONDO:2": {"HP:F": 0.8, "HP:I": None, "HP:P": 0.3},
        "MONDO:3": {"HP:A": 1.0, "HP:Y": 0.2, "HP:N": None},
    }
    rows, cal = analytics.symptom_similarity(sorted(dterms), dterms, c, calibrate=False)
    pairs = {(r["source_id"], r["target_id"]): r for r in rows}
    assert set(pairs) == {("MONDO:1", "MONDO:2")}
    r = pairs[("MONDO:1", "MONDO:2")]
    f = r["features"]
    assert f["explanation"].startswith(
        "Similar symptom profile: both list Focal seizure and Infantile spasms (2 of 4 specific"
    )
    assert "Nystagmus" not in f["explanation"] and "Ptosis" not in f["explanation"]
    assert f["shared_specific"] == 2 and f["specific_total"] == 4
    assert f["score"] == pytest.approx(min(0.30 + 0.55 * f["similarity"], 0.75), abs=1e-4)
    assert f["score"] <= 0.75
    assert cal == {"threshold": analytics.SYM_THRESHOLD}


def test_symptom_similarity_needs_two_shared_specific_terms():
    c = _corpus()
    dterms = {
        "MONDO:1": {"HP:F": 1.0, "HP:Y": 1.0, "HP:A": 1.0},
        "MONDO:2": {"HP:F": 1.0, "HP:P": 1.0, "HP:A": 1.0},
        "MONDO:3": {"HP:I": 1.0, "HP:P": 1.0, "HP:N": 1.0},
    }
    rows, _ = analytics.symptom_similarity(sorted(dterms), dterms, c, calibrate=False)
    assert {(r["source_id"], r["target_id"]) for r in rows} == {("MONDO:1", "MONDO:2")}
    dterms["MONDO:2"] = {"HP:F": 1.0, "HP:P": 1.0, "HP:I": 1.0}  # only Focal seizure shared
    rows, _ = analytics.symptom_similarity(sorted(dterms), dterms, c, calibrate=False)
    assert ("MONDO:1", "MONDO:2") not in {(r["source_id"], r["target_id"]) for r in rows}


def test_calibration_raises_threshold_to_random_p95():
    ann = {f"D:{i}": {"HP:F": 1.0, "HP:I": 1.0, "HP:Y": 1.0} for i in range(6)}
    c = hpo_sim.corpus_from(ann | {"D:x": {"HP:A": 1.0}}, PARENTS, LABELS)
    cal = analytics.similarity_calibration(c, 0.45, [0.2, 0.9], n_pairs=10)
    assert cal["random_p95"] == pytest.approx(1.0)
    assert cal["threshold"] >= cal["random_p95"] and cal["threshold"] == pytest.approx(1.0)
    assert 0 <= cal["threshold_percentile_random"] <= 100


# ---------------------------------------------------------------- proximity


def _gene(symbol, chrom, start, end, band):
    return {"symbol": symbol, "chromosome": chrom, "start": start, "end": end, "cytoband": band}


GENES = {
    "HGNC:1": _gene("AAA", "9", 1_000_000, 1_050_000, "9q34.11"),
    "HGNC:2": _gene("BBB", "9", 1_170_000, 1_200_000, "9q34.11"),  # 120 kb from AAA
    "HGNC:3": _gene("CCC", "9", 1_040_000, 1_060_000, "9q34.11"),  # overlaps AAA
    "HGNC:4": _gene("DDD", "9", 3_500_000, 3_600_000, "9q34.13"),  # > 1 Mb from all
    "HGNC:5": _gene("EEE", "2", 1_100_000, 1_150_000, "2p25.3"),  # other chromosome
    "HGNC:6": _gene("FFF", "9", 1_900_000, 1_950_000, "9q34.12"),  # 700 kb from BBB
    "HGNC:7": _gene("GGG", "9", 2_000_000, 2_010_000, "9q34.12"),
    "HGNC:8": _gene("HHH", "9", 2_020_000, 2_030_000, "9q34.12"),
    "HGNC:9": {"symbol": "III", "chromosome": "9", "cytoband": "9q34.12"},  # no coordinates
    "HGNC:10": {"symbol": "MT-X", "chromosome": "MT", "cytoband": None},
}


def _near(cnvs=None):
    rows = analytics.near_edges(GENES, cnvs)
    return {(r["source_id"], r["target_id"]): r for r in rows}


def test_near_on_chromosome_gap_limit_and_nearest_three():
    near = _near()
    assert ("HGNC:1", "HGNC:2") in near
    assert ("HGNC:1", "HGNC:3") in near
    assert not any("HGNC:4" in k for k in near)  # more than 1 Mb away
    assert not any("HGNC:5" in k for k in near)  # other chromosome
    assert not any("HGNC:10" in k for k in near)  # mitochondrial
    for g in GENES:
        if GENES[g].get("start") is None:
            continue
        nearest = sorted(
            (analytics._gap(GENES[g], GENES[h]), h)
            for h in GENES
            if h != g
            and GENES[h].get("chromosome") == GENES[g]["chromosome"]
            and GENES[h].get("start") is not None
        )
        mine = [h for _, h in nearest if tuple(sorted((g, h))) in near]
        # a gene's own 3 nearest within 1 Mb are always linked
        within = [h for d, h in nearest if d <= analytics.NEAR_MAX_GAP_BP][:3]
        assert set(within) <= set(mine)
    f = near[("HGNC:1", "HGNC:2")]["features"]
    assert f["gap_bp"] == 120_000 and f["score"] == analytics.NEAR_CONFIDENCE
    assert f["explanation"].startswith("AAA and BBB lie 120 kb apart on chromosome 9 (9q34.11).")
    assert "weak evidence" in f["explanation"]
    assert near[("HGNC:1", "HGNC:3")]["features"]["explanation"].startswith(
        "AAA and CCC overlap on chromosome 9"
    )


def test_near_on_chromosome_cytoband_fallback_and_copy_number_boost():
    near = _near()
    fallback = [k for k in near if "HGNC:9" in k]
    assert fallback and all(near[k]["features"]["basis"] == "cytoband" for k in fallback)
    assert "exact positions not available" in near[fallback[0]]["features"]["explanation"]
    cnv = {
        "type": "copy number loss",
        "chromosome": "9",
        "start": 1_010_000,
        "stop": 1_180_000,
        "assembly": "GRCh38",
    }
    boosted = _near([cnv, dict(cnv, start=1_020_000)])
    f = boosted[("HGNC:1", "HGNC:2")]["features"]
    assert f["score"] == analytics.NEAR_CNV_CONFIDENCE
    assert (
        f["n_spanning_cnv"] == 2
        and "copy-number changes in ClinVar span both" in (f["explanation"])
    )
    one = _near([cnv])[("HGNC:1", "HGNC:2")]["features"]
    assert one["score"] == analytics.NEAR_CONFIDENCE  # a single CNV is not enough


# ---------------------------------------------------------------- shared gene precedence


def _mech(m):
    return {"mechanism": m, "basis": {"kind": "orphanet"}, "weight": 0.85}


def test_shared_gene_only_where_no_same_gene_mechanism_link():
    dg = {
        "MONDO:a": {"HGNC:1"},
        "MONDO:b": {"HGNC:1"},
        "MONDO:c": {"HGNC:1", "HGNC:2"},
        "MONDO:d": {"HGNC:2"},
    }
    mech = {("HGNC:1", "MONDO:a"): _mech("loss_of_function")}
    mech[("HGNC:1", "MONDO:b")] = _mech("gain_of_function")
    same, unknown = analytics.same_gene_edges(dg, mech, {"HGNC:1": "GENEA"})
    assert {(r["source_id"], r["target_id"]) for r in same} == {("MONDO:a", "MONDO:b")}
    covered = {tuple(sorted((r["source_id"], r["target_id"]))) for r in same}
    causal = {
        (d, g): {"confidence": 0.9, "sources": ["orphanet"]} for d, gs in dg.items() for g in gs
    }
    causal[("MONDO:d", "HGNC:2")] = {"confidence": 0.7, "sources": ["clinvar"]}
    rows = analytics.shared_gene_edges(dg, covered, causal, {"HGNC:1": "GENEA", "HGNC:2": "GENEB"})
    pairs = {(r["source_id"], r["target_id"]): r for r in rows}
    assert ("MONDO:a", "MONDO:b") not in pairs  # has a same_gene_different_mechanism link
    assert set(pairs) == {("MONDO:a", "MONDO:c"), ("MONDO:b", "MONDO:c"), ("MONDO:c", "MONDO:d")}
    cd = pairs[("MONDO:c", "MONDO:d")]["features"]
    assert cd["gene_symbol"] == "GENEB"
    assert cd["score"] == pytest.approx(0.7 * analytics.SHARED_GENE_FACTOR)
    assert cd["explanation"] == (
        "Both are linked to variants in GENEB (sources: ClinVar and Orphanet); whether they "
        "share a mechanism is not established."
    )


def test_shared_gene_skips_genes_linked_to_many_diseases():
    dg = {f"MONDO:{i:02d}": {"HGNC:9"} for i in range(analytics.SHARED_GENE_MAX_DISEASES + 1)}
    causal = {(d, "HGNC:9"): {"confidence": 0.9, "sources": []} for d in dg}
    assert analytics.shared_gene_edges(dg, set(), causal, {}) == []


# ---------------------------------------------------------------- caps, weights, explanations


def _nodes(*ids):
    return pl.DataFrame(
        [
            {"id": i, "type": t, "label": i, "description": None, "url": None, "attrs": "{}"}
            for i, t in ids
        ],
        schema=NODE_SCHEMA,
    )


def _table(rows):
    return pl.DataFrame(
        [
            {c: (json.dumps(r[c]) if isinstance(r[c], dict) else r[c]) for c in ASSERTION_SCHEMA}
            for r in rows
        ],
        schema=ASSERTION_SCHEMA,
    )


def _row(src, tgt, rel, score, ref="x"):
    return analytics._inferred(
        src,
        tgt,
        rel,
        score=score,
        explanation="One line.",
        method="m",
        confidence_basis="b",
        source_type="analytics",
        source_ref=ref,
    )


def test_caps_and_weight_shares_give_the_link_score():
    rows = [
        _row("HGNC:1", "HGNC:2", "near_on_chromosome", 0.9),
        _row("MONDO:1", "MONDO:2", "shared_pathway", 0.5, "p1"),
        _row("MONDO:1", "MONDO:2", "shared_pathway", 0.5, "p2"),
        _row("MONDO:1", "MONDO:2", "shared_pathway", 0.5, "p3"),
        _row("MONDO:1", "MONDO:3", "shared_gene", 0.95),
    ]
    analytics.finalize_inferred(rows)
    nodes = _nodes(
        ("HGNC:1", "gene"),
        ("HGNC:2", "gene"),
        ("MONDO:1", "disease"),
        ("MONDO:2", "disease"),
        ("MONDO:3", "disease"),
    )
    t = build.merge(nodes, pl.DataFrame(schema=SYNONYM_SCHEMA), _table(rows))
    conf = {r["relation"]: r["confidence"] for r in t["edges"].iter_rows(named=True)}
    assert conf["near_on_chromosome"] == pytest.approx(0.45)
    assert conf["shared_pathway"] == pytest.approx(0.5, abs=1e-5)
    assert conf["shared_gene"] == pytest.approx(build.INFERRED_CONFIDENCE_CAP)
    assert build.inferred_cap("candidate_phenotype") == 0.55
    assert build.inferred_cap("similar_symptoms") == build.INFERRED_CONFIDENCE_CAP
    assert set(t["evidence"]["tier"].to_list()) == {"computed"}
    assert set(t["evidence"]["claim_type"].to_list()) == {"hypothesis"}


def test_hypothesis_features_dropped_when_an_edge_is_also_observed():
    rows = [
        _row("HGNC:1", "MECH:loss_of_function", "acts_via", 0.7),
        {
            **_row("HGNC:1", "MECH:loss_of_function", "acts_via", 0.7, "orpha"),
            "origin": "observed",
            "tier": "curated_db",
            "claim_type": None,
            "features": {"disease": "MONDO:1"},
        },
    ]
    nodes = _nodes(("HGNC:1", "gene"), ("MECH:loss_of_function", "mechanism"))
    t = build.merge(nodes, pl.DataFrame(schema=SYNONYM_SCHEMA), _table(rows))
    e = t["edges"].row(0, named=True)
    assert e["origin"] == "observed"
    assert "explanation" not in json.loads(e["features"])


EXPLANATION_ENDINGS = (".",)


def _well_formed(rows):
    assert rows
    for r in rows:
        f = r["features"]
        assert r["tier"] == "computed" and r["claim_type"] == "hypothesis"
        assert r["origin"] == "inferred"
        text = f["explanation"]
        assert isinstance(text, str) and text.strip() == text and "\n" not in text
        assert text.endswith(EXPLANATION_ENDINGS) and len(text) <= 400
        assert isinstance(f["method"], str) and isinstance(f["confidence_basis"], str)
        for k, v in f.items():
            assert isinstance(v, str | int | float | type(None)), (k, v)  # flat features
        for word in ("you have", "diagnos", "causes "):
            assert word not in text.lower()


def test_explanations_present_and_well_formed_for_every_relation():
    dg = {"MONDO:a": {"HGNC:1"}, "MONDO:b": {"HGNC:1"}, "MONDO:c": {"HGNC:1"}}
    mech = {
        ("HGNC:1", "MONDO:a"): _mech("loss_of_function"),
        ("HGNC:1", "MONDO:b"): _mech("loss_of_function"),
        ("HGNC:1", "MONDO:c"): _mech("gain_of_function"),
    }
    same, _ = analytics.same_gene_edges(dg, mech, {"HGNC:1": "GENEA"}, {"MONDO:a": "Alpha"})
    _well_formed(same)
    _well_formed(analytics.near_edges(GENES))
    c = _corpus()
    dterms = {
        "MONDO:1": {"HP:F": 0.9, "HP:I": 0.9, "HP:Y": 0.5},
        "MONDO:2": {"HP:F": 0.8, "HP:I": None, "HP:P": 0.3},
    }
    _well_formed(analytics.symptom_similarity(sorted(dterms), dterms, c, calibrate=False)[0])
    causal = {
        (d, "HGNC:2"): {"confidence": 0.9, "sources": ["hpo"]} for d in ("MONDO:x", "MONDO:y")
    }
    _well_formed(analytics.shared_gene_edges({d: {"HGNC:2"} for d, _ in causal}, set(), causal, {}))
    stats = {"n_pathogenic": 40, "truncating": 30, "missense": 5, "truncating_share": 0.75}
    acts = analytics.gene_mechanism_edges(None, {"HGNC:1": stats}, {}, {"HGNC:1": "GENEA"})
    _well_formed([r for r in acts if r["origin"] == "inferred"])
    assert acts[0]["features"]["explanation"].startswith(
        "30 of 40 pathogenic or likely pathogenic ClinVar variants in GENEA are truncating"
    )


def test_pathway_edges_explain_with_genes_and_pathway():
    nodes = pl.DataFrame(
        [
            {
                "id": "REACT:R-1",
                "type": "pathway",
                "label": "Small pathway",
                "attrs": '{"n_genes": 10}',
            },
            {"id": "HGNC:1", "type": "gene", "label": "GENEA", "attrs": "{}"},
            {"id": "HGNC:2", "type": "gene", "label": "GENEB", "attrs": "{}"},
        ]
    )
    edges = pl.DataFrame(
        {
            "source_id": ["HGNC:1", "HGNC:2"],
            "target_id": ["REACT:R-1", "REACT:R-1"],
            "relation": ["participates_in", "participates_in"],
        }
    )
    dg = {"MONDO:1": {"HGNC:1"}, "MONDO:2": {"HGNC:2"}}
    rows = analytics.pathway_edges(dg, edges, nodes, {"HGNC:1": "GENEA", "HGNC:2": "GENEB"})
    _well_formed(rows)
    f = rows[0]["features"]
    assert f["explanation"] == (
        "Their linked genes GENEA and GENEB both take part in Small pathway (10 genes, Reactome)."
    )
    assert f["score"] == pytest.approx(analytics.PATHWAY_FACTOR * 0.9 / 2, abs=1e-4)
    assert f["cluster_score"] == pytest.approx(0.9 / 2, abs=1e-4)


def test_clustering_ignores_proximity_and_shared_gene_links():
    ds = ["A", "B", "C", "D"]
    f = lambda s: {"score": s}  # noqa: E731
    base = [
        {"source_id": "A", "target_id": "B", "relation": "similar_symptoms", "features": f(0.9)},
        {"source_id": "C", "target_id": "D", "relation": "similar_symptoms", "features": f(0.9)},
    ]
    extra = [
        {"source_id": a, "target_id": b, "relation": rel, "features": f(0.9)}
        for a, b in (("A", "C"), ("B", "D"), ("A", "D"), ("B", "C"))
        for rel in ("near_on_chromosome", "shared_gene")
    ]
    assert analytics.cluster_diseases(ds, base, []) == analytics.cluster_diseases(
        ds, base + extra, []
    )


# ---------------------------------------------------------------- validation


def _graph(rows):
    edges = pl.DataFrame(
        [
            {
                "id": f"e{i}",
                "relation": rel,
                "origin": "inferred",
                "confidence": conf,
                "features": json.dumps(feats),
            }
            for i, (rel, conf, feats) in enumerate(rows)
        ]
    )
    evidence = pl.DataFrame(
        {
            "edge_id": [f"e{i}" for i in range(len(rows))],
            "tier": ["computed"] * len(rows),
            "claim_type": ["hypothesis"] * len(rows),
        }
    )
    return {"edges": edges, "evidence": evidence}


GOOD = {"explanation": "Why.", "method": "m", "confidence_basis": "b"}
CAL = {
    "similar_symptoms_calibration": {
        "threshold": 0.45,
        "random_p95": 0.4,
        "threshold_percentile_random": 97.0,
    }
}


def _checks(rows, summary=CAL):
    return {r["check"]: r["ok"] for r in validate.check_inferred(_graph(rows), summary)}


def test_check_inferred_passes_good_and_catches_each_problem():
    assert all(
        _checks([("similar_symptoms", 0.7, GOOD), ("near_on_chromosome", 0.2, GOOD)]).values()
    )
    bad = _checks([("shared_gene", 0.7, {"method": "m", "confidence_basis": "b"})])
    assert not bad["every inferred edge has a one-line explanation, method and confidence basis"]
    multi = _checks([("shared_gene", 0.7, {**GOOD, "explanation": "a\nb"})])
    assert not multi["every inferred edge has a one-line explanation, method and confidence basis"]
    assert not _checks([("near_on_chromosome", 0.5, GOOD)])[
        "inferred edges stay within their relation's confidence cap"
    ]
    assert not _checks([("candidate_phenotype", 0.6, GOOD)])[
        "no proximity or candidate link can sit on a supported path"
    ]
    uncal = {"similar_symptoms_calibration": {"threshold": 0.3, "random_p95": 0.4}}
    assert not _checks([("similar_symptoms", 0.7, GOOD)], uncal)[
        "symptom similarity threshold calibrated against random pairs"
    ]
