"""Wide scope (stage A): the inclusion rule, focus-only fetching, tiers, candidate-only symptom
similarity, the HPO term export, template cluster labels, ClinVar splitting and the load SQL.
Synthetic data only; no cached data is read."""

import gzip
import io
import json
import random
from collections import defaultdict
from itertools import combinations

import numpy as np
import polars as pl
import pytest
from backend.phenotype_similarity import SPECIFIC_IC, closure, phenotype_similarity

from pipeline import analytics, bio, hpo_sim, scope, validate
from pipeline.contracts import Scope
from pipeline.extract import common
from pipeline.sources import clinvar

# ---------------------------------------------------------------- inclusion rule


def _terms(rows):
    base = {"rare": False, "exact_matches": [], "parents": [], "deprecated": False}
    return pl.DataFrame([{**base, **r} for r in rows], infer_schema_length=None)


def test_qualify_keeps_rare_diseases_with_gene_and_symptoms_and_reports_exclusions():
    rows = [
        {"id": "M:fop", "label": "fibrodysplasia ossificans progressiva", "rare": True},
        {"id": "M:omim", "label": "ciliary dyskinesia, primary, 25"},
        {"id": "M:orpha", "label": "some orphanet disorder"},
        {"id": "M:susc", "label": "asthma, susceptibility to, 1", "rare": True},
        {"id": "M:prot", "label": "malaria, protection against", "rare": True},
        {"id": "M:broad", "label": "broad epilepsy", "rare": True},
        {"id": "M:cancer", "label": "thyroid cancer, nonmedullary, 1"},
        {"id": "M:orphacancer", "label": "rare carcinoma"},
        {"id": "M:nogene", "label": "no gene disease", "rare": True},
        {"id": "M:nophen", "label": "no symptom disease", "rare": True},
        {"id": "M:withdrawn", "label": "withdrawn gene only", "rare": True},
        {"id": "M:dep", "label": "obsolete", "rare": True, "deprecated": True},
        {"id": "M:common", "label": "common thing"},
    ]
    # 31 children make M:broad a grouping term
    rows += [
        {"id": f"M:child{i}", "label": f"child {i}", "parents": ["M:broad"]} for i in range(31)
    ]
    terms = _terms(rows)
    approved = {"HGNC:1", "HGNC:2", "HGNC:3"}
    genes = [
        ("M:fop", "HGNC:1", "ORPHA:337"),
        ("M:fop", "HGNC:1", "OMIM:135100"),
        ("M:omim", "HGNC:2", "OMIM:615482"),
        ("M:orpha", "HGNC:3", "ORPHA:9"),
        ("M:susc", "HGNC:2", "OMIM:1"),
        ("M:prot", "HGNC:2", "OMIM:2"),
        ("M:broad", "HGNC:2", "ORPHA:10"),
        ("M:cancer", "HGNC:3", "OMIM:3"),
        ("M:orphacancer", "HGNC:3", "ORPHA:11"),
        ("M:nophen", "HGNC:3", "OMIM:4"),
        ("M:withdrawn", "HGNC:999", "OMIM:5"),
        ("M:dep", "HGNC:1", "OMIM:6"),
    ]
    keys = [("M:nogene", "ORPHA:12"), ("M:common", "OMIM:7")]
    phen = {m: {"HP:1"} for m, *_ in genes} | {"M:nogene": {"HP:1"}, "M:nophen": set()}
    keep, report = scope.qualify_diseases(terms, genes, keys, phen, approved)
    assert set(keep) == {"M:fop", "M:omim", "M:orpha", "M:orphacancer"}
    assert keep["M:fop"] == {"HGNC:1"}
    ex = report["excluded"]
    assert ex["susceptibility or protection label"]["n"] == 2
    assert ex["more than 30 MONDO descendants"]["n"] == 1
    assert ex["OMIM-only cancer or carcinoma"]["n"] == 1  # the ORPHA-keyed carcinoma stays
    assert report["left_out"]["mapped_without_approved_gene"] == 3  # nogene, withdrawn, common
    assert report["left_out"]["with_gene_without_phenotypes"] == 1
    assert report["left_out"]["withdrawn_gene_links"] == 1
    assert report["by_source"] == {"omim_and_orpha": 1, "omim_only": 1, "orpha_only": 2}
    assert report["diseases"] == 4 and report["genes"] == 3


