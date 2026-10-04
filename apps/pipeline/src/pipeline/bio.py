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


def _cached(name: str, sources: list[tuple[str, str]], version: int = 1):
    """Cache a parser's DataFrame in data/cache/parsed/<name>.parquet keyed by raw SHA-256s.

    Bump ``version`` when the parser's output columns change, so stale caches are re-parsed.
    """

    def deco(fn: Callable[[], pl.DataFrame]):
        @cache
        def wrapper() -> pl.DataFrame:
            key = []
            for source, file in sources:
                rec = raw_record(source, file)
                if rec is None:
                    raise FileNotFoundError(f"raw {source}/{file} missing; run fetch first")
                key.append(rec["sha256"])
            if version > 1:
                key.append(f"v{version}")
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


# ---------------------------------------------------------------- MANE (gene coordinates)

MANE_FILE = "MANE.GRCh38.v1.5.summary.txt.gz"
ASSEMBLY = "GRCh38"
_REFSEQ_CHROMOSOMES = {23: "X", 24: "Y"}


def refseq_chromosome(accession: str) -> str | None:
    """NC_000019.10 -> "19", NC_000023.11 -> "X", NC_012920.1 -> "MT"; anything else -> None."""
    m = re.match(r"NC_0+(\d+)\.\d+$", accession or "")
    if not m:
        return None
    n = int(m.group(1))
    if n == 12920:
        return "MT"
    if 1 <= n <= 22:
        return str(n)
    return _REFSEQ_CHROMOSOMES.get(n)


def parse_mane(lines) -> pl.DataFrame:
    """MANE summary rows -> one GRCh38 span per HGNC gene, from its MANE Select transcript.

    The span is the transcript's (MANE Select), which for nearly every gene is the gene's
    extent. Genes with several Select rows keep the outermost coordinates.
    """
    rows = []
    reader = csv.DictReader((line.lstrip("#") for line in lines), delimiter="\t")
    for r in reader:
        if r.get("MANE_status") != "MANE Select" or not r.get("HGNC_ID", "").startswith("HGNC:"):
            continue
        chrom = refseq_chromosome(r["GRCh38_chr"])
        if chrom is None:
            continue
        rows.append(
            {
                "hgnc_id": r["HGNC_ID"],
                "chromosome": chrom,
                "start": int(r["chr_start"]),
                "end": int(r["chr_end"]),
                "strand": r["chr_strand"],
            }
        )
    schema = {
        "hgnc_id": pl.String,
        "chromosome": pl.String,
        "start": pl.Int64,
        "end": pl.Int64,
        "strand": pl.String,
    }
    df = pl.DataFrame(rows, schema=schema)
    return df.group_by("hgnc_id", maintain_order=True).agg(
        pl.col("chromosome").first(),
        pl.col("start").min(),
        pl.col("end").max(),
        pl.col("strand").first(),
    )


_CYTOBAND_CHROMOSOME = re.compile(r"^\s*(\d{1,2}|X|Y)(?=[pq\s]|cen|$)", re.IGNORECASE)


def cytoband_chromosome(location: str | None) -> str | None:
    """HGNC location -> chromosome: "9q34.11" -> "9", "Xp22.13" -> "X", "mitochondria" -> "MT"."""
    if not location:
        return None
    if location.strip().lower().startswith("mito"):
        return "MT"
    m = _CYTOBAND_CHROMOSOME.match(location)
    return m.group(1).upper() if m else None


@_cached("mane", [("mane", MANE_FILE)])
def mane_genes() -> pl.DataFrame:
    with gzip.open(RAW / "mane" / MANE_FILE, "rt") as f:
        return parse_mane(f)


def gene_coordinates() -> dict[str, dict]:
    """HGNC id -> {chromosome, start, end, strand} on GRCh38; {} when MANE was not fetched."""
    try:
        df = mane_genes()
    except FileNotFoundError:
        log.warning("MANE summary not fetched; genes get no coordinates")
        return {}
    return {
        r["hgnc_id"]: {k: r[k] for k in ("chromosome", "start", "end", "strand")}
        for r in df.iter_rows(named=True)
    }


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


