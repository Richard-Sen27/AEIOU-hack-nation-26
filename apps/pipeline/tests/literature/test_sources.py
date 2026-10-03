"""Parsing and normalization of recorded real API responses (fixtures/)."""

import json
import shutil

import polars as pl
import yaml

from pipeline.contracts import ASSERTION_SCHEMA, NODE_SCHEMA, SYNONYM_SCHEMA
from pipeline.sources import clinicaltrials, patient_orgs, pubmed, reporter

from .conftest import FIXTURES


def _tables(root, source):
    out = {}
    for name, schema in (
        ("nodes", NODE_SCHEMA),
        ("synonyms", SYNONYM_SCHEMA),
        ("assertions", ASSERTION_SCHEMA),
    ):
        df = pl.read_parquet(root / source / f"{name}.parquet")
        assert list(df.columns) == list(schema), name
        out[name] = df
    for col in out["nodes"]["attrs"].drop_nulls():
        json.loads(col)
    return out


def _no_contacts(tables):
    for df in tables.values():
        for col in df.columns:
            if df[col].dtype == pl.String:
                assert not df[col].drop_nulls().str.contains(r"@[\w-]+\.").any(), col


def test_pubmed_parse():
    papers = {
        p["pmid"]: p for p in pubmed.parse_articles((FIXTURES / "pubmed_efetch.xml").read_bytes())
    }
    assert set(papers) >= {"35190816", "26865513"}
    review = papers["26865513"]
    assert "Review" in review["pub_types"] and pubmed.tier_for(review["pub_types"]) == "review"
    primary = papers["35190816"]
    assert pubmed.tier_for(primary["pub_types"]) == "peer_reviewed"
    assert primary["abstract"] and primary["journal"] and primary["year"]
    assert any(a["orcid"] for a in primary["authors"])
    affs = [x for p in papers.values() for a in p["authors"] for x in a["affiliations"]]
    assert affs and not any("@" in x for x in affs)
    assert pubmed.tier_for(["Journal Article", "Preprint"]) == "preprint"


def test_pubmed_normalize(data_dirs, scope):
    raw = data_dirs["raw"] / "pubmed"
    raw.mkdir(parents=True)
    shutil.copy(FIXTURES / "pubmed_efetch.xml", raw / "efetch_0000.xml")
    searches = [
        {
            "target_id": "HGNC:11444",
            "kind": "gene",
            "terms": ["STXBP1"],
            "query": "q1",
            "cap": 40,
            "pmids": ["35190816", "26865513"],
        },
        {
            "target_id": "MONDO:0100135",
            "kind": "disease",
            "terms": ["Dravet syndrome"],
            "query": "q2",
            "cap": 20,
            "pmids": ["35190816"],
        },
    ]
    (raw / "searches.json").write_text(json.dumps(searches))
    pubmed.normalize(scope)
    t = _tables(data_dirs["normalized"], "pubmed")
    nodes, a = t["nodes"], t["assertions"]
    assert {"PMID:35190816", "PMID:26865513"} <= set(nodes["id"])
    about = a.filter(pl.col("relation") == "about")
    stx = about.filter(pl.col("target_id") == "HGNC:11444")
    assert stx.height == 2 and stx["quote"].str.contains("STXBP1").all()
    assert about.filter(pl.col("source_id") == "PMID:26865513")["tier"].to_list() == ["review"]
    authored = a.filter(pl.col("relation") == "authored")
    assert authored.height > 10
    assert authored["source_id"].str.contains(r"^(ORCID:\d{4}-|RES:)").all()
    assert nodes.filter(pl.col("type") == "institution").height > 0
    paper_attrs = json.loads(nodes.filter(pl.col("id") == "PMID:35190816")["attrs"][0])
    assert "abstract" not in paper_attrs and paper_attrs["journal"]
    abstracts = pl.read_parquet(data_dirs["normalized"] / "pubmed" / "abstracts.parquet")
    assert abstracts.filter(pl.col("pmid") == "35190816")["abstract"][0]
    _no_contacts(t)


