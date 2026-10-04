"""PubMed (E-utilities): per in-scope gene and disease, the most relevant abstracts with authors,
affiliations, journal, year and publication types.

Authors and affiliations come from PubMed metadata only. Researchers are keyed by ORCID when the
record carries one, otherwise by a hash of "<first given name> <last name>"; a name without ORCID
is attached to an ORCID seen for the same name elsewhere in the corpus only when that name maps to
exactly one ORCID and the given name is not a bare initial.
"""

from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import polars as pl
from pydantic_settings import BaseSettings, SettingsConfigDict

from pipeline.config import settings
from pipeline.contracts import Scope, Source, assertion, raw_record, record_raw, write_tables
from pipeline.extract.common import (
    affiliation_country,
    disease_query_terms,
    fetch_fingerprint,
    fetch_is_current,
    institution_id,
    institution_name,
    json_attrs,
    normalize_orcid,
    person_name_key,
    request,
    researcher_id,
    reusable_searches,
    scrub_contacts,
    settings_key,
    split_searches,
    write_fingerprint,
)
from pipeline.http import get_client
from pipeline.paths import ENV_FILE, NORMALIZED, RAW

log = logging.getLogger(__name__)

NAME = "pubmed"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
EFETCH_BATCH = 200
# Sequential calls spaced to stay under 3 requests/second without an API key.
PACE = 0.0 if settings.ncbi_api_key else 0.34


class PubMedSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PUBMED_", env_file=ENV_FILE, extra="ignore")

    max_per_seed_gene: int = 40
    max_per_gene: int = 5
    max_per_seed_disease: int = 20
    max_per_disease: int = 5
    review_share: float = 0.25
    # Keeps gene searches on the cluster's phenotype (e.g. SLC2A1 also has a large cancer
    # literature). Empty string disables it.
    gene_context: str = (
        "(epilep*[tiab] OR seizure*[tiab] OR encephalopath*[tiab] OR neurodevelopment*[tiab])"
    )


cfg = PubMedSettings()

SKIP_TYPES = {"Retracted Publication", "Retraction of Publication", "Published Erratum"}
REVIEW_TYPES = {"Review", "Systematic Review", "Meta-Analysis", "Scoping Review"}


def tier_for(pub_types: list[str]) -> str:
    if "Preprint" in pub_types:
        return "preprint"
    if REVIEW_TYPES & set(pub_types):
        return "review"
    return "peer_reviewed"


def _identity_params() -> dict[str, str]:
    params: dict[str, str] = {}
    if settings.ncbi_api_key:
        params["api_key"] = settings.ncbi_api_key
    email = settings.contact_email
    if email and not email.endswith("@example.org"):
        params |= {"tool": "amber_rare_disease_atlas", "email": email}
    return params


@dataclass
class SearchSpec:
    target_id: str
    kind: str  # gene | disease
    terms: list[str]
    query: str
    cap: int
    pmids: list[str] = field(default_factory=list)


def build_searches(scope: Scope) -> list[SearchSpec]:
    specs: list[SearchSpec] = []
    for g in scope.genes:
        sym = g["symbol"]
        q = f'"{sym}"[tiab] AND hasabstract'
        if cfg.gene_context:
            q += f" AND {cfg.gene_context}"
        cap = cfg.max_per_seed_gene if g.get("seed") else cfg.max_per_gene
        specs.append(SearchSpec(g["hgnc_id"], "gene", [sym], q, cap))
    for d in scope.diseases:
        terms = disease_query_terms(scope, d)
        if not terms:
            continue
        q = "(" + " OR ".join(f'"{t}"[tiab]' for t in terms) + ") AND hasabstract"
        cap = cfg.max_per_seed_disease if d.get("seed") else cfg.max_per_disease
        specs.append(SearchSpec(d["mondo_id"], "disease", terms, q, cap))
    return specs


async def _esearch(client, term: str, retmax: int) -> list[str]:
    if retmax <= 0:
        return []
    params = {
        "db": "pubmed",
        "term": term,
        "retmax": str(retmax),
        "sort": "relevance",
        "retmode": "json",
        **_identity_params(),
    }
    r = await request(client, "GET", f"{EUTILS}/esearch.fcgi", params=params, pace=PACE)
    return r.json()["esearchresult"].get("idlist", [])


