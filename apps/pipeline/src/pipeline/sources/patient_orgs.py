"""Patient organizations, their registries and umbrella networks.

The curated list (`curated/patient_orgs.yaml`) names each organization with the pages that state
what it serves, runs or belongs to. `fetch` downloads those pages and cleans them with trafilatura;
`normalize` keeps a claim only when its quote occurs in the cleaned page text. With
`BRIGHTDATA_API_KEY` (and `BRIGHTDATA_SERP_ZONE`) set, Bright Data SERP queries discover further
organization pages, which Stage 3 reads; without it discovery is skipped silently.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import quote_plus, urlparse

import polars as pl
import trafilatura
import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

from pipeline.config import settings
from pipeline.contracts import Scope, Source, assertion, now_iso, record_raw, write_tables
from pipeline.extract.common import (
    institution_id,
    json_attrs,
    quote_in_text,
    request,
    scrub_contacts,
    short_hash,
)
from pipeline.http import get_client
from pipeline.paths import CURATED, NORMALIZED, RAW

log = logging.getLogger(__name__)

NAME = "patient_orgs"
CURATED_FILE = CURATED / "patient_orgs.yaml"
SOURCE_TYPE = "patient_org_site"


class BrightDataSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BRIGHTDATA_", extra="ignore")

    serp_zone: str | None = None
    max_results_per_query: int = 5


bd = BrightDataSettings()

# Hosts that are never a patient organization's own page.
_NOT_ORG_HOSTS = (
    "wikipedia.org",
    "ncbi.nlm.nih.gov",
    "pubmed",
    "clinicaltrials.gov",
    "facebook.com",
    "youtube.com",
    "linkedin.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "medlineplus.gov",
    "orpha.net",
    "omim.org",
    "rarediseases.info.nih.gov",
    "sciencedirect.com",
    "springer.com",
    "wiley.com",
    "nature.com",
    "mayoclinic.org",
    "webmd.com",
    "healthline.com",
    "google.",
)


def load_curated() -> dict[str, Any]:
    return yaml.safe_load(CURATED_FILE.read_text()) or {}


def curated_urls(data: dict[str, Any]) -> list[str]:
    urls: list[str] = []

    def add(u: str | None) -> None:
        if u and u not in urls:
            urls.append(u)

    for section in ("networks", "organizations", "registries", "institutions"):
        for entry in data.get(section) or []:
            add((entry.get("identity") or {}).get("url"))
            for key in ("serves", "member_of", "runs", "studies"):
                for claim in entry.get(key) or []:
                    add(claim.get("url"))
    return urls


def page_file(url: str) -> str:
    return f"pages/{short_hash(url)}.txt"


def clean_html(html: str) -> str:
    text = trafilatura.extract(html, favor_recall=True, include_comments=False) or ""
    return scrub_contacts(text)


async def _fetch_page(client, url: str, origin: str) -> dict[str, Any]:
    entry: dict[str, Any] = {"url": url, "origin": origin, "retrieved_at": now_iso()}
    try:
        r = await request(client, "GET", url, attempts=2)
    except Exception as exc:  # unreachable pages are recorded, never fatal
        entry["error"] = type(exc).__name__ + (
            f" {exc.response.status_code}" if hasattr(exc, "response") else ""
        )
        return entry
    text = clean_html(r.text)
    path = RAW / NAME / page_file(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    record_raw(NAME, url, path, None, final_url=str(r.url), origin=origin)
    entry |= {"file": page_file(url), "final_url": str(r.url), "chars": len(text)}
    return entry


async def _discover(client, scope: Scope) -> list[str]:
    """Bright Data SERP: candidate organization homepages for each seed disease (public terms)."""
    if not settings.brightdata_api_key or not bd.serp_zone:
        return []
    found: list[str] = []
    headers = {"Authorization": f"Bearer {settings.brightdata_api_key}"}
    for d in scope.diseases:
        if not d.get("seed"):
            continue
        q = f'"{d["label"]}" patient organization foundation'
        body = {
            "zone": bd.serp_zone,
            "format": "raw",
            "url": f"https://www.google.com/search?q={quote_plus(q)}&brd_json=1",
        }
        try:
            r = await request(
                client,
                "POST",
                "https://api.brightdata.com/request",
                json=body,
                headers=headers,
                attempts=2,
            )
            organic = r.json().get("organic", [])
        except Exception as exc:
            log.warning("patient_orgs: Bright Data query failed (%s)", type(exc).__name__)
            continue
        for item in organic[: bd.max_results_per_query]:
            link = item.get("link") or ""
            host = urlparse(link).netloc.lower()
            if link and not any(h in host for h in _NOT_ORG_HOSTS) and link not in found:
                found.append(link)
    return found


async def fetch(scope: Scope | None) -> None:
    data = load_curated()
    pages: list[dict[str, Any]] = []
    async with get_client(NAME, headers={"Accept": "text/html,application/xhtml+xml"}) as client:
        for url in curated_urls(data):
            pages.append(await _fetch_page(client, url, "curated"))
        if scope is not None:
            known = {p["url"] for p in pages}
            for url in await _discover(client, scope):
                if url not in known:
                    pages.append(await _fetch_page(client, url, "brightdata"))
    index = RAW / NAME / "pages.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps(pages, indent=1))
    ok = sum(1 for p in pages if "file" in p)
    log.info("patient_orgs: fetched %d/%d pages", ok, len(pages))
    for p in pages:
        if "error" in p:
            log.warning("patient_orgs: could not fetch %s (%s)", p["url"], p["error"])


def load_pages() -> list[dict[str, Any]]:
    index = RAW / NAME / "pages.json"
    if not index.exists():
        return []
    pages = json.loads(index.read_text())
    for p in pages:
        f = RAW / NAME / p["file"] if p.get("file") else None
        p["text"] = f.read_text() if f and f.exists() else None
    return pages


def normalize(scope: Scope) -> None:
    data = load_curated()
    pages = {p["url"]: p for p in load_pages()}
    in_scope = scope.disease_ids
    nodes: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    synonyms: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    def verified(claim: dict[str, Any] | None, what: str) -> bool:
        if not claim:
            return False
        page = pages.get(claim.get("url"))
        ok = bool(page and page.get("text") and quote_in_text(claim.get("quote"), page["text"]))
        if not ok:
            reason = "page_unavailable" if not (page and page.get("text")) else "quote_not_found"
            rejected.append({"claim": what, "url": claim.get("url"), "reason": reason})
        return ok

    def edge(src: str, dst: str, relation: str, claim: dict[str, Any]) -> dict[str, Any]:
        page = pages[claim["url"]]
        return assertion(
            src,
            dst,
            relation,
            tier="curated_db",
            source_type=SOURCE_TYPE,
            source_ref=claim["url"],
            url=claim["url"],
            quote=claim["quote"],
            retrieved_at=page.get("retrieved_at"),
        )

    def add_node(entry: dict[str, Any], node_type: str, **attrs) -> None:
        nodes[entry["id"]] = {
            "id": entry["id"],
            "type": node_type,
            "label": entry["name"],
            "description": None,
            "url": entry.get("url"),
            "attrs": json_attrs(source="curated", **attrs),
        }
        synonyms.append({"node_id": entry["id"], "synonym": entry["name"], "source": NAME})

    networks = {}
    for net in data.get("networks") or []:
        if verified(net.get("identity"), f"{net['id']} identity"):
            networks[net["id"]] = net

    orgs = {}
    for org in data.get("organizations") or []:
        if not verified(org.get("identity"), f"{org['id']} identity"):
            continue
        serves = [
            c
            for c in org.get("serves") or []
            if c.get("disease") in in_scope and verified(c, f"{org['id']} serves {c['disease']}")
        ]
        if not serves:
            continue
        orgs[org["id"]] = org
        add_node(
            org,
            "patient_org",
            country=org.get("country"),
            genes=org.get("genes"),
            identity_url=org["identity"]["url"],
        )
        rows.extend(edge(org["id"], c["disease"], "serves", c) for c in serves)
        for c in org.get("member_of") or []:
            if c.get("network") in networks and verified(c, f"{org['id']} member_of"):
                rows.append(edge(org["id"], c["network"], "member_of", c))

    runners: set[str] = set()
    for reg in data.get("registries") or []:
        runs = []
        for c in reg.get("runs") or []:
            by = c.get("by", "")
            if by.startswith("ORG:") and by not in orgs:
                continue
            if by.startswith("NET:") and by not in networks:
                continue
            if verified(c, f"{reg['id']} runs"):
                runs.append(c)
        studies = [
            c
            for c in reg.get("studies") or []
            if c.get("disease") in in_scope and verified(c, f"{reg['id']} studies")
        ]
        if not runs:
            continue
        add_node(reg, "registry", kind=reg.get("kind"))
        for c in runs:
            by = c["by"]
            if not by.startswith(("ORG:", "NET:")):
                iid = institution_id(by)
                nodes.setdefault(
                    iid,
                    {
                        "id": iid,
                        "type": "institution",
                        "label": by,
                        "description": None,
                        "url": None,
                        "attrs": json_attrs(source="curated"),
                    },
                )
                by = iid
            runners.add(by)
            rows.append(edge(by, reg["id"], "runs", c))
        rows.extend(edge(reg["id"], c["disease"], "studies", c) for c in studies)

    members: set[str] = set()
    for inst in data.get("institutions") or []:
        iid = institution_id(inst["name"])
        for c in inst.get("member_of") or []:
            if c.get("network") in networks and verified(c, f"{inst['name']} member_of"):
                nodes.setdefault(
                    iid,
                    {
                        "id": iid,
                        "type": "institution",
                        "label": inst["name"],
                        "description": None,
                        "url": None,
                        "attrs": json_attrs(source="curated"),
                    },
                )
                rows.append(edge(iid, c["network"], "member_of", c))
                members.add(c["network"])

    # A network is emitted only if something verified points at it (no orphan nodes).
    members |= {r["target_id"] for r in rows if r["relation"] == "member_of"}
    for net_id, net in networks.items():
        if net_id in members or net_id in runners:
            add_node(net, "network", country=net.get("country"), kind=net.get("kind"))

    write_tables(NAME, list(nodes.values()), synonyms, rows)
    out = NORMALIZED / NAME
    page_rows = [
        {
            "url": p["url"],
            "origin": p.get("origin"),
            "retrieved_at": p.get("retrieved_at"),
            "text": p["text"],
            "org_id": next(
                (o["id"] for o in orgs.values() if _same_site(o.get("url"), p["url"])), None
            ),
        }
        for p in pages.values()
        if p.get("text")
    ]
    pl.DataFrame(page_rows, schema=PAGE_SCHEMA, orient="row").write_parquet(out / "pages.parquet")
    (out / "verification.json").write_text(
        json.dumps({"accepted_assertions": len(rows), "rejected_claims": rejected}, indent=1)
    )
    log.info(
        "patient_orgs: %d organizations, %d registries, %d networks, %d claims rejected",
        len(orgs),
        sum(1 for n in nodes.values() if n["type"] == "registry"),
        sum(1 for n in nodes.values() if n["type"] == "network"),
        len(rejected),
    )


PAGE_SCHEMA = {
    "url": pl.String,
    "origin": pl.String,
    "retrieved_at": pl.String,
    "text": pl.String,
    "org_id": pl.String,
}


def _same_site(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    ha = urlparse(a).netloc.lower().removeprefix("www.")
    hb = urlparse(b).netloc.lower().removeprefix("www.")
    return ha == hb


SOURCE = Source(NAME, "scoped", fetch, normalize)