def test_clinicaltrials_scrub_and_normalize(data_dirs, scope):
    study = json.loads((FIXTURES / "ctgov_study.json").read_text())["studies"][0]
    scrubbed = clinicaltrials.scrub_study(study)
    dumped = json.dumps(scrubbed)
    assert "@" not in dumped and "phone" not in dumped and "centralContacts" not in dumped
    raw = data_dirs["raw"] / "clinicaltrials"
    raw.mkdir(parents=True)
    (raw / "studies.json").write_text(json.dumps({"NCT06625112": scrubbed}))
    clinicaltrials.normalize(scope)
    t = _tables(data_dirs["normalized"], "clinicaltrials")
    nodes, a = t["nodes"], t["assertions"]
    trial = nodes.filter(pl.col("id") == "NCT06625112")
    attrs = json.loads(trial["attrs"][0])
    assert attrs["status"] == "RECRUITING" and attrs["study_type"] == "OBSERVATIONAL"
    studies = a.filter(pl.col("relation") == "studies")
    assert set(studies["target_id"]) == {"MONDO:0012812"}
    assert set(studies["source_id"]) == {"NCT06625112", "REG:nct06625112"}
    reg = json.loads(nodes.filter(pl.col("id") == "REG:nct06625112")["attrs"][0])
    assert reg["kind"] == "registry"
    doctors = nodes.filter(pl.col("type") == "doctor")
    assert "Hannah Stamberger" in doctors["label"].to_list()
    assert doctors["id"].str.starts_with("DOC:").all()
    assert a.filter(pl.col("relation") == "investigator_of").height >= 4
    assert a.filter(pl.col("relation") == "runs").height == 1
    _no_contacts(t)


def test_clinicaltrials_person_filter():
    assert clinicaltrials.person_name("Jane Q. Doe, MD, PhD") == ("Jane Q. Doe", "Doe", "Jane")
    assert clinicaltrials.person_name("Medical Director") is None
    assert clinicaltrials.person_name("Clinical Trials, Acme Inc") is None
    assert clinicaltrials.person_name("Prof. Dr. Ingo Helbig") == ("Ingo Helbig", "Helbig", "Ingo")


def test_trial_without_scope_condition_is_dropped(data_dirs, scope):
    study = json.loads((FIXTURES / "ctgov_study.json").read_text())["studies"][0]
    study["protocolSection"]["conditionsModule"]["conditions"] = ["Epilepsy"]
    raw = data_dirs["raw"] / "clinicaltrials"
    raw.mkdir(parents=True)
    (raw / "studies.json").write_text(json.dumps({"NCT06625112": study}))
    clinicaltrials.normalize(scope)
    t = _tables(data_dirs["normalized"], "clinicaltrials")
    assert t["nodes"].height == 0 and t["assertions"].height == 0


def test_reporter_normalize(data_dirs, scope):
    projects = json.loads((FIXTURES / "reporter_project.json").read_text())["results"]
    raw = data_dirs["raw"] / "reporter"
    raw.mkdir(parents=True)
    (raw / "projects.json").write_text(json.dumps({str(p["appl_id"]): p for p in projects}))
    reporter.normalize(scope)
    t = _tables(data_dirs["normalized"], "reporter")
    nodes, a = t["nodes"], t["assertions"]
    grant = nodes.filter(pl.col("type") == "grant")
    assert grant["id"].to_list() == ["GRANT:F31NS141322"]
    attrs = json.loads(grant["attrs"][0])
    assert attrs["fiscal_years"] == [2026] and attrs["agency"] == "NINDS"
    funds = a.filter(pl.col("relation") == "funds_research_on")
    assert funds["target_id"].to_list() == ["MONDO:0012812"]
    assert "STXBP1-encephalopathy" in funds["quote"][0]
    pi = a.filter(pl.col("relation") == "pi_of")
    assert pi.height == 1 and pi["source_id"][0].startswith("RES:")
    assert a.filter(pl.col("relation") == "affiliated_with").height == 1


