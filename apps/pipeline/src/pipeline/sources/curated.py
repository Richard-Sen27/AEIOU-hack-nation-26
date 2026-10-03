"""Curated, cited facts (curated/*.yaml) plus the mechanism nodes.

fetch: pulls the PubMed summaries of every cited PMID (raw/curated/esummary.json).
normalize: fails if a cited title does not match PubMed, resolves labels to in-scope ids.
"""

import json
import logging
import re

import yaml

from pipeline import bio
from pipeline.contracts import Scope, Source, assertion, raw_record, record_raw, write_tables
from pipeline.http import get_client
from pipeline.paths import CURATED, RAW

log = logging.getLogger(__name__)

ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
PUBMED_URL = "https://pubmed.ncbi.nlm.nih.gov/{}/"

MECHANISMS = {
    "loss_of_function": (
        "Loss of function",
        "Variants reduce or abolish the gene product's activity (including haploinsufficiency).",
    ),
    "gain_of_function": (
        "Gain of function",
        "Variants increase or alter the gene product's activity.",
    ),
    "dominant_negative": (
        "Dominant negative",
        "Altered gene product interferes with the normal product from the other allele.",
    ),
}


def load_facts() -> list[dict]:
    facts = []
    for path in sorted(CURATED.glob("*.yaml")):
        data = yaml.safe_load(path.read_text()) or {}
        for f in data.get("facts", []):
            facts.append({**f, "_file": path.name})
    return facts


async def fetch(scope: Scope | None) -> None:
    pmids = sorted({str(f["pmid"]) for f in load_facts() if f.get("pmid")})
    dest = RAW / "curated" / "esummary.json"
    rec = raw_record("curated", "esummary.json")
    if dest.exists() and rec and rec.get("pmids") == pmids:
        return
    async with get_client("curated") as client:
        r = await client.get(
            ESUMMARY, params={"db": "pubmed", "id": ",".join(pmids), "retmode": "json"}
        )
        r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(r.json(), indent=1))
    record_raw("curated", ESUMMARY, dest, None, pmids=pmids)


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def _endpoint(ep: dict, scope: Scope, diseases: dict[str, str]) -> str | None:
    if "gene" in ep:
        hid = bio.resolve_gene(ep["gene"])
        return hid if hid in scope.gene_ids else None
    if "mechanism" in ep:
        return f"MECH:{ep['mechanism']}"
    if "disease" in ep:
        return _disease(ep["disease"], scope, diseases)
    return None


def _disease(name: str, scope: Scope, diseases: dict[str, str]) -> str | None:
    if name.upper().startswith("MONDO:"):
        return name.upper() if name.upper() in scope.disease_ids else None
    return diseases.get(name.lower())


def normalize(scope: Scope) -> None:
    summaries = json.loads((RAW / "curated" / "esummary.json").read_text())["result"]
    retrieved = raw_record("curated", "esummary.json")["retrieved_at"]
    diseases: dict[str, str] = {}
    for d in scope.diseases:
        for name in [d["label"], *d.get("synonyms", [])]:
            diseases.setdefault(name.lower(), d["mondo_id"])
    nodes = [
        {
            "id": f"MECH:{key}",
            "type": "mechanism",
            "label": label,
            "description": desc,
            "url": None,
            "attrs": {},
        }
        for key, (label, desc) in MECHANISMS.items()
    ]
    syns = [
        {"node_id": n["id"], "synonym": s, "source": "curated"}
        for n in nodes
        for s in (n["label"], n["id"].split(":")[1].replace("_", " "))
    ]
    rows, mismatched, skipped = [], [], []
    for f in load_facts():
        pmid = str(f["pmid"])
        record = summaries.get(pmid) or {}
        if _norm(record.get("title", "")) != _norm(f["title"]):
            mismatched.append((pmid, f["title"], record.get("title")))
            continue
        src = _endpoint(f["source"], scope, diseases)
        tgt = _endpoint(f["target"], scope, diseases)
        disease = _disease(f["disease"], scope, diseases) if f.get("disease") else None
        if not src or not tgt or (f.get("disease") and not disease):
            skipped.append((f["source"], f["relation"], f["target"], f.get("disease")))
            continue
        features = (
            {"disease": disease, "curated_file": f["_file"]}
            if disease
            else {"curated_file": f["_file"]}
        )
        rows.append(
            assertion(
                src,
                tgt,
                f["relation"],
                tier=f["tier"],
                source_type="pubmed",
                source_ref=f"PMID:{pmid}",
                url=PUBMED_URL.format(pmid),
                quote=record["title"],
                retrieved_at=retrieved,
                claim_type=f.get("claim_type"),
                features=features,
            )
        )
    if mismatched:
        raise SystemExit(f"curated citations do not match PubMed: {mismatched}")
    for s in skipped:
        log.warning("curated fact not in scope, skipped: %s", s)
    write_tables("curated", nodes, syns, rows)


SOURCE = Source("curated", "bulk", fetch, normalize)