@_cached("hpoa", [("hpo", "phenotype.hpoa")], version=2)
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
                    "onset": r.get("onset") or None,
                }
            )
    return pl.DataFrame(rows, infer_schema_length=None)


def frequency_label(raw: str | None) -> str | None:
    """Readable form of an HPO frequency: the HPO term's name, or the ratio / percentage as is."""
    if not raw or raw == "-":
        return None
    if raw in FREQ_HP:
        return hpo_label(raw)
    return raw


@cache
def _hpo_labels() -> dict[str, str]:
    return {hid: label for hid, label in hpo_terms().select("id", "label").iter_rows() if label}


def hpo_label(hpo_id: str) -> str:
    return _hpo_labels().get(hpo_id, hpo_id)


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


ORPHA_EXACT = "E (Exact mapping"
NOMENCLATURE_SCHEMA = {
    "orpha": pl.String,
    "name": pl.String,
    "disorder_type": pl.String,
    "mondo_ids": pl.List(pl.String),
    "omim_ids": pl.List(pl.String),
}


def parse_orphanet_nomenclature(source) -> pl.DataFrame:
    """Orphanet product1 (nomenclature) -> one row per disorder with its exact MONDO / OMIM ids.

    Only external references with an exact mapping ("E") that Orphanet marks as validated are
    kept; narrower / broader mappings (NTBT, BTNT, ...) would attach the wrong entity.
    """
    rows = []
    for _, el in ET.iterparse(source, events=("end",)):
        if el.tag != "Disorder" or el.find("OrphaCode") is None:
            continue
        exact: dict[str, list[str]] = {"MONDO": [], "OMIM": []}
        for ref in el.iter("ExternalReference"):
            src = ref.findtext("Source")
            if src not in exact:
                continue
            relation = ref.findtext("DisorderMappingRelation/Name") or ""
            status = ref.findtext("DisorderMappingValidationStatus/Name") or ""
            value = (ref.findtext("Reference") or "").strip()
            if relation.startswith(ORPHA_EXACT) and status == "Validated" and value:
                exact[src].append(f"{src}:{value}")
        rows.append(
            {
                "orpha": f"ORPHA:{el.findtext('OrphaCode')}",
                "name": el.findtext("Name"),
                "disorder_type": el.findtext("DisorderType/Name"),
                "mondo_ids": sorted(set(exact["MONDO"])),
                "omim_ids": sorted(set(exact["OMIM"])),
            }
        )
        el.clear()
    return pl.DataFrame(rows, schema=NOMENCLATURE_SCHEMA)


@_cached("orphanet_nomenclature", [("orphanet", "en_product1.xml")])
def orphanet_nomenclature() -> pl.DataFrame:
    return parse_orphanet_nomenclature(RAW / "orphanet" / "en_product1.xml")


