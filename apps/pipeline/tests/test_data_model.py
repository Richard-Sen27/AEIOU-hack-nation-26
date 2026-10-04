"""Stage 1 data model: positions, standard ids, symptom frequencies and the HPO lineage."""

import io
import json

import polars as pl
import pytest

from pipeline import bio, build, taxonomy, validate
from pipeline.contracts import ASSERTION_SCHEMA, NODE_SCHEMA, SYNONYM_SCHEMA, Scope, assertion


def _capture(monkeypatch) -> dict:
    """Replace bio.write_tables; returns the dict the tables land in."""
    out: dict = {}

    def write(source, nodes=(), synonyms=(), assertions=()):
        out[source] = {"nodes": list(nodes), "synonyms": list(synonyms), "rows": list(assertions)}

    monkeypatch.setattr(bio, "write_tables", write)
    return out


# ---------------------------------------------------------------- ClinVar positions


def test_clinvar_position_parses_grch38_columns():
    snv = {
        "Assembly": "GRCh38",
        "Chromosome": "2",
        "Start": "166037930",
        "Stop": "166037930",
        "Cytogenetic": "2q24.3",
        "PositionVCF": "166037930",
        "ReferenceAlleleVCF": "C",
        "AlternateAlleleVCF": "T",
    }
    assert bio.clinvar_position(snv) == {
        "chromosome": "2",
        "start": 166037930,
        "stop": 166037930,
        "cytoband": "2q24.3",
        "assembly": "GRCh38",
        "position_vcf": 166037930,
        "ref": "C",
        "alt": "T",
    }
    cnv = {**snv, "Start": "166044436", "Stop": "166079787", "PositionVCF": "-1"}
    cnv |= {"ReferenceAlleleVCF": "na", "AlternateAlleleVCF": "na"}
    pos = bio.clinvar_position(cnv)
    assert (pos["start"], pos["stop"], pos["position_vcf"], pos["ref"], pos["alt"]) == (
        166044436,
        166079787,
        None,
        None,
        None,
    )
    long_indel = {**snv, "ReferenceAlleleVCF": "A" * (bio.ALLELE_MAX_LEN + 1)}
    assert bio.clinvar_position(long_indel)["ref"] is None
    unplaced = bio.clinvar_position({**snv, "Chromosome": "na", "Start": "-1", "Stop": "-1"})
    assert unplaced["chromosome"] is None and unplaced["start"] is None
    assert unplaced["assembly"] is None


def test_vcv_accession():
    assert bio.vcv("15087") == "VCV000015087"


GENES = {
    "HGNC:1": {"chromosome": "2", "start": 1000, "end": 5000, "strand": "+"},
    "HGNC:2": {"chromosome": "2", "start": 8000, "end": 9000, "strand": "-"},
    "HGNC:3": {"chromosome": "X", "start": 1000, "end": 9000, "strand": "+"},
}


def test_spanned_genes_only_for_large_copy_number_events():
    cnv = {"type": "copy number loss", "chromosome": "2", "start": 4000, "stop": 8500}
    cnv["assembly"] = "GRCh38"
    assert bio.spanned_genes(cnv, GENES) == [("HGNC:1", 1001), ("HGNC:2", 501)]
    small = {**cnv, "type": "Deletion", "stop": 4100}
    assert bio.spanned_genes(small, GENES) == []
    snv = {**cnv, "type": "single nucleotide variant"}
    assert bio.spanned_genes(snv, GENES) == []
    assert bio.spanned_genes({**cnv, "assembly": "GRCh37"}, GENES) == []


def _variant(vid, hgnc, symbol, vtype, start, stop, cls="pathogenic"):
    return {
        "variation_id": vid,
        "hgnc_id": hgnc,
        "symbol": symbol,
        "name": f"NC_000002.12:g.{start}_{stop}del",
        "type": vtype,
        "classification": cls,
        "review_status": "criteria provided, single submitter",
        "stars": 1,
        "consequence": "copy_number",
        "phenotype_ids": [],
        "phenotypes": [],
        "origin": "germline",
        "last_evaluated": "-",
        "rs": "-1",
        "submitters": 1,
        "chromosome": "2",
        "start": start,
        "stop": stop,
        "cytoband": "2q24.3",
        "assembly": "GRCh38",
        "position_vcf": None,
        "ref": None,
        "alt": None,
    }