def test_focus_disease_genes_prefers_qualifying_genes_and_skips_grouping_terms():
    gd = pl.DataFrame(
        {
            "mondo_id": ["M:a"] + ["M:group"] * 9 + ["M:b"],
            "hgnc_id": ["HGNC:9"] + [f"HGNC:{i}" for i in range(10, 19)] + ["HGNC:5"],
        }
    )
    out = scope.focus_disease_genes(["M:a", "M:group", "M:b"], {"M:a": {"HGNC:1"}}, gd, 8)
    assert out == {"HGNC:1", "HGNC:5"}


# ---------------------------------------------------------------- focus and tiers


def _scope(with_core: bool) -> Scope:
    genes = [{"hgnc_id": "HGNC:1", "symbol": "SCN1A", "aliases": [], "seed": True}]
    diseases = [{"mondo_id": "M:1", "label": "Dravet syndrome", "synonyms": [], "seed": True}]
    phen = [{"hpo_id": "HP:1", "label": "Seizure"}]
    if with_core:
        for e in genes + diseases + phen:
            e["focus"] = True
        genes.append({"hgnc_id": "HGNC:171", "symbol": "ACVR1", "aliases": [], "focus": False})
        diseases.append({"mondo_id": "M:2", "label": "FOP", "synonyms": [], "focus": False})
        phen.append({"hpo_id": "HP:2", "label": "Ectopic ossification", "focus": False})
    return Scope("v", genes, diseases, phen)


def test_focus_view_and_tiers():
    s = _scope(with_core=True)
    f = s.focus()
    assert f.disease_ids == {"M:1"} and f.gene_ids == {"HGNC:1"} and f.phenotype_ids == {"HP:1"}
    assert s.focus_gene_ids == {"HGNC:1"} and s.focus_disease_ids == {"M:1"}
    assert s.tier("M:1") == "focus" and s.tier("M:2") == "core"
    assert s.tier("HGNC:171") == "core" and s.tier("HP:2") == "core"
    assert s.tier("PMID:1") is None
    # entries written before tiers existed are focus
    assert _scope(with_core=False).focus().disease_ids == {"M:1"}


def test_fetch_fingerprint_covers_focus_entries_only():
    old, wide = _scope(with_core=False), _scope(with_core=True)
    assert common.fetch_fingerprint(old, {"cap": 5}) == common.fetch_fingerprint(wide, {"cap": 5})
    grown = _scope(with_core=True)
    grown.diseases[1]["focus"] = True
    assert common.fetch_fingerprint(grown, {"cap": 5}) != common.fetch_fingerprint(old, {"cap": 5})


def test_scoped_search_lists_iterate_focus_entries_only():
    from pipeline.sources import clinicaltrials, pubmed, reporter

    f = _scope(with_core=True).focus()
    assert {s.target_id for s in pubmed.build_searches(f)} == {"HGNC:1", "M:1"}
    assert {s["target_id"] for s in clinicaltrials._searches(f)} == {"HGNC:1", "M:1"}
    assert {s["target_id"] for s in reporter._searches(f)} == {"HGNC:1", "M:1"}


def test_reusable_searches_and_split(tmp_path, monkeypatch):
    monkeypatch.delenv("PIPELINE_REFRESH", raising=False)
    prev = [{"target_id": "A", "query": "q", "cap": 5, "pmids": ["1"]}]
    (tmp_path / "searches.json").write_text(json.dumps(prev))
    assert common.reusable_searches(tmp_path, "pubmed", "k") == []  # no marker: incomplete
    common.write_fingerprint(tmp_path, "fp", "k")
    assert common.reusable_searches(tmp_path, "pubmed", "k") == prev
    assert common.reusable_searches(tmp_path, "pubmed", "other settings") == []
    monkeypatch.setenv("PIPELINE_REFRESH", "pubmed")
    assert common.reusable_searches(tmp_path, "pubmed", "k") == []
    monkeypatch.delenv("PIPELINE_REFRESH")
    wanted = [
        {"target_id": "A", "query": "q", "cap": 5},
        {"target_id": "A2", "query": "q", "cap": 5},
        {"target_id": "A", "query": "q changed", "cap": 5},
    ]
    reused, todo = common.split_searches(wanted, prev, ("target_id", "query", "cap"))
    assert reused == [{"target_id": "A", "query": "q", "cap": 5, "pmids": ["1"]}]
    assert [t["target_id"] for t in todo] == ["A2", "A"]


# ---------------------------------------------------------------- candidate-only similarity