def disease_xref_ids(
    exact_matches: dict[str, list[str]], nomenclature: pl.DataFrame
) -> dict[str, dict[str, list[str]]]:
    """MONDO id -> {"orpha_ids": [...], "omim_ids": [...], "orphanet_added": [...]}.

    Starts from MONDO's own exact matches, then adds what Orphanet product1 maps exactly:
    ORPHA codes whose validated exact MONDO mapping is the disease, and the OMIM ids those ORPHA
    codes map exactly. An ORPHA or OMIM id that MONDO already assigns to another disease is
    skipped. ``orphanet_added`` lists the ids that came only from product1.
    """
    owner: dict[str, str] = {}
    for mid, xs in exact_matches.items():
        for x in xs:
            owner.setdefault(x, mid)
    by_orpha = {r["orpha"]: r for r in nomenclature.iter_rows(named=True)}
    orpha_by_mondo: dict[str, set[str]] = {}
    for r in by_orpha.values():
        for m in r["mondo_ids"]:
            orpha_by_mondo.setdefault(m, set()).add(r["orpha"])
    out: dict[str, dict[str, list[str]]] = {}
    for mid, xs in exact_matches.items():
        orpha = {x for x in xs if x.startswith("ORPHA:")}
        omim = {x for x in xs if x.startswith("OMIM:")}
        base = orpha | omim
        for o in orpha_by_mondo.get(mid, ()):
            if owner.get(o, mid) == mid:
                orpha.add(o)
        for o in sorted(orpha):
            for x in by_orpha[o]["omim_ids"] if o in by_orpha else ():
                if owner.get(x, mid) == mid:
                    omim.add(x)
        out[mid] = {
            "orpha_ids": sorted(orpha, key=_id_sort),
            "omim_ids": sorted(omim, key=_id_sort),
            "orphanet_added": sorted((orpha | omim) - base, key=_id_sort),
        }
    return out


def _id_sort(curie_id: str) -> tuple[str, int]:
    prefix, _, acc = curie_id.partition(":")
    return (prefix, int(acc) if acc.isdigit() else 0)


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
    names = {
        k: v["name"]
        for k, v in _obo_terms(RAW / "go" / "go-basic.obo", "biological_process").items()
    }
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
                rows.append(
                    {
                        "hgnc_id": hid,
                        "go_id": p[4],
                        "name": names[p[4]],
                        "evidence": p[6],
                        "ref": p[5],
                    }
                )
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
                "detail": (
                    f"ClinGen gene-disease validity: {cls} ({r['moi']}, {r['gcep']}, {r['date']})"
                ),
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
    return pl.DataFrame(rows, infer_schema_length=None).unique(
        ["mondo_id", "hgnc_id", "source", "ref"]
    )


@cache
def _phenotype_annotations() -> pl.DataFrame:
    """Every MONDO-mapped annotation from HPO and Orphanet, with an ``excluded`` flag.

    Excluded = an HPO "NOT" qualifier, or a frequency of 0 (HPO "Excluded (0%)" HP:0040285,
    Orphanet "Excluded (0%)").
    """
    x2m = xref_to_mondo()
    a = (
        hpoa()
        .with_columns(pl.col("disease_id").replace_strict(x2m, default=None).alias("mondo_id"))
        .drop_nulls("mondo_id")
    )
    labels = {raw: frequency_label(raw) for raw in a["frequency_raw"].unique().to_list()}
    onsets = {o: hpo_label(o) for o in a["onset"].drop_nulls().unique().to_list()}
    a = a.select(
        "mondo_id",
        "hpo_id",
        "frequency",
        pl.col("frequency_raw").replace_strict(labels, default=None).alias("frequency_label"),
        pl.col("onset").alias("onset_id"),
        pl.col("onset").replace_strict(onsets, default=None).alias("onset"),
        pl.col("disease_id").alias("ref"),
        pl.lit("hpo").alias("source"),
        (pl.col("negated") | (pl.col("frequency") == 0).fill_null(False)).alias("excluded"),
    )
    o = orphanet_phenotypes()
    o = o.with_columns(
        pl.col("orpha").replace_strict(x2m, default=None).alias("mondo_id"),
        pl.col("frequency_raw").replace_strict(ORPHA_FREQ, default=None).alias("frequency"),
    ).drop_nulls("mondo_id")
    o = o.select(
        "mondo_id",
        "hpo_id",
        "frequency",
        pl.col("frequency_raw").alias("frequency_label"),
        pl.lit(None, dtype=pl.String).alias("onset_id"),
        pl.lit(None, dtype=pl.String).alias("onset"),
        pl.col("orpha").alias("ref"),
        pl.lit("orphanet").alias("source"),
        (pl.col("frequency") == 0).fill_null(False).alias("excluded"),
    )
    return pl.concat([a, o], how="vertical_relaxed")