SEARCH_KEY = ("target_id", "kind", "query", "cap")


def fetched_pmids(raw: Path) -> set[str]:
    """PMIDs already present in the efetch files of earlier fetches."""
    found: set[str] = set()
    for f in raw.glob("efetch_*.xml"):
        found |= {a["pmid"] for a in parse_articles(f.read_bytes())}
    return found


async def fetch(scope: Scope | None) -> None:
    if scope is None:
        log.warning("pubmed: no scope; nothing to fetch")
        return
    scope = scope.focus()
    out = RAW / NAME
    out.mkdir(parents=True, exist_ok=True)
    skey = settings_key(cfg.model_dump())
    fingerprint = fetch_fingerprint(scope, cfg.model_dump())
    previous = reusable_searches(out, NAME, skey)
    if fetch_is_current(out, NAME, fingerprint, ["searches.json"]):
        log.info("%s: raw data is current for this scope and settings; skipping fetch", NAME)
        return
    specs = build_searches(scope)
    reused, todo = split_searches([s.__dict__ for s in specs], previous, SEARCH_KEY)
    log.info("pubmed: %d searches reused, %d to run", len(reused), len(todo))
    have = fetched_pmids(out) if reused else set()
    if not reused:
        for p in out.glob("efetch_*.xml"):
            p.unlink()
    async with get_client(NAME) as client:
        for spec in todo:
            n_reviews = max(1, round(spec["cap"] * cfg.review_share))
            reviews = await _esearch(client, f"{spec['query']} AND review[pt]", n_reviews)
            ranked = await _esearch(client, spec["query"], spec["cap"])
            spec["pmids"] = list(dict.fromkeys(reviews + ranked))[: spec["cap"]]
        by_target = {(s["target_id"], s["kind"]): s for s in reused + todo}
        searches = [by_target[(s.target_id, s.kind)] for s in specs]
        (out / "searches.json").write_text(json.dumps(searches, indent=1))
        record_raw(NAME, f"{EUTILS}/esearch.fcgi", out / "searches.json", "esearch")

        pmids = sorted({p for s in searches for p in s["pmids"]} - have, key=int)
        log.info("pubmed: %d searches, %d PMIDs to fetch", len(searches), len(pmids))
        start = 1 + max((int(p.stem.split("_")[1]) for p in out.glob("efetch_*.xml")), default=-1)
        for i in range(0, len(pmids), EFETCH_BATCH):
            batch = pmids[i : i + EFETCH_BATCH]
            data = {"db": "pubmed", "id": ",".join(batch), "retmode": "xml", **_identity_params()}
            r = await request(client, "POST", f"{EUTILS}/efetch.fcgi", data=data, pace=PACE)
            path = out / f"efetch_{start + i // EFETCH_BATCH:04d}.xml"
            path.write_bytes(r.content)
            record_raw(NAME, f"{EUTILS}/efetch.fcgi", path, "efetch", pmids=len(batch))
    write_fingerprint(out, fingerprint, skey)


# ---------------------------------------------------------------------------------------------
# Parsing


def _text(el: ET.Element | None) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""


def _year(article: ET.Element) -> int | None:
    for path in (
        ".//Article/Journal/JournalIssue/PubDate/Year",
        ".//Article/ArticleDate/Year",
        ".//PubmedData/History/PubMedPubDate[@PubStatus='pubmed']/Year",
    ):
        el = article.find(path)
        if el is not None and el.text and el.text.strip().isdigit():
            return int(el.text.strip())
    md = article.find(".//Article/Journal/JournalIssue/PubDate/MedlineDate")
    m = re.search(r"(19|20)\d{2}", md.text or "") if md is not None else None
    return int(m.group(0)) if m else None