def _random_corpus(n_diseases: int = 60, seed: int = 3):
    """A random 3-level ontology and a corpus whose diseases record 3-8 leaf terms."""
    rng = random.Random(seed)
    parents = {"HP:R": []}
    mids = [f"HP:M{i}" for i in range(6)]
    leaves = [f"HP:L{i}" for i in range(40)]
    for m in mids:
        parents[m] = ["HP:R"]
    for i, leaf in enumerate(leaves):
        parents[leaf] = [mids[i % 6]] + ([mids[(i + 1) % 6]] if i % 5 == 0 else [])
    ann = {
        f"MONDO:{i}": {
            t: rng.choice([None, 0.9, 0.55, 0.17]) for t in rng.sample(leaves, rng.randint(3, 8))
        }
        for i in range(n_diseases)
    }
    return ann, hpo_sim.corpus_from(ann, parents, {t: t for t in parents})


def _reference_rows(ids, dterms, c, threshold):
    """The pre-stage-A computation: every pair scored, the dense cosine matrix as prefilter."""
    ic, anc = c.ic, c.ancestors
    w = {d: {t: (0.5 if f is None else f) for t, f in dterms[d].items()} for d in ids}
    cl = {d: closure(w[d], anc) for d in ids}
    full = {
        (i, j): phenotype_similarity(w[ids[i]], w[ids[j]], ic, anc, cl[ids[i]], cl[ids[j]])
        for i, j in combinations(range(len(ids)), 2)
    }
    cos = hpo_sim.cosine_matrix(
        ids, ids, terms=dterms, ic_fn=lambda t: ic.get(t, 0.0), ancestors_fn=anc
    )
    np.fill_diagonal(cos, -1)
    pairs = set()
    for i in range(len(ids)):
        for j in np.argsort(-cos[i], kind="stable")[: analytics.SYM_PREFILTER_K]:
            if cos[i, j] > 0:
                pairs.add((min(i, int(j)), max(i, int(j))))

    def spec(d):
        return {t for t in dterms[d] if ic.get(t, 0.0) >= SPECIFIC_IC}

    per = defaultdict(list)
    for i, j in pairs:
        if full[(i, j)] >= threshold and len(spec(ids[i]) & spec(ids[j])) >= 2:
            per[i].append((full[(i, j)], j))
            per[j].append((full[(i, j)], i))
    keep = set()
    for i, lst in per.items():
        for _s, j in sorted(lst, reverse=True)[: analytics.SYM_TOP_K]:
            keep.add((ids[min(i, j)], ids[max(i, j)]))
    return pairs, keep


def test_cosine_top_k_matches_the_dense_prefilter():
    ann, c = _random_corpus()
    ids = sorted(ann)
    ref, _ = _reference_rows(ids, ann, c, 0.45)
    for block in (7, 1024):
        got = hpo_sim.cosine_top_k(
            ids,
            ann,
            analytics.SYM_PREFILTER_K,
            ic_fn=lambda t: c.ic.get(t, 0.0),
            ancestors_fn=c.ancestors,
            block=block,
        )
        assert got == ref


def test_candidate_only_similarity_equals_the_full_computation(monkeypatch):
    ann, c = _random_corpus()
    ids = sorted(ann)
    monkeypatch.setattr(analytics, "SYM_THRESHOLD", 0.3)  # enough links on random data
    rows, _ = analytics.symptom_similarity(ids, ann, c, calibrate=False)
    _, keep = _reference_rows(ids, ann, c, 0.3)
    assert keep and {(r["source_id"], r["target_id"]) for r in rows} == keep


def test_calibration_records_how_much_the_top_k_cap_decides():
    ann, c = _random_corpus(n_diseases=150)  # more than 5,000 random pairs
    rows, cal = analytics.symptom_similarity(sorted(ann), ann, c, calibrate=True)
    for key in (
        "qualifying_pairs",
        "kept_pairs",
        "dropped_by_top_k",
        "share_decided_by_top_k",
        "diseases_at_cap",
        "cap_bite_similarity_median",
    ):
        assert key in cal
    assert cal["kept_pairs"] == len(rows)
    assert cal["dropped_by_top_k"] == cal["qualifying_pairs"] - cal["kept_pairs"]
    assert "_random_scores" not in cal
    json.dumps(cal)


