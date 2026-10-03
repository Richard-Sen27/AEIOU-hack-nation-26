"""Parsers for the biology sources and their Stage 2 normalizers.

Raw files are parsed once into data/cache/parsed/*.parquet (keyed by the raw file's SHA-256), so
Stage 0 (scope), Stage 2 (normalize) and Stage 5 (analytics) share one fast representation.
"""

from __future__ import annotations

import csv
import gzip
import json
import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from functools import cache
from pathlib import Path

import polars as pl

from pipeline.contracts import Scope, assertion, raw_record, write_tables
from pipeline.paths import CACHE, RAW

log = logging.getLogger(__name__)

PARSED = CACHE / "parsed"

OBO = "http://purl.obolibrary.org/obo/"
MONDO_URL = "https://monarchinitiative.org/{}"
HGNC_URL = "https://www.genenames.org/data/gene-symbol-report/#!/hgnc_id/{}"
HPO_URL = "https://hpo.jax.org/browse/term/{}"
ORPHA_URL = "https://www.orpha.net/en/disease/detail/{}"
OMIM_URL = "https://omim.org/entry/{}"
REACTOME_URL = "https://reactome.org/content/detail/{}"
GO_URL = "https://amigo.geneontology.org/amigo/term/{}"
CLINVAR_URL = "https://www.ncbi.nlm.nih.gov/clinvar/variation/{}/"


def _cached(name: str, sources: list[tuple[str, str]]):
    """Cache a parser's DataFrame in data/cache/parsed/<name>.parquet keyed by raw SHA-256s."""

    def deco(fn: Callable[[], pl.DataFrame]):
        @cache
        def wrapper() -> pl.DataFrame:
            key = []
            for source, file in sources:
                rec = raw_record(source, file)
                if rec is None:
                    raise FileNotFoundError(f"raw {source}/{file} missing; run fetch first")
                key.append(rec["sha256"])
            out = PARSED / f"{name}.parquet"
            stamp = PARSED / f"{name}.key"
            if out.exists() and stamp.exists() and stamp.read_text() == ",".join(key):
                return pl.read_parquet(out)
            log.info("parsing %s", name)
            df = fn()
            PARSED.mkdir(parents=True, exist_ok=True)
            df.write_parquet(out)
            stamp.write_text(",".join(key))
            return df

        return wrapper

    return deco


def curie(iri: str) -> str:
    """http://purl.obolibrary.org/obo/MONDO_0100135 -> MONDO:0100135."""
    tail = iri.rsplit("/", 1)[-1]
    return tail.replace("_", ":", 1) if "_" in tail else tail


# ---------------------------------------------------------------- MONDO


def _exact_xref(val: str) -> str | None:
    m = re.match(r"https?://omim\.org/entry/(\d+)", val)
    if m:
        return f"OMIM:{m.group(1)}"
    m = re.match(r"https?://www\.orpha\.net/ORDO/Orphanet_(\d+)", val)
    if m:
        return f"ORPHA:{m.group(1)}"
    m = re.match(r"https?://identifiers\.org/medgen/(\w+)", val)
    if m:
        return f"MEDGEN:{m.group(1)}"
    return None


@_cached("mondo_terms", [("mondo", "mondo.json")])
def mondo_terms() -> pl.DataFrame:
    data = json.loads((RAW / "mondo" / "mondo.json").read_text())
    graph = data["graphs"][0]
    parents: dict[str, list[str]] = {}
    for e in graph["edges"]:
        if e["pred"] == "is_a" and "MONDO_" in e["sub"] and "MONDO_" in e["obj"]:
            parents.setdefault(curie(e["sub"]), []).append(curie(e["obj"]))
    rows = []
    for n in graph["nodes"]:
        if "MONDO_" not in n["id"] or n.get("type") != "CLASS":
            continue
        meta = n.get("meta", {})
        mid = curie(n["id"])
        syn_exact, syn_other = [], []
        for s in meta.get("synonyms", []):
            (syn_exact if s.get("pred") == "hasExactSynonym" else syn_other).append(s["val"])
        exact = sorted(
            {
                x
                for b in meta.get("basicPropertyValues", [])
                if b["pred"].endswith("skos/core#exactMatch") and (x := _exact_xref(b["val"]))
            }
        )
        xrefs = sorted({x["val"] for x in meta.get("xrefs", [])})
        rows.append(
            {
                "id": mid,
                "label": n.get("lbl"),
                "definition": (meta.get("definition") or {}).get("val"),
                "exact_synonyms": syn_exact,
                "other_synonyms": syn_other,
                "exact_matches": exact,
                "xrefs": xrefs,
                "parents": parents.get(mid, []),
                "deprecated": bool(meta.get("deprecated")),
                "rare": any(s.endswith("#rare") for s in meta.get("subsets", [])),
            }
        )
    return pl.DataFrame(rows, infer_schema_length=None)


@_cached("mondo_genes", [("mondo", "mondo.json")])
def mondo_genes() -> pl.DataFrame:
    """MONDO 'has material basis in germline mutation in' (RO:0004003) disease -> HGNC links."""
    data = json.loads((RAW / "mondo" / "mondo.json").read_text())
    rows = []
    for e in data["graphs"][0]["edges"]:
        if e["pred"].endswith("RO_0004003") and "hgnc/" in e["obj"]:
            refs = [
                b["val"]
                for b in (e.get("meta") or {}).get("basicPropertyValues", [])
                if b["pred"].endswith("#source")
            ]
            rows.append(
                {
                    "mondo_id": curie(e["sub"]),
                    "hgnc_id": "HGNC:" + e["obj"].rsplit("/", 1)[-1],
                    "refs": refs,
                }
            )
    return pl.DataFrame(rows, infer_schema_length=None)


def mondo_version() -> str | None:
    rec = raw_record("mondo", "mondo.json")
    path = RAW / "mondo" / "mondo.json"
    with path.open() as f:
        head = f.read(200_000)
    m = re.search(r"releases/(\d{4}-\d{2}-\d{2})/", head)
    return m.group(1) if m else (rec or {}).get("source_version")