@cache
def disease_phenotypes() -> pl.DataFrame:
    """MONDO disease -> HPO term with frequency, merged from HPO annotations and Orphanet.

    Columns: mondo_id, hpo_id, frequency (0-1 or null), frequency_label, onset_id, onset, ref,
    source (hpo | orphanet). Excluded annotations are in ``disease_excluded_phenotypes``.
    """
    return _phenotype_annotations().filter(~pl.col("excluded")).drop("excluded")


@cache
def disease_excluded_phenotypes() -> pl.DataFrame:
    """MONDO disease -> HPO term recorded as excluded (absent) for that disease."""
    return (
        _phenotype_annotations()
        .filter(pl.col("excluded"))
        .select("mondo_id", "hpo_id", "ref", "source")
        .unique(maintain_order=True)
    )


# ---------------------------------------------------------------- normalizers


def _retrieved(source: str, file: str) -> str | None:
    rec = raw_record(source, file)
    return rec["retrieved_at"] if rec else None


def _nomenclature_or_empty() -> pl.DataFrame:
    try:
        return orphanet_nomenclature()
    except FileNotFoundError:
        log.warning("Orphanet product1 not fetched; disease ids come from MONDO only")
        return pl.DataFrame(schema=NOMENCLATURE_SCHEMA)