def test_top_k_cap_stats_on_a_hub():
    per = {0: [(0.9 - i / 100, i + 1) for i in range(10)]}
    for i in range(1, 11):
        per[i] = [(0.9 - (i - 1) / 100, 0)]
    keep = {(0, j) for j in range(1, 9)}
    out = analytics.top_k_cap_stats(per, keep, 10, np.array([0.1, 0.5, 0.95]))
    assert out["dropped_by_top_k"] == 2 and out["share_decided_by_top_k"] == 0.2
    assert out["diseases_at_cap"] == 1
    assert out["cap_bite_similarity_median"] == pytest.approx(0.83)
    assert out["cap_bite_percentile_random"] == pytest.approx(66.67)


# ---------------------------------------------------------------- HPO term export


def test_hpo_terms_table_covers_the_phenotype_branch(monkeypatch):
    terms = pl.DataFrame(
        {
            "id": ["HP:0000001", "HP:0000118", "HP:A", "HP:B", "HP:C", "HP:0000005", "HP:OLD"],
            "label": ["All", "Phenotypic abnormality", "A", "B", "C", "Mode", "Old"],
            "definition": [None] * 7,
            "synonyms": [[], [], ["a syn", "A"], [], ["c1"], [], []],
            "parents": [
                [],
                ["HP:0000001"],
                ["HP:0000118"],
                ["HP:A"],
                ["HP:A", "HP:B"],
                ["HP:0000001"],
                [],
            ],
            "deprecated": [False, False, False, False, False, False, True],
        }
    )
    monkeypatch.setattr(bio, "hpo_terms", lambda: terms)
    ann = {"D1": {"HP:B": 1.0}, "D2": {"HP:A": None}}
    c = hpo_sim.corpus_from(ann, {r[0]: r[1] for r in terms.select("id", "parents").iter_rows()})
    t = analytics.hpo_terms_table(c)
    assert t["id"].to_list() == ["HP:0000118", "HP:A", "HP:B", "HP:C"]
    row = {r["id"]: r for r in t.iter_rows(named=True)}
    assert row["HP:A"]["synonyms"] == ["a syn"]  # the label itself is not repeated
    assert row["HP:C"]["parents"] == ["HP:A", "HP:B"]
    assert row["HP:C"]["ic"] is None  # neither it nor a descendant annotates anything
    assert row["HP:B"]["ic"] == pytest.approx(c.ic["HP:B"])
    assert row["HP:0000118"]["ic"] == 0.0
    assert t.schema["synonyms"] == pl.List(pl.String)
    # phenotype nodes outside HP:0000118 are added with their ancestors, never the HPO root
    t = analytics.hpo_terms_table(c, ["HP:0000005"])
    assert "HP:0000005" in t["id"].to_list() and "HP:0000001" not in t["id"].to_list()


# ---------------------------------------------------------------- cluster labels


def test_template_cluster_label_uses_distinctive_symptom_and_top_gene():
    labels = {
        "HP:0011987": "Ectopic ossification in muscle tissue",
        "HP:SEIZ": "Seizure",
        "HGNC:171": "ACVR1",
        "M:1": "fibrodysplasia ossificans progressiva",
    }
    members = {1: ["M:1", "M:2", "M:3"], 2: ["M:4", "M:5"], 3: ["M:6", "M:7"]}
    dis_ph = {
        "M:1": {"HP:0011987", "HP:SEIZ"},
        "M:2": {"HP:0011987", "HP:SEIZ"},
        "M:3": {"HP:SEIZ", "HP:RARE"},
        "M:4": {"HP:SEIZ"},
        "M:5": {"HP:SEIZ"},
        "M:6": {"HP:SEIZ"},
        "M:7": {"HP:SEIZ"},
    }
    ranked = analytics.distinctive_phenotypes(members, dis_ph, labels)
    assert ranked[1][0] == "HP:0011987"  # rarer across clusters beats the ubiquitous seizure
    assert ranked[1][-1] == "HP:RARE"  # recorded by one member only: ranked last
    label = analytics.template_cluster_label(members[1], ranked[1][0], "HGNC:171", labels)
    assert label == "Ectopic ossification in muscle tissue · ACVR1"
    assert analytics.template_cluster_label(["M:1"], "HP:SEIZ", "HGNC:171", labels) == (
        "fibrodysplasia ossificans progressiva"
    )
    assert analytics.template_cluster_label(["M:4", "M:5"], None, "HGNC:171", labels) == (
        "ACVR1 disorders"
    )