def test_normalize_clinvar_positions_and_multi_gene_variant_of(monkeypatch):
    rows = [
        _variant("60251", "HGNC:1", "GENEA", "copy number loss", 4000, 8500),
        _variant("70000", "HGNC:2", "GENEB", "single nucleotide variant", 8100, 8100),
    ]
    monkeypatch.setattr(bio, "clinvar_variants", lambda: pl.DataFrame(rows))
    monkeypatch.setattr(bio, "clinvar_plp_or_focus", lambda: pl.DataFrame(rows))
    monkeypatch.setattr(bio, "gene_coordinates", lambda: GENES)
    monkeypatch.setattr(bio, "_retrieved", lambda *_: "2026-10-04T00:00:00+00:00")
    monkeypatch.setattr(bio, "xref_to_mondo", lambda: {})
    out = _capture(monkeypatch)
    scope = Scope(
        data_version="t",
        genes=[
            {"hgnc_id": "HGNC:1", "symbol": "GENEA", "seed": True},
            {"hgnc_id": "HGNC:2", "symbol": "GENEB", "seed": True},
        ],
    )
    bio.normalize_clinvar(scope)
    nodes = {n["id"]: n for n in out["clinvar"]["nodes"]}
    attrs = nodes["CLINVAR:60251"]["attrs"]
    assert attrs["vcv"] == "VCV000060251"
    assert (attrs["chromosome"], attrs["start"], attrs["stop"]) == ("2", 4000, 8500)
    assert attrs["cytoband"] == "2q24.3" and attrs["assembly"] == "GRCh38"
    links = sorted(
        (r["source_id"], r["target_id"], (r["features"] or {}).get("basis"))
        for r in out["clinvar"]["rows"]
        if r["relation"] == "variant_of"
    )
    assert links == [
        ("CLINVAR:60251", "HGNC:1", None),
        ("CLINVAR:60251", "HGNC:2", "coordinate_overlap"),
        ("CLINVAR:70000", "HGNC:2", None),
    ]


# ---------------------------------------------------------------- MANE gene coordinates

MANE_LINES = [
    "#NCBI_GeneID\tEnsembl_Gene\tHGNC_ID\tsymbol\tname\tRefSeq_nuc\tRefSeq_prot\tEnsembl_nuc\t"
    "Ensembl_prot\tMANE_status\tGRCh38_chr\tchr_start\tchr_end\tchr_strand\n",
    "GeneID:6812\tE\tHGNC:11444\tSTXBP1\tx\tNM\tNP\tENST\tENSP\tMANE Select\tNC_000009.12\t"
    "127612277\t127692699\t+\n",
    "GeneID:6812\tE\tHGNC:11444\tSTXBP1\tx\tNM\tNP\tENST\tENSP\tMANE Plus Clinical\t"
    "NC_000009.12\t1\t999999999\t+\n",
    "GeneID:1\tE\tHGNC:11411\tCDKL5\tx\tNM\tNP\tENST\tENSP\tMANE Select\tNC_000023.11\t"
    "18425583\t18653629\t+\n",
]


def test_refseq_chromosome():
    assert bio.refseq_chromosome("NC_000019.10") == "19"
    assert bio.refseq_chromosome("NC_000023.11") == "X"
    assert bio.refseq_chromosome("NC_000024.10") == "Y"
    assert bio.refseq_chromosome("NC_012920.1") == "MT"
    assert bio.refseq_chromosome("NT_187361.1") is None