@cache
def xref_to_mondo() -> dict[str, str]:
    """OMIM:/ORPHA:/MEDGEN: id -> MONDO id, from MONDO's exact matches (unambiguous ones only)."""
    terms = mondo_terms().filter(~pl.col("deprecated"))
    pairs = terms.select("id", "exact_matches").explode("exact_matches").drop_nulls()
    counts = pairs.group_by("exact_matches").agg(pl.col("id").unique())
    return {
        row["exact_matches"]: row["id"][0]
        for row in counts.iter_rows(named=True)
        if len(row["id"]) == 1
    }


# ---------------------------------------------------------------- HGNC


def _split(v: str | None) -> list[str]:
    if not v:
        return []
    return [s.strip() for s in v.strip('"').split("|") if s.strip()]


@_cached("hgnc", [("hgnc", "hgnc_complete_set.txt")])
def hgnc() -> pl.DataFrame:
    rows = []
    with (RAW / "hgnc" / "hgnc_complete_set.txt").open(newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if r["status"] != "Approved":
                continue
            rows.append(
                {
                    "hgnc_id": r["hgnc_id"],
                    "symbol": r["symbol"],
                    "name": r["name"],
                    "locus_group": r["locus_group"],
                    "location": r["location"],
                    "aliases": _split(r["alias_symbol"]),
                    "alias_names": _split(r["alias_name"]),
                    "prev_symbols": _split(r["prev_symbol"]),
                    "entrez_id": r["entrez_id"] or None,
                    "ensembl_id": r["ensembl_gene_id"] or None,
                    "uniprot_ids": _split(r["uniprot_ids"]),
                    "omim_ids": _split(r["omim_id"]),
                }
            )
    return pl.DataFrame(rows, infer_schema_length=None)


@cache
def gene_lookup() -> dict[str, str]:
    """Upper-cased symbol / previous symbol / alias -> HGNC id. Approved symbols win."""
    df = hgnc()
    out: dict[str, str] = {}
    for col in ("aliases", "prev_symbols"):
        for hid, names in df.select("hgnc_id", col).iter_rows():
            for n in names:
                out.setdefault(n.upper(), hid)
    for hid, sym in df.select("hgnc_id", "symbol").iter_rows():
        out[sym.upper()] = hid
    return out


@cache
def entrez_to_hgnc() -> dict[str, str]:
    return {e: h for h, e in hgnc().select("hgnc_id", "entrez_id").iter_rows() if e}


@cache
def uniprot_to_hgnc() -> dict[str, str]:
    out = {}
    for h, ups in hgnc().select("hgnc_id", "uniprot_ids").iter_rows():
        for u in ups:
            out.setdefault(u, h)
    return out


def resolve_gene(name: str) -> str | None:
    """Gene symbol, alias, previous symbol or HGNC id -> HGNC id."""
    name = name.strip()
    if name.upper().startswith("HGNC:"):
        return "HGNC:" + name.split(":", 1)[1]
    return gene_lookup().get(name.upper())


# ---------------------------------------------------------------- HPO


@_cached("hpo_terms", [("hpo", "hp.json")])
def hpo_terms() -> pl.DataFrame:
    data = json.loads((RAW / "hpo" / "hp.json").read_text())
    graph = data["graphs"][0]
    parents: dict[str, list[str]] = {}
    for e in graph["edges"]:
        if e["pred"] == "is_a":
            parents.setdefault(curie(e["sub"]), []).append(curie(e["obj"]))
    rows = []
    for n in graph["nodes"]:
        if "HP_" not in n["id"] or n.get("type") != "CLASS":
            continue
        meta = n.get("meta", {})
        hid = curie(n["id"])
        rows.append(
            {
                "id": hid,
                "label": n.get("lbl"),
                "definition": (meta.get("definition") or {}).get("val"),
                "synonyms": [s["val"] for s in meta.get("synonyms", [])],
                "parents": parents.get(hid, []),
                "deprecated": bool(meta.get("deprecated")),
            }
        )
    return pl.DataFrame(rows, infer_schema_length=None)


FREQ_HP = {
    "HP:0040280": 1.0,  # obligate
    "HP:0040281": 0.9,  # very frequent
    "HP:0040282": 0.55,  # frequent
    "HP:0040283": 0.17,  # occasional
    "HP:0040284": 0.025,  # very rare
    "HP:0040285": 0.0,  # excluded
}


def parse_frequency(v: str | None) -> float | None:
    if not v or v == "-":
        return None
    if v in FREQ_HP:
        return FREQ_HP[v]
    m = re.match(r"(\d+)/(\d+)$", v)
    if m and int(m.group(2)):
        return int(m.group(1)) / int(m.group(2))
    m = re.match(r"([\d.]+)%$", v)
    if m:
        return float(m.group(1)) / 100
    return None


@_cached("hpoa", [("hpo", "phenotype.hpoa")])
def hpoa() -> pl.DataFrame:
    """Disease -> phenotype annotations (aspect P only, NOT-qualified rows kept with a flag)."""
    rows = []
    with (RAW / "hpo" / "phenotype.hpoa").open() as f:
        lines = (line for line in f if not line.startswith("#"))
        for r in csv.DictReader(lines, delimiter="\t"):
            if r["aspect"] != "P":
                continue
            rows.append(
                {
                    "disease_id": r["database_id"].replace("ORPHA:", "ORPHA:"),
                    "disease_name": r["disease_name"],
                    "negated": r["qualifier"] == "NOT",
                    "hpo_id": r["hpo_id"],
                    "reference": r["reference"],
                    "evidence": r["evidence"],
                    "frequency_raw": r["frequency"],
                    "frequency": parse_frequency(r["frequency"]),
                }
            )
    return pl.DataFrame(rows, infer_schema_length=None)


@_cached("hpo_g2p", [("hpo", "genes_to_phenotype.txt")])
def hpo_gene_disease() -> pl.DataFrame:
    """Gene -> disease pairs implied by genes_to_phenotype.txt (OMIM/Orphanet derived)."""
    df = pl.read_csv(
        RAW / "hpo" / "genes_to_phenotype.txt", separator="\t", infer_schema=False, quote_char=None
    )
    return df.select(
        pl.col("ncbi_gene_id").alias("entrez_id"),
        pl.col("gene_symbol").alias("symbol"),
        "disease_id",
    ).unique()


def hpo_version() -> str | None:
    with (RAW / "hpo" / "hp.json").open() as f:
        head = f.read(20_000)
    m = re.search(r"releases/(\d{4}-\d{2}-\d{2})/", head)
    return m.group(1) if m else None


# ---------------------------------------------------------------- ClinGen


@_cached("clingen_validity", [("clingen", "gene_validity.csv")])
def clingen_validity() -> pl.DataFrame:
    rows = []
    with (RAW / "clingen" / "gene_validity.csv").open(newline="") as f:
        reader = csv.reader(f)
        header = None
        for r in reader:
            if r and r[0] == "GENE SYMBOL":
                header = r
                continue
            if header is None or not r or r[0].startswith("+"):
                continue
            d = dict(zip(header, r, strict=False))
            rows.append(
                {
                    "symbol": d["GENE SYMBOL"],
                    "hgnc_id": d["GENE ID (HGNC)"],
                    "disease_label": d["DISEASE LABEL"],
                    "mondo_id": d["DISEASE ID (MONDO)"],
                    "moi": d["MOI"],
                    "classification": d["CLASSIFICATION"],
                    "url": d["ONLINE REPORT"],
                    "date": d["CLASSIFICATION DATE"][:10],
                    "gcep": d["GCEP"],
                }
            )
    return pl.DataFrame(rows, infer_schema_length=None)


@_cached("clingen_dosage", [("clingen", "ClinGen_gene_curation_list_GRCh38.tsv")])
def clingen_dosage() -> pl.DataFrame:
    rows = []
    with (RAW / "clingen" / "ClinGen_gene_curation_list_GRCh38.tsv").open() as f:
        header = None
        for line in f:
            if line.startswith("#Gene Symbol"):
                header = line[1:].rstrip("\n").split("\t")
                continue
            if line.startswith("#") or header is None:
                continue
            d = dict(zip(header, line.rstrip("\n").split("\t"), strict=False))
            pmids = [
                p.strip()
                for k, v in d.items()
                if k.startswith("Haploinsufficiency PMID")
                for p in v.split(",")
                if p.strip()
            ]
            rows.append(
                {
                    "symbol": d["Gene Symbol"],
                    "entrez_id": d["Gene ID"],
                    "hi_score": d["Haploinsufficiency Score"],
                    "hi_description": d["Haploinsufficiency Description"],
                    "hi_pmids": pmids,
                    "ts_score": d["Triplosensitivity Score"],
                    "hi_disease": d.get("Haploinsufficiency Disease ID") or None,
                    "date": d["Date Last Evaluated"],
                }
            )
    return pl.DataFrame(rows, infer_schema_length=None)


# ---------------------------------------------------------------- Orphanet


def _orpha_disorders(file: str):
    for _, el in ET.iterparse(RAW / "orphanet" / file, events=("end",)):
        if el.tag == "Disorder" and el.find("OrphaCode") is not None:
            yield el
            el.clear()


@_cached("orphanet_genes", [("orphanet", "en_product6.xml")])
def orphanet_genes() -> pl.DataFrame:
    rows = []
    for d in _orpha_disorders("en_product6.xml"):
        code, name = d.findtext("OrphaCode"), d.findtext("Name")
        for a in d.iter("DisorderGeneAssociation"):
            gene = a.find("Gene")
            hgnc_ref = None
            for ref in gene.iter("ExternalReference"):
                if ref.findtext("Source") == "HGNC":
                    hgnc_ref = "HGNC:" + ref.findtext("Reference")
            pmids = re.findall(r"(\d+)\[PMID\]", a.findtext("SourceOfValidation") or "")
            rows.append(
                {
                    "orpha": f"ORPHA:{code}",
                    "name": name,
                    "symbol": gene.findtext("Symbol"),
                    "hgnc_id": hgnc_ref,
                    "assoc_type": a.findtext("DisorderGeneAssociationType/Name"),
                    "status": a.findtext("DisorderGeneAssociationStatus/Name"),
                    "pmids": pmids,
                }
            )
    return pl.DataFrame(rows, infer_schema_length=None)


@_cached("orphanet_phenotypes", [("orphanet", "en_product4.xml")])
def orphanet_phenotypes() -> pl.DataFrame:
    rows = []
    for d in _orpha_disorders("en_product4.xml"):
        code = d.findtext("OrphaCode")
        for a in d.iter("HPODisorderAssociation"):
            rows.append(
                {
                    "orpha": f"ORPHA:{code}",
                    "hpo_id": a.findtext("HPO/HPOId"),
                    "frequency_raw": a.findtext("HPOFrequency/Name"),
                }
            )
    return pl.DataFrame(rows, infer_schema_length=None)


@_cached("orphanet_prevalence", [("orphanet", "en_product9_prev.xml")])
def orphanet_prevalence() -> pl.DataFrame:
    rows = []
    for d in _orpha_disorders("en_product9_prev.xml"):
        code = d.findtext("OrphaCode")
        for p in d.iter("Prevalence"):
            rows.append(
                {
                    "orpha": f"ORPHA:{code}",
                    "type": p.findtext("PrevalenceType/Name"),
                    "qualification": p.findtext("PrevalenceQualification/Name"),
                    "class": p.findtext("PrevalenceClass/Name"),
                    "val_moy": p.findtext("ValMoy"),
                    "geographic": p.findtext("PrevalenceGeographic/Name"),
                    "validation": p.findtext("PrevalenceValidationStatus/Name"),
                    "source": p.findtext("Source"),
                }
            )
    return pl.DataFrame(rows, infer_schema_length=None)


ORPHA_FREQ = {
    "Obligate (100%)": 1.0,
    "Very frequent (99-80%)": 0.9,
    "Frequent (79-30%)": 0.55,
    "Occasional (29-5%)": 0.17,
    "Very rare (<4-1%)": 0.025,
    "Excluded (0%)": 0.0,
}


def orphanet_version() -> str | None:
    with (RAW / "orphanet" / "en_product6.xml").open() as f:
        head = f.read(500)
    m = re.search(r'date="([\d-]+)', head)
    return m.group(1) if m else None


# ---------------------------------------------------------------- Reactome and GO


@_cached("reactome", [("reactome", "NCBI2Reactome.txt"), ("reactome", "ReactomePathways.txt")])
def reactome() -> pl.DataFrame:
    names = {}
    with (RAW / "reactome" / "ReactomePathways.txt").open() as f:
        for line in f:
            pid, name, species = line.rstrip("\n").split("\t")
            if species == "Homo sapiens":
                names[pid] = name.strip()
    rows = []
    e2h = entrez_to_hgnc()
    with (RAW / "reactome" / "NCBI2Reactome.txt").open() as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) < 6 or p[5] != "Homo sapiens" or p[0] not in e2h:
                continue
            rows.append(
                {
                    "hgnc_id": e2h[p[0]],
                    "pathway_id": p[1],
                    "name": names.get(p[1], p[3].strip()),
                    "evidence": p[4],
                }
            )
    return pl.DataFrame(rows).unique(["hgnc_id", "pathway_id"])