def parse_articles(xml_bytes: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_bytes)
    out = []
    for art in root.iter("PubmedArticle"):
        pmid = (art.findtext("MedlineCitation/PMID") or "").strip()
        if not pmid:
            continue
        a = art.find("MedlineCitation/Article")
        if a is None:
            continue
        abstract_parts = []
        for at in a.findall("Abstract/AbstractText"):
            label = at.get("Label")
            txt = _text(at)
            if txt:
                abstract_parts.append(f"{label}: {txt}" if label else txt)
        authors = []
        for au in a.findall("AuthorList/Author"):
            if au.get("ValidYN", "Y") != "Y" or au.find("CollectiveName") is not None:
                continue
            last = (au.findtext("LastName") or "").strip()
            if not last:
                continue
            orcid = None
            for ident in au.findall("Identifier"):
                if ident.get("Source") == "ORCID":
                    orcid = normalize_orcid(ident.text)
            affs = [
                scrub_contacts(_text(x)).strip(" .;")
                for x in au.findall("AffiliationInfo/Affiliation")
            ]
            authors.append(
                {
                    "last": last,
                    "fore": (au.findtext("ForeName") or au.findtext("Initials") or "").strip(),
                    "orcid": orcid,
                    "affiliations": [x for x in affs if x],
                }
            )
        doi = None
        for aid in art.findall("PubmedData/ArticleIdList/ArticleId"):
            if aid.get("IdType") == "doi":
                doi = (aid.text or "").strip() or None
        out.append(
            {
                "pmid": pmid,
                "title": _text(a.find("ArticleTitle")),
                "abstract": "\n".join(abstract_parts),
                "journal": _text(a.find("Journal/Title"))
                or _text(a.find("Journal/ISOAbbreviation")),
                "year": _year(art),
                "pub_types": [_text(p) for p in a.findall("PublicationTypeList/PublicationType")],
                "doi": doi,
                "authors": authors,
            }
        )
    return out


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(])", text) if s.strip()]


def supporting_sentence(paper: dict[str, Any], terms: list[str], kind: str) -> str | None:
    """The title, or else the first abstract sentence, that mentions one of the search terms."""
    flags = 0 if kind == "gene" else re.I
    pats = [re.compile(rf"(?<![A-Za-z0-9]){re.escape(t)}(?![A-Za-z0-9])", flags) for t in terms]
    for sent in [paper["title"], *_sentences(paper["abstract"].replace("\n", " "))]:
        if any(p.search(sent) for p in pats):
            return sent
    return None