def test_parse_mane_keeps_select_transcripts():
    df = bio.parse_mane(MANE_LINES)
    got = {r["hgnc_id"]: r for r in df.iter_rows(named=True)}
    assert got["HGNC:11444"] == {
        "hgnc_id": "HGNC:11444",
        "chromosome": "9",
        "start": 127612277,
        "end": 127692699,
        "strand": "+",
    }
    assert got["HGNC:11411"]["chromosome"] == "X"


def test_normalize_hgnc_joins_coordinates_and_reports_missing(monkeypatch, caplog):
    genes = pl.DataFrame(
        [
            {
                "hgnc_id": hid,
                "symbol": sym,
                "name": sym,
                "locus_group": "protein-coding gene",
                "location": loc,
                "aliases": [],
                "alias_names": [],
                "prev_symbols": [],
                "entrez_id": None,
                "ensembl_id": None,
                "uniprot_ids": [],
                "omim_ids": [],
            }
            for hid, sym, loc in [
                ("HGNC:11444", "STXBP1", "9q34.11"),
                ("HGNC:7489", "MT-TL2", "mitochondria"),
            ]
        ]
    )
    monkeypatch.setattr(bio, "hgnc", lambda: genes)
    monkeypatch.setattr(bio, "clingen_dosage", lambda: pl.DataFrame({"symbol": []}))
    coords = {r["hgnc_id"]: r for r in bio.parse_mane(MANE_LINES).iter_rows(named=True)}
    monkeypatch.setattr(bio, "gene_coordinates", lambda: coords)
    monkeypatch.setattr(bio, "clinvar_gene_counts", lambda scope: {})
    out = _capture(monkeypatch)
    scope = Scope(data_version="t", genes=[{"hgnc_id": "HGNC:11444"}, {"hgnc_id": "HGNC:7489"}])
    with caplog.at_level("WARNING"):
        bio.normalize_hgnc(scope)
    attrs = {n["id"]: n["attrs"] for n in out["hgnc"]["nodes"]}
    stx = attrs["HGNC:11444"]
    assert (stx["chromosome"], stx["cytoband"], stx["start"], stx["end"], stx["strand"]) == (
        "9",
        "9q34.11",
        127612277,
        127692699,
        "+",
    )
    assert stx["assembly"] == "GRCh38"
    mt = attrs["HGNC:7489"]
    assert mt["chromosome"] == "MT" and mt["start"] is None and mt["assembly"] is None
    assert "MT-TL2" in caplog.text


# ---------------------------------------------------------------- disease ids (MONDO + product1)

PRODUCT1 = b"""<?xml version="1.0" encoding="UTF-8"?>
<JDBOR><DisorderList count="2">
  <Disorder id="1"><OrphaCode>33069</OrphaCode><Name lang="en">Dravet syndrome</Name>
    <DisorderType id="21394"><Name lang="en">Disease</Name></DisorderType>
    <ExternalReferenceList count="4">
      <ExternalReference id="a"><Source>MONDO</Source><Reference>0000002</Reference>
        <DisorderMappingRelation id="1"><Name lang="en">E (Exact mapping: the two concepts are
        equivalent)</Name></DisorderMappingRelation>
        <DisorderMappingValidationStatus id="2"><Name lang="en">Validated</Name>
        </DisorderMappingValidationStatus></ExternalReference>
      <ExternalReference id="b"><Source>OMIM</Source><Reference>607208</Reference>
        <DisorderMappingRelation id="1"><Name lang="en">E (Exact mapping: the two concepts are
        equivalent)</Name></DisorderMappingRelation>
        <DisorderMappingValidationStatus id="2"><Name lang="en">Validated</Name>
        </DisorderMappingValidationStatus></ExternalReference>
      <ExternalReference id="c"><Source>OMIM</Source><Reference>100000</Reference>
        <DisorderMappingRelation id="3"><Name lang="en">NTBT (ORPHAcode is narrower than the
        targeted code used to represent it)</Name></DisorderMappingRelation>
        <DisorderMappingValidationStatus id="2"><Name lang="en">Validated</Name>
        </DisorderMappingValidationStatus></ExternalReference>
      <ExternalReference id="d"><Source>OMIM</Source><Reference>200000</Reference>
        <DisorderMappingRelation id="1"><Name lang="en">E (Exact mapping: the two concepts are
        equivalent)</Name></DisorderMappingRelation>
        <DisorderMappingValidationStatus id="4"><Name lang="en">Not yet validated</Name>
        </DisorderMappingValidationStatus></ExternalReference>
    </ExternalReferenceList></Disorder>
  <Disorder id="2"><OrphaCode>999</OrphaCode><Name lang="en">Other</Name>
    <ExternalReferenceList count="1">
      <ExternalReference id="e"><Source>MONDO</Source><Reference>0000001</Reference>
        <DisorderMappingRelation id="1"><Name lang="en">E (Exact mapping: the two concepts are
        equivalent)</Name></DisorderMappingRelation>
        <DisorderMappingValidationStatus id="2"><Name lang="en">Validated</Name>
        </DisorderMappingValidationStatus></ExternalReference>
    </ExternalReferenceList></Disorder>
</DisorderList></JDBOR>"""