def _obo_terms(path: Path, namespace: str | None = None) -> dict[str, dict]:
    terms, cur = {}, None
    with path.open() as f:
        for line in f:
            line = line.rstrip("\n")
            if line == "[Term]":
                cur = {"is_a": []}
                continue
            if line.startswith("[") or not line:
                if cur and "id" in cur and not cur.get("obsolete"):
                    if namespace is None or cur.get("namespace") == namespace:
                        terms[cur["id"]] = cur
                cur = None if line.startswith("[") else cur
                continue
            if cur is None or ": " not in line:
                continue
            k, v = line.split(": ", 1)
            if k == "is_a":
                cur["is_a"].append(v.split(" ! ")[0])
            elif k in ("id", "name", "namespace"):
                cur[k] = v
            elif k == "is_obsolete" and v == "true":
                cur["obsolete"] = True
    return terms


GO_EVIDENCE_EXCLUDE = {"IEA", "ND", "NAS"}


@_cached("go", [("go", "goa_human.gaf.gz"), ("go", "go-basic.obo")])
def go_annotations() -> pl.DataFrame:
    """Gene -> GO biological process, experimental/curated evidence only (no IEA/ND/NAS)."""
    names = {k: v["name"] for k, v in _obo_terms(RAW / "go" / "go-basic.obo", "biological_process").items()}
    up = uniprot_to_hgnc()
    rows = []
    with gzip.open(RAW / "go" / "goa_human.gaf.gz", "rt") as f:
        for line in f:
            if line.startswith("!"):
                continue
            p = line.rstrip("\n").split("\t")
            if p[8] != "P" or "NOT" in p[3] or p[6] in GO_EVIDENCE_EXCLUDE or p[4] not in names:
                continue
            hid = up.get(p[1]) or resolve_gene(p[2])
            if hid:
                rows.append({"hgnc_id": hid, "go_id": p[4], "name": names[p[4]], "evidence": p[6], "ref": p[5]})
    return pl.DataFrame(rows).unique(["hgnc_id", "go_id"], keep="first")