def test_wide_graphs_cluster_at_the_finer_resolution(monkeypatch):
    seen = []
    real = analytics.leidenalg.RBConfigurationVertexPartition

    def spy(*a, **kw):
        seen.append(kw["resolution_parameter"])
        return real(*a, **kw)

    monkeypatch.setattr(analytics.leidenalg, "RBConfigurationVertexPartition", spy)
    analytics.cluster_diseases(["M:1", "M:2"], [], [])
    monkeypatch.setattr(analytics, "WIDE_MIN_DISEASES", 2)
    analytics.cluster_diseases(["M:1", "M:2"], [], [])
    assert seen == [1.0, 1.0, analytics.LEIDEN_RESOLUTION_WIDE, analytics.LEIDEN_RESOLUTION_WIDE]


# ---------------------------------------------------------------- pathways and ClinVar


def test_core_genes_keep_small_shared_pathways_only():
    rows = []
    for g in ("HGNC:F", "HGNC:C1", "HGNC:C2"):
        rows.append({"hgnc_id": g, "pathway_id": "SMALL"})  # 3 genes, all in scope
    rows.append({"hgnc_id": "HGNC:C1", "pathway_id": "LONELY"})  # one scope gene
    rows.append({"hgnc_id": "HGNC:other", "pathway_id": "LONELY"})
    for i in range(100):
        rows.append({"hgnc_id": f"HGNC:x{i}", "pathway_id": "BIG"})
    rows += [
        {"hgnc_id": "HGNC:F", "pathway_id": "BIG"},
        {"hgnc_id": "HGNC:C1", "pathway_id": "BIG"},
    ]
    s = Scope(
        "v",
        genes=[
            {"hgnc_id": "HGNC:F", "symbol": "F", "focus": True},
            {"hgnc_id": "HGNC:C1", "symbol": "C1", "focus": False},
            {"hgnc_id": "HGNC:C2", "symbol": "C2", "focus": False},
        ],
    )
    out = bio._pathway_rows(pl.DataFrame(rows), "pathway_id", s)
    got = set(out.select("hgnc_id", "pathway_id").iter_rows())
    assert got == {
        ("HGNC:F", "SMALL"),
        ("HGNC:C1", "SMALL"),
        ("HGNC:C2", "SMALL"),
        ("HGNC:F", "BIG"),  # focus genes keep pathways up to 300 genes
    }


HEADER = (
    "#AlleleID\tType\tName\tGeneID\tGeneSymbol\tHGNC_ID\tClinicalSignificance\tVariationID"
    "\tAssembly"
)


def _line(vid, sym, hgnc, sig, assembly="GRCh38"):
    return f"1\tsingle nucleotide variant\tx\t1\t{sym}\t{hgnc}\t{sig}\t{vid}\t{assembly}".encode()


def test_clinvar_splitter_routes_focus_rows_plp_rows_and_counts(monkeypatch):
    monkeypatch.setattr(bio, "gene_lookup", lambda: {"OTHER": "HGNC:2"})
    focus, plp = io.BytesIO(), io.BytesIO()
    sp = clinvar.Splitter(focus, plp, {"HGNC:1"}, {"FOC"})
    for line in [
        HEADER.encode(),
        _line(1, "FOC", "HGNC:1", "Pathogenic"),
        _line(1, "FOC", "HGNC:1", "Pathogenic"),  # duplicate VariationID counted once
        _line(2, "FOC", "HGNC:1", "Uncertain significance"),
        _line(3, "OTHER", "-", "Likely pathogenic"),  # gene from the symbol
        _line(4, "OTHER", "HGNC:2", "Benign"),
        _line(5, "FOC", "HGNC:1", "Pathogenic", assembly="GRCh37"),
    ]:
        sp.handle(line)
    assert focus.getvalue().count(b"\n") == 1 + 3  # header + GRCh38 focus rows
    assert plp.getvalue().count(b"\n") == 1 + 3  # header + P/LP rows of any gene
    assert sp.counts["HGNC:1"] == {"plp": 1, "vus": 1}
    assert sp.counts["HGNC:2"] == {"plp": 1, "vus": 0}