def test_parse_product1_keeps_validated_exact_mappings_only():
    df = bio.parse_orphanet_nomenclature(io.BytesIO(PRODUCT1))
    rows = {r["orpha"]: r for r in df.iter_rows(named=True)}
    assert rows["ORPHA:33069"]["mondo_ids"] == ["MONDO:0000002"]
    assert rows["ORPHA:33069"]["omim_ids"] == ["OMIM:607208"]
    assert rows["ORPHA:33069"]["disorder_type"] == "Disease"
    assert rows["ORPHA:999"]["omim_ids"] == []


def test_disease_xref_ids_adds_product1_ids_without_stealing():
    nomenclature = bio.parse_orphanet_nomenclature(io.BytesIO(PRODUCT1))
    exact = {
        "MONDO:0000001": ["OMIM:111111", "ORPHA:999"],
        "MONDO:0000002": ["MEDGEN:C1"],
        "MONDO:0000003": ["OMIM:607208"],  # MONDO owns this OMIM id for another disease
    }
    ids = bio.disease_xref_ids(exact, nomenclature)
    assert ids["MONDO:0000001"] == {
        "orpha_ids": ["ORPHA:999"],
        "omim_ids": ["OMIM:111111"],
        "orphanet_added": [],
    }
    # ORPHA:33069 maps exactly to MONDO:0000002 in product1; its OMIM id belongs elsewhere.
    assert ids["MONDO:0000002"] == {
        "orpha_ids": ["ORPHA:33069"],
        "omim_ids": [],
        "orphanet_added": ["ORPHA:33069"],
    }


def test_normalize_mondo_adds_id_attrs_and_synonyms(monkeypatch):
    terms = pl.DataFrame(
        [
            {
                "id": "MONDO:0000002",
                "label": "Dravet syndrome",
                "definition": None,
                "exact_synonyms": [],
                "other_synonyms": [],
                "exact_matches": ["OMIM:607208"],
                "xrefs": [],
                "parents": [],
                "deprecated": False,
                "rare": True,
            }
        ]
    )
    monkeypatch.setattr(bio, "mondo_terms", lambda: terms)
    monkeypatch.setattr(
        bio,
        "orphanet_nomenclature",
        lambda: bio.parse_orphanet_nomenclature(io.BytesIO(PRODUCT1)),
    )
    monkeypatch.setattr(
        bio,
        "gene_disease",
        lambda: pl.DataFrame(
            schema={"source": pl.String, "mondo_id": pl.String, "hgnc_id": pl.String}
        ),
    )
    monkeypatch.setattr(bio, "_retrieved", lambda *_: None)
    out = _capture(monkeypatch)
    bio.normalize_mondo(Scope(data_version="t", diseases=[{"mondo_id": "MONDO:0000002"}]))
    attrs = out["mondo"]["nodes"][0]["attrs"]
    assert attrs["orpha_ids"] == ["ORPHA:33069"]
    assert attrs["omim_ids"] == ["OMIM:607208"]
    syns = {(s["synonym"], s["source"]) for s in out["mondo"]["synonyms"]}
    assert ("ORPHA:33069", "orphanet") in syns
    assert ("OMIM:607208", "mondo") in syns