# ---------------------------------------------------------------- gene-disease associations

CAUSAL_ORPHA_TYPES = {
    "Disease-causing germline mutation(s) in": None,
    "Disease-causing germline mutation(s) (loss of function) in": "loss_of_function",
    "Disease-causing germline mutation(s) (gain of function) in": "gain_of_function",
}
CLINGEN_SUPPORTING = {"Definitive", "Strong", "Moderate"}
CLINGEN_CONTRADICTING = {"Refuted", "Disputed"}


@cache
def gene_disease() -> pl.DataFrame:
    """All causal gene -> MONDO disease links with their provenance.

    Columns: mondo_id, hgnc_id, source, ref, url, polarity, mechanism (Orphanet LoF/GoF hint),
    detail. Diseases are mapped to MONDO via exact matches; unmapped ones are dropped (logged).
    """
    x2m = xref_to_mondo()
    e2h = entrez_to_hgnc()
    rows: list[dict] = []
    for r in mondo_genes().iter_rows(named=True):
        rows.append(
            {
                "mondo_id": r["mondo_id"],
                "hgnc_id": r["hgnc_id"],
                "source": "mondo",
                "ref": ";".join(r["refs"]) or r["mondo_id"],
                "url": MONDO_URL.format(r["mondo_id"]),
                "polarity": "supports",
                "mechanism": None,
                "detail": "has material basis in germline mutation in",
            }
        )
    for r in clingen_validity().iter_rows(named=True):
        cls = r["classification"]
        if cls not in CLINGEN_SUPPORTING | CLINGEN_CONTRADICTING:
            continue
        rows.append(
            {
                "mondo_id": r["mondo_id"],
                "hgnc_id": r["hgnc_id"],
                "source": "clingen",
                "ref": r["url"].rsplit("/", 1)[-1],
                "url": r["url"],
                "polarity": "supports" if cls in CLINGEN_SUPPORTING else "contradicts",
                "mechanism": None,
                "detail": f"ClinGen gene-disease validity: {cls} ({r['moi']}, {r['gcep']}, {r['date']})",
            }
        )
    unmapped = 0
    for r in orphanet_genes().iter_rows(named=True):
        if r["assoc_type"] not in CAUSAL_ORPHA_TYPES or r["status"] != "Assessed":
            continue
        mid = x2m.get(r["orpha"])
        hid = r["hgnc_id"] or resolve_gene(r["symbol"] or "")
        if not mid or not hid:
            unmapped += 1
            continue
        code = r["orpha"].split(":")[1]
        rows.append(
            {
                "mondo_id": mid,
                "hgnc_id": hid,
                "source": "orphanet",
                "ref": r["orpha"],
                "url": ORPHA_URL.format(code),
                "polarity": "supports",
                "mechanism": CAUSAL_ORPHA_TYPES[r["assoc_type"]],
                "detail": f"{r['assoc_type']} {r['symbol']}"
                + (f" (PMID {', '.join(r['pmids'])})" if r["pmids"] else ""),
            }
        )
    for r in hpo_gene_disease().iter_rows(named=True):
        mid = x2m.get(r["disease_id"])
        hid = e2h.get(r["entrez_id"]) or resolve_gene(r["symbol"])
        if not mid or not hid:
            unmapped += 1
            continue
        db, acc = r["disease_id"].split(":", 1)
        rows.append(
            {
                "mondo_id": mid,
                "hgnc_id": hid,
                "source": "hpo",
                "ref": r["disease_id"],
                "url": OMIM_URL.format(acc) if db == "OMIM" else ORPHA_URL.format(acc),
                "polarity": "supports",
                "mechanism": None,
                "detail": f"HPO gene-disease annotation via {r['disease_id']}",
            }
        )
    log.info("gene_disease: %d links (%d unmapped to MONDO/HGNC)", len(rows), unmapped)
    return pl.DataFrame(rows, infer_schema_length=None).unique(["mondo_id", "hgnc_id", "source", "ref"])