def normalize(scope: Scope) -> None:
    scope = scope.focus()
    raw = RAW / NAME
    searches_file = raw / "searches.json"
    if not searches_file.exists():
        log.warning("pubmed: no raw data; writing empty tables")
        write_tables(NAME)
        return
    searches = json.loads(searches_file.read_text())
    papers: dict[str, dict[str, Any]] = {}
    retrieved: dict[str, str] = {}
    for f in sorted(raw.glob("efetch_*.xml")):
        rec = raw_record(NAME, f.name) or {}
        for p in parse_articles(f.read_bytes()):
            papers[p["pmid"]] = p
            retrieved[p["pmid"]] = rec.get("retrieved_at")
    in_scope = scope.gene_ids | scope.disease_ids
    found_by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in searches:
        if s["target_id"] in in_scope:
            for pmid in s["pmids"]:
                found_by[pmid].append(s)

    # Name -> ORCIDs seen anywhere in the corpus (for conservative ORCID back-filling).
    orcids_by_key: dict[str, set[str]] = defaultdict(set)
    for p in papers.values():
        for au in p["authors"]:
            key, weak = person_name_key(au["last"], au["fore"])
            if au["orcid"] and not weak:
                orcids_by_key[key].add(au["orcid"])

    nodes: dict[str, dict[str, Any]] = {}
    researchers: dict[str, dict[str, Any]] = {}
    institutions: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    abstracts: list[dict[str, Any]] = []
    skipped = 0
    for pmid, p in papers.items():
        if SKIP_TYPES & set(p["pub_types"]) or pmid not in found_by:
            skipped += 1
            continue
        tier = tier_for(p["pub_types"])
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        ts = retrieved.get(pmid)
        pid = f"PMID:{pmid}"
        abouts = []
        for s in found_by[pmid]:
            quote = supporting_sentence(p, s["terms"], s["kind"])
            if not quote:
                continue
            abouts.append(s["target_id"])
            rows.append(
                assertion(
                    pid,
                    s["target_id"],
                    "about",
                    tier=tier,
                    source_type=NAME,
                    source_ref=pmid,
                    url=url,
                    quote=quote,
                    retrieved_at=ts,
                    features={"query": s["query"]},
                )
            )
        if not abouts:
            skipped += 1
            continue
        nodes[pid] = {
            "id": pid,
            "type": "paper",
            "label": p["title"] or pid,
            "description": None,
            "url": url,
            "attrs": json_attrs(
                pmid=pmid,
                journal=p["journal"],
                year=p["year"],
                publication_types=p["pub_types"],
                tier=tier,
                doi=p["doi"],
                n_authors=len(p["authors"]),
            ),
        }
        abstracts.append(
            {
                "pmid": pmid,
                "title": p["title"],
                "abstract": p["abstract"],
                "tier": tier,
                "publication_types": json.dumps(p["pub_types"]),
                "year": p["year"],
                "url": url,
                "retrieved_at": ts,
                "about_ids": json.dumps(sorted(set(abouts))),
            }
        )
        for au in p["authors"]:
            key, weak = person_name_key(au["last"], au["fore"])
            orcid = au["orcid"]
            if not orcid and not weak and len(orcids_by_key.get(key, ())) == 1:
                orcid = next(iter(orcids_by_key[key]))
            rid = researcher_id(key, orcid)
            r = researchers.setdefault(
                rid,
                {
                    "name": f"{au['fore']} {au['last']}".strip(),
                    "name_key": key,
                    "weak": weak,
                    "orcid": orcid,
                    "papers": 0,
                    "institutions": set(),
                },
            )
            r["papers"] += 1
            rows.append(
                assertion(
                    rid,
                    pid,
                    "authored",
                    tier="curated_db",
                    source_type=NAME,
                    source_ref=pmid,
                    url=url,
                    retrieved_at=ts,
                )
            )
            for aff in au["affiliations"]:
                inst = institution_name(aff)
                if not inst:
                    continue
                iid = institution_id(inst)
                institutions.setdefault(iid, {"name": inst, "country": affiliation_country(aff)})
                r["institutions"].add(inst)
                rows.append(
                    assertion(
                        rid,
                        iid,
                        "affiliated_with",
                        tier="curated_db",
                        source_type=NAME,
                        source_ref=pmid,
                        url=url,
                        retrieved_at=ts,
                        quote=aff,
                    )
                )
    for rid, r in researchers.items():
        nodes[rid] = {
            "id": rid,
            "type": "researcher",
            "label": r["name"],
            "description": None,
            "url": f"https://orcid.org/{r['orcid']}" if r["orcid"] else None,
            "attrs": json_attrs(
                orcid=r["orcid"],
                name_key=r["name_key"],
                weak_name_key=r["weak"] or None,
                n_papers=r["papers"],
                institutions=sorted(r["institutions"])[:10],
                source="pubmed",
            ),
        }
    for iid, inst in institutions.items():
        nodes[iid] = {
            "id": iid,
            "type": "institution",
            "label": inst["name"],
            "description": None,
            "url": None,
            "attrs": json_attrs(country=inst["country"], source="pubmed"),
        }
    synonyms = [
        {"node_id": rid, "synonym": r["name"], "source": NAME} for rid, r in researchers.items()
    ]
    write_tables(NAME, list(nodes.values()), synonyms, _dedupe(rows))
    pl.DataFrame(abstracts, schema=ABSTRACT_SCHEMA, orient="row").write_parquet(
        NORMALIZED / NAME / "abstracts.parquet"
    )
    log.info(
        "pubmed: %d papers, %d researchers, %d institutions, %d skipped",
        len(abstracts),
        len(researchers),
        len(institutions),
        skipped,
    )


ABSTRACT_SCHEMA = {
    "pmid": pl.String,
    "title": pl.String,
    "abstract": pl.String,
    "tier": pl.String,
    "publication_types": pl.String,
    "year": pl.Int64,
    "url": pl.String,
    "retrieved_at": pl.String,
    "about_ids": pl.String,
}


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for r in rows:
        k = (r["source_id"], r["relation"], r["target_id"], r["source_ref"], r["quote"])
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


SOURCE = Source(NAME, "scoped", fetch, normalize)