def test_clinvar_gene_counts_attrs(tmp_path, monkeypatch):
    monkeypatch.setattr(bio, "RAW", tmp_path)
    (tmp_path / "clinvar").mkdir()
    (tmp_path / "clinvar" / bio.CLINVAR_COUNTS_FILE).write_text("hgnc_id\tplp\tvus\nHGNC:1\t3\t7\n")
    plp = pl.DataFrame(
        {
            "variation_id": ["1", "2", "3", "4"],
            "hgnc_id": ["HGNC:1", "HGNC:1", "HGNC:1", "HGNC:9"],
            "symbol": ["A", "A", "A", "Z"],
            "consequence": ["nonsense", "missense", "copy_number", "missense"],
        }
    )
    monkeypatch.setattr(bio, "clinvar_plp_variants", lambda: plp)
    s = Scope(
        "v",
        genes=[{"hgnc_id": "HGNC:1", "symbol": "A"}, {"hgnc_id": "HGNC:5", "symbol": "E"}],
    )
    out = bio.clinvar_gene_counts(s)
    assert out["HGNC:1"] == {
        "clinvar_plp": 3,
        "clinvar_vus": 7,
        "clinvar_truncating_share": 0.5,  # copy-number changes left out of the share
    }
    assert out["HGNC:5"] == {"clinvar_plp": 0, "clinvar_vus": 0, "clinvar_truncating_share": None}


def test_plp_parser_keeps_lean_columns(tmp_path, monkeypatch):
    monkeypatch.setattr(bio, "RAW", tmp_path)
    (tmp_path / "clinvar").mkdir()
    cols = [
        "AlleleID", "Type", "Name", "GeneSymbol", "HGNC_ID", "ClinicalSignificance",
        "PhenotypeIDS", "Chromosome", "Start", "Stop", "Assembly", "Cytogenetic",
        "PositionVCF", "ReferenceAlleleVCF", "AlternateAlleleVCF", "VariationID",
    ]  # fmt: skip
    rows = [
        ["1", "single nucleotide variant", "NM_1(ACVR1):c.617G>A (p.Arg206His)", "ACVR1",
         "HGNC:171", "Pathogenic", "MONDO:MONDO:0007606,OMIM:135100", "2", "100", "100",
         "GRCh38", "2q24.1", "100", "G", "A", "13525"],
        ["2", "single nucleotide variant", "x", "ACVR1", "HGNC:171", "Pathogenic", "na", "2",
         "100", "100", "GRCh38", "2q24.1", "100", "G", "A", "13525"],
    ]  # fmt: skip
    with gzip.open(tmp_path / "clinvar" / bio.CLINVAR_PLP_FILE, "wt") as f:
        f.write("#" + "\t".join(cols) + "\n")
        for r in rows:
            f.write("\t".join(r) + "\n")
    df = bio.parse_clinvar_plp(tmp_path / "clinvar" / bio.CLINVAR_PLP_FILE)
    assert df.height == 1  # one row per VariationID
    r = df.row(0, named=True)
    assert r["hgnc_id"] == "HGNC:171" and r["consequence"] == "missense"
    assert r["phenotype_ids"] == ["MONDO:MONDO:0007606", "OMIM:135100"]
    assert (r["chromosome"], r["start"], r["assembly"]) == ("2", 100, "GRCh38")


# ---------------------------------------------------------------- validation


def _graph(tier_missing: bool = False):
    attrs = lambda tier: json.dumps({} if tier is None else {"tier": tier})  # noqa: E731
    nodes = pl.DataFrame(
        {
            "id": ["M:1", "M:2", "HGNC:1", "HP:1"],
            "type": ["disease", "disease", "gene", "phenotype"],
            "attrs": [attrs("focus"), attrs("core"), attrs(None if tier_missing else "core"),
                      attrs("core")],
        }
    )  # fmt: skip
    edges = pl.DataFrame(
        {
            "source_id": ["M:1", "M:1", "M:2"],
            "target_id": ["HGNC:1", "HP:1", "HP:1"],
            "relation": ["caused_by_variant_in", "has_phenotype", "has_phenotype"],
        }
    )
    return {"nodes": nodes, "edges": edges, "hpo_terms": pl.DataFrame({"id": ["HP:1"]})}


def test_check_core_counts_tiers_and_hpo_terms():
    res = {r["check"]: r for r in validate.check_core(_graph(), 1)}
    assert all(r["ok"] for r in res.values())
    assert res["at least 1 diseases with a gene and a recorded symptom"]["detail"]["n"] == 1
    res = {r["check"]: r for r in validate.check_core(_graph(), 2)}
    assert not res["at least 2 diseases with a gene and a recorded symptom"]["ok"]
    res = validate.check_core(_graph(tier_missing=True), None)
    assert [r["ok"] for r in res] == [False, True]
    g = _graph()
    g["hpo_terms"] = pl.DataFrame({"id": ["HP:9"]})
    assert not validate.check_core(g, None)[-1]["ok"]