def normalize_mondo(scope: Scope) -> None:
    live = mondo_terms().filter(~pl.col("deprecated"))
    ids = disease_xref_ids(
        dict(live.select("id", "exact_matches").iter_rows()), _nomenclature_or_empty()
    )
    terms = mondo_terms().filter(pl.col("id").is_in(list(scope.disease_ids)))
    nodes, syns = [], []
    for t in terms.iter_rows(named=True):
        xrefs = [
            x
            for x in t["xrefs"]
            if x.split(":")[0] in ("OMIM", "Orphanet", "MEDGEN", "GARD", "DOID", "NORD")
        ]
        own = ids.get(t["id"]) or {  # a deprecated MONDO term: its own exact matches only
            "orpha_ids": [x for x in t["exact_matches"] if x.startswith("ORPHA:")],
            "omim_ids": [x for x in t["exact_matches"] if x.startswith("OMIM:")],
            "orphanet_added": [],
        }
        nodes.append(
            {
                "id": t["id"],
                "type": "disease",
                "label": t["label"],
                "description": t["definition"],
                "url": MONDO_URL.format(t["id"]),
                "attrs": {
                    "xrefs": xrefs,
                    "exact_matches": t["exact_matches"],
                    "rare": t["rare"],
                    "orpha_ids": own["orpha_ids"],
                    "omim_ids": own["omim_ids"],
                },
            }
        )
        syns.append({"node_id": t["id"], "synonym": t["label"], "source": "mondo"})
        for s in t["exact_synonyms"] + t["other_synonyms"]:
            syns.append({"node_id": t["id"], "synonym": s, "source": "mondo"})
        # ORPHA:/OMIM: ids as synonyms, so search finds a disease by its standard ids.
        added = set(own["orphanet_added"])
        for x in own["orpha_ids"] + own["omim_ids"]:
            syns.append(
                {"node_id": t["id"], "synonym": x, "source": "orphanet" if x in added else "mondo"}
            )
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
    coords = gene_coordinates()
    nodes, syns, missing = [], [], []
    for g in genes.iter_rows(named=True):
        c = coords.get(g["hgnc_id"])
        if c is None:
            missing.append(g["symbol"])
        attrs = {
            "symbol": g["symbol"],
            "locus_group": g["locus_group"],
            "location": g["location"],
            "entrez_id": g["entrez_id"],
            "ensembl_id": g["ensembl_id"],
            "uniprot_ids": g["uniprot_ids"],
            "omim_ids": g["omim_ids"],
            # Position on GRCh38 from the MANE Select transcript; null when MANE has none.
            "chromosome": c["chromosome"] if c else cytoband_chromosome(g["location"]),
            "cytoband": g["location"] or None,
            "start": c["start"] if c else None,
            "end": c["end"] if c else None,
            "strand": c["strand"] if c else None,
            "assembly": ASSEMBLY if c else None,
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
    if missing:
        log.warning("%d genes without MANE coordinates: %s", len(missing), ", ".join(missing))
    write_tables("hgnc", nodes, syns, [])


PHENOTYPES_PER_DISEASE = 40


def phenotype_rows(scope: Scope, source: str) -> pl.DataFrame:
    """One row per (disease, term, source record) in scope: the highest frequency recorded with
    its label, and the first recorded onset (several hpoa lines can share a record)."""
    dp = disease_phenotypes().filter(
        (pl.col("source") == source)
        & pl.col("mondo_id").is_in(list(scope.disease_ids))
        & pl.col("hpo_id").is_in(list(scope.phenotype_ids))
    )
    keys = ["mondo_id", "hpo_id", "ref"]
    best = (
        dp.sort([*keys, "frequency"], descending=[False, False, False, True], nulls_last=True)
        .group_by(keys, maintain_order=True)
        .agg(pl.col("frequency").first(), pl.col("frequency_label").first())
    )
    onset = (
        dp.drop_nulls("onset_id")
        .sort([*keys, "onset_id"])
        .group_by(keys, maintain_order=True)
        .agg(pl.col("onset_id").first(), pl.col("onset").first())
    )
    return best.join(onset, on=keys, how="left").sort(keys)


def phenotype_features(r: dict, source: str) -> dict | None:
    """has_phenotype features of one source record (None values left out).

    frequency: 0-1, the value Stage 4 compares across sources (it keeps the maximum);
    frequency_label: the source's own wording ("Very frequent", "7/13", "Frequent (79-30%)");
    frequency_by_source: {"hpo": 0.9, "orphanet": 0.55}, merged per source in Stage 4;
    onset / onset_id: HPO onset term of the annotation (HPO annotations only).
    """
    f = r.get("frequency")
    out = {
        "frequency": f,
        "frequency_label": r.get("frequency_label") if f is not None else None,
        "frequency_by_source": {source: f} if f is not None else None,
        "onset": r.get("onset"),
        "onset_id": r.get("onset_id"),
    }
    out = {k: v for k, v in out.items() if v is not None}
    return out or None


def excluded_phenotype_nodes(scope: Scope) -> list[dict]:
    """Disease stubs carrying ``attrs.excluded_phenotypes`` (merged onto the MONDO node in Stage 4).

    Each item: {"id": "HP:...", "label": ..., "sources": ["hpo", "orphanet"], "refs": [...]}.
    Terms outside the phenotype scope are kept too: ranking needs every recorded absence.
    """
    ex = disease_excluded_phenotypes().filter(pl.col("mondo_id").is_in(list(scope.disease_ids)))
    grouped = (
        ex.group_by("mondo_id", "hpo_id")
        .agg(pl.col("source").unique().sort(), pl.col("ref").unique().sort())
        .sort("mondo_id", "hpo_id")
    )
    items: dict[str, list[dict]] = {}
    for r in grouped.iter_rows(named=True):
        items.setdefault(r["mondo_id"], []).append(
            {
                "id": r["hpo_id"],
                "label": hpo_label(r["hpo_id"]),
                "sources": r["source"],
                "refs": r["ref"],
            }
        )
    return [
        {"id": mid, "type": "disease", "attrs": {"excluded_phenotypes": lst}}
        for mid, lst in items.items()
    ]


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
    for r in phenotype_rows(scope, "hpo").iter_rows(named=True):
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
                features=phenotype_features(r, "hpo"),
            )
        )
    # Excluded terms (HPO "NOT" and frequency 0, from HPO and Orphanet) go onto the disease node.
    nodes += excluded_phenotype_nodes(scope)
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
    for r in phenotype_rows(scope, "orphanet").iter_rows(named=True):
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
                features=phenotype_features(r, "orphanet"),
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
    return df.join(sizes, on=id_col).filter(
        pl.col("hgnc_id").is_in(list(scope.gene_ids)) & (pl.col("n_genes") <= PATHWAY_MAX_GENES)
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
    df = (
        df.sort(["hgnc_id", "n_genes"])
        .group_by("hgnc_id", maintain_order=True)
        .head(GO_MAX_PER_GENE)
    )
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


ALLELE_MAX_LEN = 50  # longer VCF alleles (large indels) are left out of the node attrs


def _int_or_none(v: str | None) -> int | None:
    v = (v or "").strip()
    return int(v) if v.lstrip("-").isdigit() and int(v) > 0 else None


def _allele(v: str | None) -> str | None:
    v = (v or "").strip()
    if not v or v in ("na", "-") or len(v) > ALLELE_MAX_LEN:
        return None
    return v


def clinvar_position(r: dict) -> dict:
    """GRCh38 position columns of one variant_summary row; missing values become None."""
    chrom = (r.get("Chromosome") or "").strip()
    band = (r.get("Cytogenetic") or "").strip()
    start, stop = _int_or_none(r.get("Start")), _int_or_none(r.get("Stop"))
    if not chrom or chrom in ("na", "Un") or start is None:
        chrom, start, stop = None, None, None
    return {
        "chromosome": chrom,
        "start": start,
        "stop": stop if stop is not None else start,
        "cytoband": band if band and band not in ("-", "na") else None,
        "assembly": (r.get("Assembly") or None) if start is not None else None,
        "position_vcf": _int_or_none(r.get("PositionVCF")),
        "ref": _allele(r.get("ReferenceAlleleVCF")),
        "alt": _allele(r.get("AlternateAlleleVCF")),
    }


def vcv(variation_id: str) -> str:
    """ClinVar VariationID -> its VCV accession without version: 15087 -> VCV000015087."""
    return f"VCV{int(variation_id):09d}"


@_cached("clinvar", [("clinvar", "variant_summary.scope.tsv.gz")], version=2)
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
                    **clinvar_position(r),
                    "variation_id": r["VariationID"],
                    "hgnc_id": r["HGNC_ID"] if r["HGNC_ID"].startswith("HGNC:") else None,
                    "symbol": r["GeneSymbol"],
                    "name": r["Name"],
                    "type": r["Type"],
                    "classification": cls,
                    "review_status": r["ReviewStatus"],
                    "stars": review_stars(r["ReviewStatus"]),
                    "consequence": consequence(r["Name"], r["Type"]),
                    "phenotype_ids": sorted(
                        {i.strip() for i in ids if i.strip() and i.strip() != "na"}
                    ),
                    "phenotypes": [
                        p for p in r["PhenotypeList"].split("|") if p and p != "not provided"
                    ],
                    "origin": r["OriginSimple"],
                    "last_evaluated": r["LastEvaluated"],
                    "rs": r["RS# (dbSNP)"],
                    "submitters": int(r["NumberSubmitters"] or 0),
                }
            )
    return pl.DataFrame(rows, infer_schema_length=None).unique(
        "variation_id", keep="first", maintain_order=True
    )


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