# ---------------------------------------------------------------- symptom frequencies


def test_phenotype_features_leave_out_unknowns():
    r = {"frequency": 0.9, "frequency_label": "Very frequent", "onset": None, "onset_id": None}
    assert bio.phenotype_features(r, "hpo") == {
        "frequency": 0.9,
        "frequency_label": "Very frequent",
        "frequency_by_source": {"hpo": 0.9},
    }
    assert bio.phenotype_features({"frequency": None, "frequency_label": None}, "hpo") is None


def test_phenotype_rows_keep_highest_frequency_and_onset(monkeypatch):
    dp = pl.DataFrame(
        [
            ("MONDO:1", "HP:1", 0.2, "1/5", None, None, "OMIM:1", "hpo"),
            ("MONDO:1", "HP:1", 0.5, "1/2", "HP:0003593", "Infantile onset", "OMIM:1", "hpo"),
            ("MONDO:1", "HP:1", 0.9, "Very frequent (99-80%)", None, None, "ORPHA:1", "orphanet"),
            ("MONDO:1", "HP:2", None, None, None, None, "OMIM:1", "hpo"),
        ],
        schema=[
            "mondo_id",
            "hpo_id",
            "frequency",
            "frequency_label",
            "onset_id",
            "onset",
            "ref",
            "source",
        ],
        orient="row",
    )
    monkeypatch.setattr(bio, "disease_phenotypes", lambda: dp)
    scope = Scope(
        data_version="t",
        diseases=[{"mondo_id": "MONDO:1"}],
        phenotypes=[{"hpo_id": "HP:1"}, {"hpo_id": "HP:2"}],
    )
    rows = bio.phenotype_rows(scope, "hpo").to_dicts()
    assert rows[0] == {
        "mondo_id": "MONDO:1",
        "hpo_id": "HP:1",
        "ref": "OMIM:1",
        "frequency": 0.5,
        "frequency_label": "1/2",
        "onset_id": "HP:0003593",
        "onset": "Infantile onset",
    }
    assert rows[1]["frequency"] is None and rows[1]["onset"] is None


def test_merge_keeps_frequency_by_source_and_label_of_the_maximum():
    nodes = pl.DataFrame(
        [
            {"id": i, "type": t, "label": i, "description": None, "url": None, "attrs": "{}"}
            for i, t in (("MONDO:1", "disease"), ("HP:1", "phenotype"))
        ],
        schema=NODE_SCHEMA,
    )
    hpo = {"frequency": 0.17, "frequency_label": "Occasional", "frequency_by_source": {"hpo": 0.17}}
    orpha = {
        "frequency": 0.55,
        "frequency_label": "Frequent (79-30%)",
        "frequency_by_source": {"orphanet": 0.55},
    }
    rows = [
        assertion(
            "MONDO:1",
            "HP:1",
            "has_phenotype",
            tier="curated_db",
            source_type=s,
            source_ref=r,
            features=f,
        )
        for s, r, f in (
            ("hpo", "OMIM:1", hpo),
            ("hpo", "ORPHA:1", {**hpo, "frequency_by_source": {"hpo": 0.1}}),
            ("orphanet", "ORPHA:1", orpha),
        )
    ]
    df = pl.DataFrame(
        [
            {c: (json.dumps(r[c]) if isinstance(r[c], dict) else r[c]) for c in ASSERTION_SCHEMA}
            for r in rows
        ],
        schema=ASSERTION_SCHEMA,
    )
    t = build.merge(nodes, pl.DataFrame(schema=SYNONYM_SCHEMA), df)
    f = json.loads(t["edges"]["features"][0])
    assert f == {
        "frequency": 0.55,
        "frequency_label": "Frequent (79-30%)",
        "frequency_by_source": {"hpo": 0.17, "orphanet": 0.55},
    }