@cache
def disease_phenotypes() -> pl.DataFrame:
    """MONDO disease -> HPO term with frequency, merged from HPO annotations and Orphanet."""
    x2m = xref_to_mondo()
    a = hpoa().filter(~pl.col("negated"))
    a = a.with_columns(
        pl.col("disease_id").replace_strict(x2m, default=None).alias("mondo_id")
    ).drop_nulls("mondo_id")
    a = a.select(
        "mondo_id",
        "hpo_id",
        "frequency",
        pl.col("disease_id").alias("ref"),
        pl.lit("hpo").alias("source"),
    )
    o = orphanet_phenotypes()
    o = o.with_columns(
        pl.col("orpha").replace_strict(x2m, default=None).alias("mondo_id"),
        pl.col("frequency_raw").replace_strict(ORPHA_FREQ, default=None).alias("frequency"),
    ).drop_nulls("mondo_id")
    o = o.select("mondo_id", "hpo_id", "frequency", pl.col("orpha").alias("ref"), pl.lit("orphanet").alias("source"))
    df = pl.concat([a, o], how="vertical_relaxed")
    return df.filter(pl.col("frequency").is_null() | (pl.col("frequency") > 0))


# ---------------------------------------------------------------- normalizers


def _retrieved(source: str, file: str) -> str | None:
    rec = raw_record(source, file)
    return rec["retrieved_at"] if rec else None


def normalize_mondo(scope: Scope) -> None:
    terms = mondo_terms().filter(pl.col("id").is_in(list(scope.disease_ids)))
    nodes, syns = [], []
    for t in terms.iter_rows(named=True):
        xrefs = [x for x in t["xrefs"] if x.split(":")[0] in ("OMIM", "Orphanet", "MEDGEN", "GARD", "DOID", "NORD")]
        nodes.append(
            {
                "id": t["id"],
                "type": "disease",
                "label": t["label"],
                "description": t["definition"],
                "url": MONDO_URL.format(t["id"]),
                "attrs": {"xrefs": xrefs, "exact_matches": t["exact_matches"], "rare": t["rare"]},
            }
        )
        syns.append({"node_id": t["id"], "synonym": t["label"], "source": "mondo"})
        for s in t["exact_synonyms"] + t["other_synonyms"]:
            syns.append({"node_id": t["id"], "synonym": s, "source": "mondo"})
    # Disease -> gene from MONDO itself.
    retrieved = _retrieved("mondo", "mondo.json")
    gd = gene_disease().filter(
        (pl.col("source") == "mondo")
        & pl.col("mondo_id").is_in(list(scope.disease_ids))
        & pl.col("hgnc_id").is_in(list(scope.gene_ids))
    )
    rows = [_gd_assertion(r, retrieved) for r in gd.iter_rows(named=True)]
    write_tables("mondo", nodes, syns, rows)


def _gd_assertion(r: dict, retrieved: str | None) -> dict:
    return assertion(
        r["mondo_id"],
        r["hgnc_id"],
        "caused_by_variant_in",
        tier="curated_db",
        source_type=r["source"],
        source_ref=r["ref"],
        url=r["url"],
        quote=r["detail"],
        retrieved_at=retrieved,
        polarity=r["polarity"],
        features={"mechanism_hint": r["mechanism"]} if r["mechanism"] else None,
    )


def normalize_hgnc(scope: Scope) -> None:
    genes = hgnc().filter(pl.col("hgnc_id").is_in(list(scope.gene_ids)))
    dosage = {r["symbol"]: r for r in clingen_dosage().iter_rows(named=True)}
    nodes, syns = [], []
    for g in genes.iter_rows(named=True):
        attrs = {
            "symbol": g["symbol"],
            "locus_group": g["locus_group"],
            "location": g["location"],
            "entrez_id": g["entrez_id"],
            "ensembl_id": g["ensembl_id"],
            "uniprot_ids": g["uniprot_ids"],
            "omim_ids": g["omim_ids"],
        }
        if d := dosage.get(g["symbol"]):
            attrs["clingen_hi_score"] = d["hi_score"]
            attrs["clingen_ts_score"] = d["ts_score"]
        nodes.append(
            {
                "id": g["hgnc_id"],
                "type": "gene",
                "label": g["symbol"],
                "description": g["name"],
                "url": HGNC_URL.format(g["hgnc_id"]),
                "attrs": attrs,
            }
        )
        for s in [g["symbol"], g["name"], *g["aliases"], *g["prev_symbols"], *g["alias_names"]]:
            syns.append({"node_id": g["hgnc_id"], "synonym": s, "source": "hgnc"})
    write_tables("hgnc", nodes, syns, [])


PHENOTYPES_PER_DISEASE = 40


def normalize_hpo(scope: Scope) -> None:
    keep = scope.phenotype_ids
    terms = hpo_terms().filter(pl.col("id").is_in(list(keep)))
    nodes, syns = [], []
    for t in terms.iter_rows(named=True):
        nodes.append(
            {
                "id": t["id"],
                "type": "phenotype",
                "label": t["label"],
                "description": t["definition"],
                "url": HPO_URL.format(t["id"]),
                "attrs": {},
            }
        )
        syns.append({"node_id": t["id"], "synonym": t["label"], "source": "hpo"})
        for s in t["synonyms"]:
            syns.append({"node_id": t["id"], "synonym": s, "source": "hpo"})
    retrieved = _retrieved("hpo", "phenotype.hpoa")
    rows = []
    dp = disease_phenotypes().filter(
        (pl.col("source") == "hpo")
        & pl.col("mondo_id").is_in(list(scope.disease_ids))
        & pl.col("hpo_id").is_in(list(keep))
    )
    for r in dp.unique(["mondo_id", "hpo_id", "ref"]).iter_rows(named=True):
        db, acc = r["ref"].split(":", 1)
        rows.append(
            assertion(
                r["mondo_id"],
                r["hpo_id"],
                "has_phenotype",
                tier="curated_db",
                source_type="hpo",
                source_ref=r["ref"],
                url=f"https://hpo.jax.org/browse/disease/{r['ref']}",
                retrieved_at=retrieved,
                features={"frequency": r["frequency"]} if r["frequency"] is not None else None,
            )
        )
    gd = gene_disease().filter(
        (pl.col("source") == "hpo")
        & pl.col("mondo_id").is_in(list(scope.disease_ids))
        & pl.col("hgnc_id").is_in(list(scope.gene_ids))
    )
    g_retrieved = _retrieved("hpo", "genes_to_phenotype.txt")
    rows += [_gd_assertion(r, g_retrieved) for r in gd.iter_rows(named=True)]
    write_tables("hpo", nodes, syns, rows)