VARIANT_POSITION_ATTRS = (
    "chromosome",
    "start",
    "stop",
    "cytoband",
    "assembly",
    "position_vcf",
    "ref",
    "alt",
)
# Variant types that can span several genes; smaller events stay with ClinVar's own gene.
SPANNING_TYPES = {"copy number loss", "copy number gain", "deletion", "duplication"}
SPANNING_MIN_BP = 1000


def spanned_genes(v: dict, coords: dict[str, dict]) -> list[tuple[str, int]]:
    """(HGNC id, overlap in bp) of every gene in ``coords`` that a large variant overlaps.

    Only copy-number variants and deletions / duplications of at least SPANNING_MIN_BP are
    considered, on the same chromosome and assembly (MANE coordinates are GRCh38).
    """
    if (
        (v.get("type") or "").lower() not in SPANNING_TYPES
        or v.get("start") is None
        or v.get("assembly") != ASSEMBLY
    ):
        return []
    start, stop = v["start"], v.get("stop") or v["start"]
    if stop - start + 1 < SPANNING_MIN_BP:
        return []
    out = []
    for hid, c in coords.items():
        if c.get("chromosome") != v.get("chromosome"):
            continue
        overlap = min(stop, c["end"]) - max(start, c["start"]) + 1
        if overlap > 0:
            out.append((hid, overlap))
    return sorted(out)