# ---------------------------------------------------------------- excluded terms


def test_excluded_annotations_are_flagged_and_kept_on_the_disease(monkeypatch):
    hpoa = pl.DataFrame(
        [
            ("OMIM:1", False, "HP:1", "HP:0040281", 0.9, None),
            ("OMIM:1", True, "HP:2", "", None, None),  # NOT qualifier
            ("OMIM:1", False, "HP:3", "HP:0040285", 0.0, None),  # frequency "Excluded (0%)"
        ],
        schema=["disease_id", "negated", "hpo_id", "frequency_raw", "frequency", "onset"],
        orient="row",
    )
    orpha = pl.DataFrame(
        [("ORPHA:1", "HP:2", "Excluded (0%)"), ("ORPHA:1", "HP:1", "Frequent (79-30%)")],
        schema=["orpha", "hpo_id", "frequency_raw"],
        orient="row",
    )
    monkeypatch.setattr(bio, "hpoa", lambda: hpoa)
    monkeypatch.setattr(bio, "orphanet_phenotypes", lambda: orpha)
    monkeypatch.setattr(bio, "xref_to_mondo", lambda: {"OMIM:1": "MONDO:1", "ORPHA:1": "MONDO:1"})
    monkeypatch.setattr(bio, "hpo_label", lambda h: {"HP:0040281": "Very frequent"}.get(h, h))
    ann = bio._phenotype_annotations.__wrapped__()
    kept = ann.filter(~pl.col("excluded"))
    assert sorted(kept.select("hpo_id", "source").rows()) == [("HP:1", "hpo"), ("HP:1", "orphanet")]
    assert kept.filter(pl.col("source") == "hpo")["frequency_label"].to_list() == ["Very frequent"]
    excluded = ann.filter(pl.col("excluded")).select("mondo_id", "hpo_id", "ref", "source")
    monkeypatch.setattr(bio, "disease_excluded_phenotypes", lambda: excluded)
    nodes = bio.excluded_phenotype_nodes(
        Scope(data_version="t", diseases=[{"mondo_id": "MONDO:1"}])
    )
    assert nodes == [
        {
            "id": "MONDO:1",
            "type": "disease",
            "attrs": {
                "excluded_phenotypes": [
                    {
                        "id": "HP:2",
                        "label": "HP:2",
                        "sources": ["hpo", "orphanet"],
                        "refs": ["OMIM:1", "ORPHA:1"],
                    },
                    {"id": "HP:3", "label": "HP:3", "sources": ["hpo"], "refs": ["OMIM:1"]},
                ]
            },
        }
    ]


# ---------------------------------------------------------------- HPO lineage

#            HP:0000001 (All)
#            /            \
#   HP:0000118 (PA)     HP:0000005 (inheritance)
#      /        \               \
#   HP:A (sys)  HP:B (sys)     HP:INH
#    /    \      /
#  HP:A1  HP:A2 /
#     \    |   /
#      HP:X (is_a A1, A2 and B)     HP:Y (is_a A2)
PARENTS = {
    "HP:0000001": [],
    "HP:0000118": ["HP:0000001"],
    "HP:0000005": ["HP:0000001"],
    "HP:INH": ["HP:0000005"],
    "HP:A": ["HP:0000118"],
    "HP:B": ["HP:0000118"],
    "HP:A1": ["HP:A"],
    "HP:A2": ["HP:A"],
    "HP:X": ["HP:A1", "HP:A2", "HP:B"],
    "HP:Y": ["HP:A2"],
}
LABELS = {k: f"label {k}" for k in PARENTS}