def normalize_clingen(scope: Scope) -> None:
    retrieved = _retrieved("clingen", "gene_validity.csv")
    gd = gene_disease().filter(
        (pl.col("source") == "clingen")
        & pl.col("mondo_id").is_in(list(scope.disease_ids))
        & pl.col("hgnc_id").is_in(list(scope.gene_ids))
    )
    rows = [_gd_assertion(r, retrieved) for r in gd.iter_rows(named=True)]
    # Dosage: haploinsufficiency (score 3) is curated loss-of-function evidence.
    d_retrieved = _retrieved("clingen", "ClinGen_gene_curation_list_GRCh38.tsv")
    sym2id = {g["symbol"]: g["hgnc_id"] for g in scope.genes}
    for r in clingen_dosage().iter_rows(named=True):
        hid = sym2id.get(r["symbol"])
        if hid and r["hi_score"] == "3":
            rows.append(
                assertion(
                    hid,
                    "MECH:loss_of_function",
                    "acts_via",
                    tier="curated_db",
                    source_type="clingen",
                    source_ref=f"ClinGen dosage {r['symbol']}",
                    url=f"https://search.clinicalgenome.org/kb/genes/{hid}",
                    quote=f"Haploinsufficiency score 3: {r['hi_description']}",
                    retrieved_at=d_retrieved,
                    features={
                        "clingen_hi_score": 3,
                        "hi_disease": r["hi_disease"],
                        "pmids": r["hi_pmids"],
                    },
                )
            )
    write_tables("clingen", [], [], rows)


def normalize_orphanet(scope: Scope) -> None:
    retrieved = _retrieved("orphanet", "en_product6.xml")
    gd = gene_disease().filter(
        (pl.col("source") == "orphanet")
        & pl.col("mondo_id").is_in(list(scope.disease_ids))
        & pl.col("hgnc_id").is_in(list(scope.gene_ids))
    )
    rows = [_gd_assertion(r, retrieved) for r in gd.iter_rows(named=True)]
    p_retrieved = _retrieved("orphanet", "en_product4.xml")
    dp = disease_phenotypes().filter(
        (pl.col("source") == "orphanet")
        & pl.col("mondo_id").is_in(list(scope.disease_ids))
        & pl.col("hpo_id").is_in(list(scope.phenotype_ids))
    )
    for r in dp.unique(["mondo_id", "hpo_id", "ref"]).iter_rows(named=True):
        rows.append(
            assertion(
                r["mondo_id"],
                r["hpo_id"],
                "has_phenotype",
                tier="curated_db",
                source_type="orphanet",
                source_ref=r["ref"],
                url=ORPHA_URL.format(r["ref"].split(":")[1]),
                retrieved_at=p_retrieved,
                features={"frequency": r["frequency"]} if r["frequency"] is not None else None,
            )
        )
    # Prevalence goes onto the disease node as attrs (merged in Stage 4).
    x2m = xref_to_mondo()
    prev: dict[str, list[dict]] = {}
    for r in orphanet_prevalence().iter_rows(named=True):
        mid = x2m.get(r["orpha"])
        if mid in scope.disease_ids and r["validation"] == "Validated":
            prev.setdefault(mid, []).append(
                {k: r[k] for k in ("orpha", "type", "class", "val_moy", "geographic", "source")}
            )
    nodes = [
        {"id": mid, "type": "disease", "attrs": {"orphanet_prevalence": items[:5]}}
        for mid, items in prev.items()
    ]
    write_tables("orphanet", nodes, [], rows)


PATHWAY_MAX_GENES = 300  # pathways larger than this (genome-wide) stay out of the graph


def _pathway_rows(df: pl.DataFrame, id_col: str, scope: Scope) -> pl.DataFrame:
    sizes = df.group_by(id_col).len("n_genes")
    return (
        df.join(sizes, on=id_col)
        .filter(pl.col("hgnc_id").is_in(list(scope.gene_ids)) & (pl.col("n_genes") <= PATHWAY_MAX_GENES))
    )


def normalize_reactome(scope: Scope) -> None:
    df = _pathway_rows(reactome(), "pathway_id", scope)
    retrieved = _retrieved("reactome", "NCBI2Reactome.txt")
    nodes, syns, rows = {}, [], []
    for r in df.iter_rows(named=True):
        pid = f"REACT:{r['pathway_id']}"
        nodes[pid] = {
            "id": pid,
            "type": "pathway",
            "label": r["name"],
            "description": None,
            "url": REACTOME_URL.format(r["pathway_id"]),
            "attrs": {"source": "reactome", "n_genes": r["n_genes"]},
        }
        rows.append(
            assertion(
                r["hgnc_id"],
                pid,
                "participates_in",
                tier="curated_db",
                source_type="reactome",
                source_ref=r["pathway_id"],
                url=REACTOME_URL.format(r["pathway_id"]),
                retrieved_at=retrieved,
                features={"evidence": r["evidence"], "pathway_size": r["n_genes"]},
            )
        )
    for n in nodes.values():
        syns.append({"node_id": n["id"], "synonym": n["label"], "source": "reactome"})
    write_tables("reactome", list(nodes.values()), syns, rows)


GO_MIN_GENES = 3
GO_MAX_GENES = 150
GO_MAX_PER_GENE = 5