VARIANTS_PER_GENE = 25  # seed genes
VUS_PER_GENE = 5
VARIANTS_PER_OTHER_GENE = 4
VUS_PER_OTHER_GENE = 1


def select_variants(df: pl.DataFrame, per_gene: int = VARIANTS_PER_GENE, vus: int = VUS_PER_GENE):
    """Cap variants per gene: best review status first, always keep a few VUS for the UI."""
    df = df.filter(
        pl.col("classification").is_in(
            ["pathogenic", "likely_pathogenic", "uncertain_significance"]
        )
    )
    df = df.with_columns(
        pl.col("classification")
        .replace_strict({"pathogenic": 0, "likely_pathogenic": 1, "uncertain_significance": 2})
        .alias("_cls"),
        pl.col("phenotype_ids").list.len().alias("_nph"),
        pl.col("variation_id").str.zfill(12).alias("_vid"),
    )
    # The VariationID breaks ties, so the selection does not depend on the parse order.
    order = ["hgnc_id", "stars", "submitters", "_cls", "_vid"]
    path = (
        df.filter(pl.col("_cls") < 2)
        .sort(order, descending=[False, True, True, False, False])
        .group_by("hgnc_id", maintain_order=True)
        .head(per_gene - vus)
    )
    unc = (
        df.filter(pl.col("_cls") == 2)
        .sort(order, descending=[False, True, True, False, False])
        .group_by("hgnc_id", maintain_order=True)
        .head(vus)
    )
    return pl.concat([path, unc]).drop("_cls", "_nph", "_vid")


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
    coords = {g: c for g, c in gene_coordinates().items() if g in scope.gene_ids}
    symbols = {g["hgnc_id"]: g["symbol"] for g in scope.genes}
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
                    "vcv": vcv(v["variation_id"]),
                    **{k: v[k] for k in VARIANT_POSITION_ATTRS},
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
        # Copy-number and other large variants: every further in-scope gene they overlap.
        for hid, overlap in spanned_genes(v, coords):
            if hid == v["hgnc_id"]:
                continue
            c = coords[hid]
            rows.append(
                assertion(
                    vid,
                    hid,
                    "variant_of",
                    tier="curated_db",
                    source_type="clinvar",
                    source_ref=v["variation_id"],
                    url=url,
                    quote=(
                        f"{v['type']} chr{v['chromosome']}:{v['start']}-{v['stop']} "
                        f"({v['assembly']}) overlaps {symbols.get(hid, hid)} "
                        f"(MANE chr{c['chromosome']}:{c['start']}-{c['end']})"
                    ),
                    retrieved_at=retrieved,
                    features={"basis": "coordinate_overlap", "overlap_bp": overlap},
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
                quote=(
                    f"{len(vids)} pathogenic or likely pathogenic ClinVar variants "
                    "annotated to this condition"
                ),
                retrieved_at=retrieved,
                features={"n_pathogenic_variants": len(vids), "example_variation_ids": vids[:5]},
            )
        )
    write_tables("clinvar", nodes, syns, rows)