def test_lineage_follows_primary_parents_on_a_tiny_ontology():
    lin = taxonomy.hpo_lineages(
        ["HP:X", "HP:Y", "HP:A", "HP:INH", "HP:MISSING", "HP:X"], PARENTS, LABELS
    )
    # HP:A2 has two in-graph descendants (X, Y), HP:A1 and HP:B one each: A2 wins for X.
    assert lin["HP:X"] == [
        {"id": "HP:A", "label": "label HP:A"},
        {"id": "HP:A2", "label": "label HP:A2"},
    ]
    assert [x["id"] for x in lin["HP:Y"]] == ["HP:A", "HP:A2"]
    assert lin["HP:A"] == []  # an organ system itself
    assert lin["HP:INH"] == []  # outside Phenotypic abnormality
    assert lin["HP:MISSING"] == []
    assert set(lin) == {"HP:X", "HP:Y", "HP:A", "HP:INH", "HP:MISSING"}


def test_lineage_ties_go_to_the_smallest_id():
    lin = taxonomy.hpo_lineages(["HP:X"], PARENTS, LABELS)
    # Alone in the graph, A1, A2 and B each have one descendant: HP:A1 < HP:A2 < HP:B.
    assert [x["id"] for x in lin["HP:X"]] == ["HP:A", "HP:A1"]


def test_lineage_problems_flags_bad_roots_and_broken_paths():
    good = taxonomy.hpo_lineages(["HP:X"], PARENTS, LABELS)["HP:X"]
    problems = taxonomy.lineage_problems(
        {
            "HP:X": good,
            "HP:Y": [{"id": "HP:A2"}],  # does not start at an organ system
            "HP:A1": [{"id": "HP:B"}],  # HP:B is not a parent of HP:A1
            "HP:A": [],
            "HP:Z": None,
        },
        PARENTS,
    )
    assert problems == {
        "missing": ["HP:Z"],
        "bad_root": ["HP:Y"],
        "broken_path": ["HP:A1"],
        "empty": ["HP:A"],
    }


# ---------------------------------------------------------------- validation


def _node(nid, ntype, attrs):
    return {"id": nid, "type": ntype, "attrs": json.dumps(attrs)}


def test_position_checks_list_missing_and_fail_malformed():
    span = {"chromosome": "9", "start": 10, "end": 20, "assembly": "GRCh38"}
    nodes = pl.DataFrame(
        [
            _node("HGNC:1", "gene", {"symbol": "A", **span}),
            _node("HGNC:2", "gene", {"symbol": "MT-TL2", "chromosome": "MT", "start": None}),
            _node(
                "CLINVAR:1",
                "variant",
                {"chromosome": "9", "start": 5, "stop": 5, "assembly": "GRCh38"},
            ),
            _node(
                "CLINVAR:2",
                "variant",
                {"chromosome": "9", "start": 9, "stop": 3, "assembly": "GRCh38"},
            ),
        ]
    )
    res = {r["check"]: r for r in validate.check_positions(nodes)}
    genes = res["every gene has coordinates or is listed as missing"]
    assert genes["ok"] and genes["detail"]["missing"] == ["MT-TL2"]
    assert genes["detail"]["with_position"] == 1
    variants = res["every variant has a position or is listed as missing"]
    assert not variants["ok"] and variants["detail"]["malformed"] == ["CLINVAR:2"]


def test_lineage_checks(monkeypatch):
    monkeypatch.setattr(taxonomy, "hpo", lambda: (PARENTS, LABELS))
    good = taxonomy.hpo_lineages(["HP:X"], PARENTS, LABELS)["HP:X"]
    nodes = pl.DataFrame([_node("HP:X", "phenotype", {"hpo_lineage": good})])
    assert all(r["ok"] for r in validate.check_lineage(nodes))
    nodes = pl.DataFrame(
        [_node("HP:X", "phenotype", {"hpo_lineage": good}), _node("HP:Y", "phenotype", {})]
    )
    res = {r["check"]: r["ok"] for r in validate.check_lineage(nodes)}
    assert res["every phenotype has an hpo_lineage"] is False


@pytest.mark.parametrize(
    ("location", "expected"),
    [("9q34.11", "9"), ("Xp22.13", "X"), ("mitochondria", "MT"), ("", None), ("unplaced", None)],
)
def test_cytoband_chromosome(location, expected):
    assert bio.cytoband_chromosome(location) == expected