def normalize_go(scope: Scope) -> None:
    df = go_annotations()
    sizes = df.group_by("go_id").len("n_genes")
    df = df.join(sizes, on="go_id").filter(
        pl.col("hgnc_id").is_in(list(scope.gene_ids))
        & pl.col("n_genes").is_between(GO_MIN_GENES, GO_MAX_GENES)
    )
    # Most specific (smallest) processes first, a handful per gene keeps the graph explorable.
    df = df.sort(["hgnc_id", "n_genes"]).group_by("hgnc_id", maintain_order=True).head(GO_MAX_PER_GENE)
    retrieved = _retrieved("go", "goa_human.gaf.gz")
    nodes, syns, rows = {}, [], []
    for r in df.iter_rows(named=True):
        nodes[r["go_id"]] = {
            "id": r["go_id"],
            "type": "pathway",
            "label": r["name"],
            "description": None,
            "url": GO_URL.format(r["go_id"]),
            "attrs": {"source": "go", "aspect": "biological_process", "n_genes": r["n_genes"]},
        }
        rows.append(
            assertion(
                r["hgnc_id"],
                r["go_id"],
                "participates_in",
                tier="curated_db",
                source_type="go",
                source_ref=r["ref"],
                url=GO_URL.format(r["go_id"]),
                retrieved_at=retrieved,
                features={"evidence": r["evidence"], "pathway_size": r["n_genes"]},
            )
        )
    for n in nodes.values():
        syns.append({"node_id": n["id"], "synonym": n["label"], "source": "go"})
    write_tables("go", list(nodes.values()), syns, rows)


def normalize_omim(scope: Scope) -> None:
    path = RAW / "omim" / "genemap2.txt"
    if not path.exists():
        write_tables("omim", [], [], [])
        return
    x2m = xref_to_mondo()
    retrieved = _retrieved("omim", "genemap2.txt")
    rows = []
    with path.open() as f:
        header = None
        for line in f:
            if line.startswith("# Chromosome"):
                header = line[2:].rstrip("\n").split("\t")
                continue
            if line.startswith("#") or header is None:
                continue
            d = dict(zip(header, line.rstrip("\n").split("\t"), strict=False))
            hid = resolve_gene(d.get("Approved Gene Symbol") or "")
            if hid not in scope.gene_ids:
                continue
            for m in re.finditer(r"(\d{6}) \((\d)\)", d.get("Phenotypes", "")):
                mid = x2m.get(f"OMIM:{m.group(1)}")
                if mid in scope.disease_ids and m.group(2) == "3":
                    rows.append(
                        assertion(
                            mid,
                            hid,
                            "caused_by_variant_in",
                            tier="curated_db",
                            source_type="omim",
                            source_ref=f"OMIM:{m.group(1)}",
                            url=OMIM_URL.format(m.group(1)),
                            retrieved_at=retrieved,
                        )
                    )
    write_tables("omim", [], [], rows)


# ---------------------------------------------------------------- ClinVar

CLASSIFICATIONS = [
    ("pathogenic/likely pathogenic", "likely_pathogenic"),
    ("likely pathogenic", "likely_pathogenic"),
    ("pathogenic", "pathogenic"),
    ("uncertain significance", "uncertain_significance"),
    ("conflicting classifications of pathogenicity", "conflicting"),
    ("conflicting interpretations of pathogenicity", "conflicting"),
    ("likely benign", "likely_benign"),
    ("benign/likely benign", "likely_benign"),
    ("benign", "benign"),
]

REVIEW_STARS = {
    "practice guideline": 4,
    "reviewed by expert panel": 3,
    "criteria provided, multiple submitters, no conflicts": 2,
    "criteria provided, conflicting classifications": 1,
    "criteria provided, conflicting interpretations": 1,
    "criteria provided, single submitter": 1,
}


def classify(sig: str) -> str | None:
    s = sig.lower().split(";")[0].split(",")[0].strip()
    for k, v in CLASSIFICATIONS:
        if s == k:
            return v
    return None


def review_stars(status: str) -> int:
    return REVIEW_STARS.get(status.strip().lower(), 0)


_PROTEIN = re.compile(r"\(p\.([^)]+)\)")


def consequence(name: str, vtype: str) -> str:
    """Coarse molecular consequence from the HGVS name in variant_summary."""
    m = _PROTEIN.search(name)
    if m:
        p = m.group(1)
        if "fs" in p:
            return "frameshift"
        if p.endswith("Ter") or p.endswith("*") or "Ter" in p.split("ext")[0][-4:]:
            return "nonsense"
        if p.endswith("=") or re.fullmatch(r"[A-Z][a-z]{2}\d+[A-Z][a-z]{2}", p) is None:
            if p.endswith("="):
                return "synonymous"
            if "del" in p or "ins" in p or "dup" in p:
                return "inframe_indel"
            if p.startswith("Met1"):
                return "start_lost"
            return "other"
        return "missense"
    if re.search(r"c\.[-*]?\d+[+-][12][ACGT]?>|c\.\d+[+-][12]del|c\.\d+[+-][12]dup", name):
        return "splice"
    if vtype.lower() in ("deletion", "duplication", "copy number loss", "copy number gain"):
        return "copy_number" if "copy number" in vtype.lower() else "indel"
    return "other"


TRUNCATING = {"frameshift", "nonsense", "splice", "start_lost"}


@_cached("clinvar", [("clinvar", "variant_summary.scope.tsv.gz")])
def clinvar_variants() -> pl.DataFrame:
    rows = []
    with gzip.open(RAW / "clinvar" / "variant_summary.scope.tsv.gz", "rt") as f:
        reader = csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE)
        for r in reader:
            cls = classify(r["ClinicalSignificance"])
            if cls is None:
                continue
            ids = r["PhenotypeIDS"].replace("|", ";").replace(",", ";").split(";")
            rows.append(
                {
                    "variation_id": r["VariationID"],
                    "hgnc_id": r["HGNC_ID"] if r["HGNC_ID"].startswith("HGNC:") else None,
                    "symbol": r["GeneSymbol"],
                    "name": r["Name"],
                    "type": r["Type"],
                    "classification": cls,
                    "review_status": r["ReviewStatus"],
                    "stars": review_stars(r["ReviewStatus"]),
                    "consequence": consequence(r["Name"], r["Type"]),
                    "phenotype_ids": sorted({i.strip() for i in ids if i.strip() and i.strip() != "na"}),
                    "phenotypes": [p for p in r["PhenotypeList"].split("|") if p and p != "not provided"],
                    "origin": r["OriginSimple"],
                    "last_evaluated": r["LastEvaluated"],
                    "rs": r["RS# (dbSNP)"],
                    "submitters": int(r["NumberSubmitters"] or 0),
                }
            )
    return pl.DataFrame(rows).unique("variation_id")