def test_patient_orgs_claims_need_verified_quotes(data_dirs, scope, monkeypatch, tmp_path):
    page_url = "https://www.kcnt1epilepsy.org/kcnt1-international-registry/"
    curated = {
        "organizations": [
            {
                "id": "ORG:kcnt1",
                "name": "KCNT1 Epilepsy Foundation",
                "url": page_url,
                "identity": {"url": page_url, "quote": "managed by the KCNT1 Epilepsy Foundation"},
                "serves": [
                    {
                        "disease": "MONDO:0013989",
                        "url": page_url,
                        "quote": "dedicated to individuals with changes in the KCNT1 gene",
                    }
                ],
            },
            {
                "id": "ORG:fake",
                "name": "Fake Org",
                "url": page_url,
                "identity": {"url": page_url, "quote": "Fake Org is a charity"},
                "serves": [{"disease": "MONDO:0013989", "url": page_url, "quote": "KCNT1"}],
            },
        ],
        "registries": [
            {
                "id": "REG:kcnt1",
                "name": "KCNT1 International Registry",
                "kind": "registry",
                "runs": [
                    {
                        "by": "ORG:kcnt1",
                        "url": page_url,
                        "quote": "The KCNT1 International Registry is a comprehensive database",
                    }
                ],
                "studies": [
                    {
                        "disease": "MONDO:0013989",
                        "url": page_url,
                        "quote": "this registry studies everything",
                    }
                ],
            },
        ],
    }
    yml = tmp_path / "orgs.yaml"
    yml.write_text(yaml.safe_dump(curated))
    monkeypatch.setattr(patient_orgs, "CURATED_FILE", yml)
    raw = data_dirs["raw"] / "patient_orgs"
    (raw / "pages").mkdir(parents=True)
    f = patient_orgs.page_file(page_url)
    (raw / f).write_text((FIXTURES / "kcnt1_registry_page.txt").read_text())
    (raw / "pages.json").write_text(
        json.dumps(
            [
                {
                    "url": page_url,
                    "origin": "curated",
                    "retrieved_at": "2026-10-03T00:00:00+00:00",
                    "file": f,
                }
            ]
        )
    )
    patient_orgs.normalize(scope)
    t = _tables(data_dirs["normalized"], "patient_orgs")
    nodes, a = t["nodes"], t["assertions"]
    assert set(nodes["id"]) == {"ORG:kcnt1", "REG:kcnt1"}
    rels = {(r["source_id"], r["relation"], r["target_id"]) for r in a.iter_rows(named=True)}
    assert rels == {("ORG:kcnt1", "serves", "MONDO:0013989"), ("ORG:kcnt1", "runs", "REG:kcnt1")}
    assert (a["url"] == page_url).all() and a["quote"].is_not_null().all()
    report = json.loads(
        (data_dirs["normalized"] / "patient_orgs" / "verification.json").read_text()
    )
    reasons = {r["reason"] for r in report["rejected_claims"]}
    assert reasons == {"quote_not_found"} and len(report["rejected_claims"]) == 2
    pages = pl.read_parquet(data_dirs["normalized"] / "patient_orgs" / "pages.parquet")
    assert pages["org_id"].to_list() == ["ORG:kcnt1"]


def test_curated_file_is_well_formed():
    data = patient_orgs.load_curated()
    ids = set()
    for section in ("networks", "organizations", "registries"):
        for entry in data[section]:
            assert entry["id"] not in ids
            ids.add(entry["id"])
            claims = [entry.get("identity")] if section != "registries" else []
            for key in ("serves", "member_of", "runs", "studies"):
                claims += entry.get(key) or []
            for c in claims:
                assert c["url"].startswith("https://") and c["quote"].strip()
    assert all(i.split(":")[0] in {"NET", "ORG", "REG"} for i in ids)
