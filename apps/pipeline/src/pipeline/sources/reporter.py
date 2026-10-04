"""NIH RePORTER (API v2): grants by in-scope gene and disease terms, grouped by core project.

A grant is kept only when its title or abstract confidently names an in-scope disease, which is
also the evidence for its `funds_research_on` edge. PIs are keyed like PubMed authors (an ORCID
already seen for the same name in the PubMed tables is reused, otherwise a name hash), so shared
researchers across papers and grants line up.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from typing import Any

import polars as pl
from pydantic_settings import BaseSettings, SettingsConfigDict

from pipeline.contracts import Scope, Source, assertion, raw_record, record_raw, write_tables
from pipeline.extract.common import (
    ScopeMatcher,
    disease_query_terms,
    fetch_fingerprint,
    fetch_is_current,
    institution_id,
    json_attrs,
    person_name_key,
    request,
    researcher_id,
    reusable_searches,
    settings_key,
    split_searches,
    write_fingerprint,
)
from pipeline.http import get_client
from pipeline.paths import ENV_FILE, NORMALIZED, RAW

log = logging.getLogger(__name__)

NAME = "reporter"
API = "https://api.reporter.nih.gov/v2/projects/search"


class ReporterSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REPORTER_", env_file=ENV_FILE, extra="ignore")

    max_per_seed_term: int = 100
    max_per_term: int = 10


cfg = ReporterSettings()

_DROP_KEYS = {"program_officers", "geo_lat_lon", "cong_dist", "org_duns", "org_ueis"}


def _searches(scope: Scope) -> list[dict[str, Any]]:
    out = []
    for g in scope.genes:
        cap = cfg.max_per_seed_term if g.get("seed") else cfg.max_per_term
        out.append({"target_id": g["hgnc_id"], "text": f'"{g["symbol"]}"', "cap": cap})
    for d in scope.diseases:
        terms = disease_query_terms(scope, d)
        if terms:
            cap = cfg.max_per_seed_term if d.get("seed") else cfg.max_per_term
            out.append(
                {
                    "target_id": d["mondo_id"],
                    "text": " OR ".join(f'"{t}"' for t in terms),
                    "cap": cap,
                }
            )
    return out


SEARCH_KEY = ("target_id", "text", "cap")


async def fetch(scope: Scope | None) -> None:
    if scope is None:
        log.warning("reporter: no scope; nothing to fetch")
        return
    scope = scope.focus()
    out = RAW / NAME
    out.mkdir(parents=True, exist_ok=True)
    skey = settings_key(cfg.model_dump())
    fingerprint = fetch_fingerprint(scope, cfg.model_dump())
    previous = reusable_searches(out, NAME, skey)
    if fetch_is_current(out, NAME, fingerprint, ["projects.json", "searches.json"]):
        log.info("%s: raw data is current for this scope and settings; skipping fetch", NAME)
        return
    reused, todo = split_searches(_searches(scope), previous, SEARCH_KEY)
    log.info("reporter: %d searches reused, %d to run", len(reused), len(todo))
    projects: dict[str, dict[str, Any]] = (
        json.loads((out / "projects.json").read_text()) if reused else {}
    )
    async with get_client(NAME) as client:
        for s in todo:
            ids: list[str] = []
            offset = 0
            while len(ids) < s["cap"]:
                body = {
                    "criteria": {
                        "advanced_text_search": {
                            "operator": "advanced",
                            "search_field": "projecttitle,abstracttext",
                            "search_text": s["text"],
                        }
                    },
                    "offset": offset,
                    "limit": min(100, s["cap"]),
                    "sort_field": "fiscal_year",
                    "sort_order": "desc",
                }
                r = await request(client, "POST", API, json=body, pace=1.0)
                data = r.json()
                results = data.get("results", [])
                for p in results:
                    key = str(p.get("appl_id"))
                    projects[key] = {k: v for k, v in p.items() if k not in _DROP_KEYS}
                    ids.append(key)
                offset += len(results)
                if not results or offset >= data.get("meta", {}).get("total", 0):
                    break
            s["appl_ids"] = ids[: s["cap"]]
    order = {s["target_id"]: i for i, s in enumerate(_searches(scope))}
    searches = sorted(reused + todo, key=lambda s: order[s["target_id"]])
    # Keep exactly the projects the current searches found (as a fresh fetch would).
    wanted = {a for s in searches for a in s.get("appl_ids", [])}
    projects = {k: v for k, v in projects.items() if k in wanted}
    (out / "projects.json").write_text(json.dumps(projects, ensure_ascii=False))
    (out / "searches.json").write_text(json.dumps(searches, indent=1))
    record_raw(NAME, API, out / "projects.json", "v2", projects=len(projects))
    record_raw(NAME, API, out / "searches.json", "v2")
    write_fingerprint(out, fingerprint, skey)
    log.info("reporter: %d searches, %d project-years", len(searches), len(projects))


def _orcid_by_name_key() -> dict[str, str]:
    """name_key -> ORCID node id from the PubMed tables, when that name has exactly one."""
    f = NORMALIZED / "pubmed" / "nodes.parquet"
    if not f.exists():
        return {}
    df = pl.read_parquet(f).filter(pl.col("id").str.starts_with("ORCID:"))
    keys: dict[str, set[str]] = defaultdict(set)
    for row in df.iter_rows(named=True):
        attrs = json.loads(row["attrs"] or "{}")
        if attrs.get("name_key") and not attrs.get("weak_name_key"):
            keys[attrs["name_key"]].add(row["id"])
    return {k: next(iter(v)) for k, v in keys.items() if len(v) == 1}


def _title_case(name: str | None) -> str:
    return " ".join(w.capitalize() if w.isupper() else w for w in (name or "").split())


def normalize(scope: Scope) -> None:
    scope = scope.focus()
    raw = RAW / NAME
    if not (raw / "projects.json").exists():
        log.warning("reporter: no raw data; writing empty tables")
        write_tables(NAME)
        return
    projects = json.loads((raw / "projects.json").read_text())
    ts = (raw_record(NAME, "projects.json") or {}).get("retrieved_at")
    matcher = ScopeMatcher(scope)
    orcids = _orcid_by_name_key()

    by_core: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in projects.values():
        core = p.get("core_project_num") or p.get("project_num")
        if core:
            by_core[core].append(p)

    nodes: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    synonyms: list[dict[str, Any]] = []
    dropped = 0
    for core, years in by_core.items():
        years.sort(key=lambda p: (p.get("fiscal_year") or 0, p.get("appl_id") or 0), reverse=True)
        latest = years[0]
        title = latest.get("project_title") or core
        abstract = latest.get("abstract_text") or ""
        matches = {m.node_id: m for m in matcher.diseases_in(title)}
        for m in matcher.diseases_in(abstract):
            matches.setdefault(m.node_id, m)
        if not matches:
            dropped += 1
            continue
        gid = f"GRANT:{core}"
        url = (
            latest.get("project_detail_url")
            or f"https://reporter.nih.gov/project-details/{latest.get('appl_id')}"
        )
        org = latest.get("organization") or {}
        fiscal_years = sorted({p.get("fiscal_year") for p in years if p.get("fiscal_year")})
        total = sum(p.get("award_amount") or 0 for p in years)
        ic = latest.get("agency_ic_admin") or {}
        nodes[gid] = {
            "id": gid,
            "type": "grant",
            "label": _title_case(title) if title.isupper() else title,
            "description": abstract[:600] + ("…" if len(abstract) > 600 else ""),
            "url": url,
            "attrs": json_attrs(
                core_project_num=core,
                project_nums=sorted({p.get("project_num") for p in years if p.get("project_num")}),
                fiscal_years=fiscal_years,
                award_amount_total=total or None,
                award_amount_latest=latest.get("award_amount"),
                activity_code=latest.get("activity_code"),
                agency=ic.get("abbreviation"),
                organization=_title_case(org.get("org_name")),
                org_country=_title_case(org.get("org_country")),
                project_start=(latest.get("project_start_date") or "")[:10] or None,
                project_end=(latest.get("project_end_date") or "")[:10] or None,
                is_active=latest.get("is_active"),
            ),
        }
        for disease_id, m in matches.items():
            rows.append(
                assertion(
                    gid,
                    disease_id,
                    "funds_research_on",
                    tier="curated_db",
                    source_type=NAME,
                    source_ref=core,
                    url=url,
                    quote=_sentence_with(matcher, [title, abstract], disease_id),
                    retrieved_at=ts,
                    features={"match": m.method, "term": m.term},
                )
            )
        iid = None
        if org.get("org_name"):
            org_name = _title_case(org["org_name"])
            iid = institution_id(org_name)
            nodes.setdefault(
                iid,
                {
                    "id": iid,
                    "type": "institution",
                    "label": org_name,
                    "description": None,
                    "url": None,
                    "attrs": json_attrs(
                        country=_title_case(org.get("org_country")),
                        city=_title_case(org.get("org_city")),
                        source=NAME,
                    ),
                },
            )
        for pi in latest.get("principal_investigators") or []:
            first = (pi.get("first_name") or "").strip()
            last = (pi.get("last_name") or "").strip()
            if not last:
                continue
            key, weak = person_name_key(last, first)
            rid = orcids.get(key) if not weak else None
            rid = rid or researcher_id(key)
            display = _title_case(f"{first} {last}")
            nodes.setdefault(
                rid,
                {
                    "id": rid,
                    "type": "researcher",
                    "label": display,
                    "description": None,
                    "url": None,
                    "attrs": json_attrs(name_key=key, weak_name_key=weak or None, source=NAME),
                },
            )
            synonyms.append({"node_id": rid, "synonym": display, "source": NAME})
            rows.append(
                assertion(
                    rid,
                    gid,
                    "pi_of",
                    tier="curated_db",
                    source_type=NAME,
                    source_ref=core,
                    url=url,
                    retrieved_at=ts,
                    features={"contact_pi": bool(pi.get("is_contact_pi"))},
                )
            )
            if iid:
                rows.append(
                    assertion(
                        rid,
                        iid,
                        "affiliated_with",
                        tier="curated_db",
                        source_type=NAME,
                        source_ref=core,
                        url=url,
                        retrieved_at=ts,
                        quote=org.get("org_name"),
                    )
                )
    write_tables(NAME, list(nodes.values()), synonyms, rows)
    log.info(
        "reporter: %d grants kept, %d without an in-scope disease",
        sum(1 for n in nodes.values() if n["type"] == "grant"),
        dropped,
    )


def _sentence_with(matcher: ScopeMatcher, texts: list[str], disease_id: str) -> str | None:
    """The first sentence (title included) in which the disease match holds on its own."""
    for text in texts:
        for sent in re.split(r"(?<=[.!?])\s+", text or ""):
            if any(m.node_id == disease_id for m in matcher.diseases_in(sent)):
                return re.sub(r"\s+", " ", sent).strip()[:500]
    return None


SOURCE = Source(NAME, "scoped", fetch, normalize)