def clinvar_disease_ids(phenotype_ids: list[str]) -> list[str]:
    """ClinVar PhenotypeIDS (MONDO:/OMIM:/Orphanet:/MedGen:) -> MONDO ids."""
    x2m = xref_to_mondo()
    out = set()
    for i in phenotype_ids:
        if i.startswith("MONDO:MONDO:"):
            out.add(i[len("MONDO:") :])
        elif i.startswith("MONDO:"):
            out.add(i)
        elif i.startswith("OMIM:") and i in x2m:
            out.add(x2m[i])
        elif i.startswith("Orphanet:") and (m := x2m.get("ORPHA:" + i.split(":", 1)[1])):
            out.add(m)
        elif i.startswith("MedGen:") and (m := x2m.get("MEDGEN:" + i.split(":", 1)[1])):
            out.add(m)
    return sorted(out)


VARIANTS_PER_GENE = 25  # seed genes
VUS_PER_GENE = 5
VARIANTS_PER_OTHER_GENE = 4
VUS_PER_OTHER_GENE = 1


def select_variants(df: pl.DataFrame, per_gene: int = VARIANTS_PER_GENE, vus: int = VUS_PER_GENE):
    """Cap variants per gene: best review status first, always keep a few VUS for the UI."""
    df = df.filter(pl.col("classification").is_in(["pathogenic", "likely_pathogenic", "uncertain_significance"]))
    df = df.with_columns(
        pl.col("classification").replace_strict({"pathogenic": 0, "likely_pathogenic": 1, "uncertain_significance": 2}).alias("_cls"),
        pl.col("phenotype_ids").list.len().alias("_nph"),
    )
    order = ["hgnc_id", "stars", "submitters", "_cls"]
    path = (
        df.filter(pl.col("_cls") < 2)
        .sort(order, descending=[False, True, True, False])
        .group_by("hgnc_id", maintain_order=True)
        .head(per_gene - vus)
    )
    unc = (
        df.filter(pl.col("_cls") == 2)
        .sort(order, descending=[False, True, True, False])
        .group_by("hgnc_id", maintain_order=True)
        .head(vus)
    )
    return pl.concat([path, unc]).drop("_cls", "_nph")


def normalize_clinvar(scope: Scope) -> None:
    df = clinvar_variants()
    sym2id = {g["symbol"]: g["hgnc_id"] for g in scope.genes}
    df = df.with_columns(
        pl.when(pl.col("hgnc_id").is_null())
        .then(pl.col("symbol").replace_strict(sym2id, default=None))
        .otherwise(pl.col("hgnc_id"))
        .alias("hgnc_id")
    ).filter(pl.col("hgnc_id").is_in(list(scope.gene_ids)))
    seeds = {g["hgnc_id"] for g in scope.genes if g.get("seed")}
    chosen = pl.concat(
        [
            select_variants(df.filter(pl.col("hgnc_id").is_in(list(seeds)))),
            select_variants(
                df.filter(~pl.col("hgnc_id").is_in(list(seeds))),
                VARIANTS_PER_OTHER_GENE,
                VUS_PER_OTHER_GENE,
            ),
        ]
    )
    retrieved = _retrieved("clinvar", "variant_summary.scope.tsv.gz")
    nodes, syns, rows = [], [], []
    for v in chosen.iter_rows(named=True):
        vid = f"CLINVAR:{v['variation_id']}"
        url = CLINVAR_URL.format(v["variation_id"])
        hgvs = v["name"]
        protein = _PROTEIN.search(hgvs)
        short = f"{v['symbol']} {protein.group(0)[1:-1] if protein else hgvs.split(':')[-1]}"
        nodes.append(
            {
                "id": vid,
                "type": "variant",
                "label": short,
                "description": hgvs,
                "url": url,
                "attrs": {
                    "hgvs": hgvs,
                    "classification": v["classification"],
                    "review_status": v["review_status"],
                    "review_stars": v["stars"],
                    "consequence": v["consequence"],
                    "variant_type": v["type"],
                    "rs": v["rs"] if v["rs"] not in ("-1", "") else None,
                    "last_evaluated": v["last_evaluated"],
                    "origin": v["origin"],
                },
            }
        )
        syns.append({"node_id": vid, "synonym": hgvs, "source": "clinvar"})
        syns.append({"node_id": vid, "synonym": short, "source": "clinvar"})
        if v["rs"] and v["rs"] not in ("-1", ""):
            syns.append({"node_id": vid, "synonym": f"rs{v['rs']}", "source": "clinvar"})
        quote = f"{hgvs}: {v['classification'].replace('_', ' ')} ({v['review_status']})"
        rows.append(
            assertion(
                vid,
                v["hgnc_id"],
                "variant_of",
                tier="curated_db",
                source_type="clinvar",
                source_ref=v["variation_id"],
                url=url,
                quote=quote,
                retrieved_at=retrieved,
            )
        )
        for mid in clinvar_disease_ids(v["phenotype_ids"]):
            if mid in scope.disease_ids:
                rows.append(
                    assertion(
                        vid,
                        mid,
                        "observed_in",
                        tier="curated_db",
                        source_type="clinvar",
                        source_ref=v["variation_id"],
                        url=url,
                        quote=quote,
                        retrieved_at=retrieved,
                        features={"classification": v["classification"]},
                    )
                )
    # Disease -> gene links supported by (likely) pathogenic ClinVar variants with a phenotype.
    path = df.filter(pl.col("classification").is_in(["pathogenic", "likely_pathogenic"]))
    pair_counts: dict[tuple[str, str], list[str]] = {}
    for v in path.select("hgnc_id", "phenotype_ids", "variation_id").iter_rows(named=True):
        for mid in clinvar_disease_ids(v["phenotype_ids"]):
            if mid in scope.disease_ids:
                pair_counts.setdefault((mid, v["hgnc_id"]), []).append(v["variation_id"])
    for (mid, hid), vids in pair_counts.items():
        if len(vids) < 2:
            continue
        rows.append(
            assertion(
                mid,
                hid,
                "caused_by_variant_in",
                tier="curated_db",
                source_type="clinvar",
                source_ref=f"{len(vids)} P/LP variants",
                url=f"https://www.ncbi.nlm.nih.gov/clinvar/?term={vids[0]}",
                quote=f"{len(vids)} pathogenic or likely pathogenic ClinVar variants annotated to this condition",
                retrieved_at=retrieved,
                features={"n_pathogenic_variants": len(vids), "example_variation_ids": vids[:5]},
            )
        )
    write_tables("clinvar", nodes, syns, rows)
