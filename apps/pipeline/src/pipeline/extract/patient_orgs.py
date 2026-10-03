"""Stage 3b: organization facts from cleaned patient-organization pages, with verified quotes.

Extracts name, diseases served, country, registry yes/no, natural-history study yes/no and contact
URL, always with the page URL. Every fact used for an edge needs a quote found verbatim in the
page text. For curated organizations it adds independent `serves` / `runs` evidence (tier
llm_inferred) and a cross-check against the curated flags; pages found through Bright Data become
new organizations only when their name and at least one served disease verify.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlparse

import polars as pl
from pydantic import BaseModel

from pipeline.contracts import Scope, assertion, write_tables
from pipeline.extract.common import ScopeMatcher, json_attrs, quote_in_text, slugify
from pipeline.llm import LLMRun
from pipeline.paths import EXTRACTED, NORMALIZED
from pipeline.sources.patient_orgs import load_curated

log = logging.getLogger(__name__)

NAME = "patient_orgs"
MAX_PAGE_CHARS = 12000

INSTRUCTIONS = """You read the cleaned text of one web page that may belong to a patient
organization for a rare disease. Extract only what the page itself states:
- organization_name and name_quote (exact span from the page containing the name)
- diseases_served: each disease or gene-defined condition the organization serves, with an exact
  quote from the page
- country where the organization is based, if stated
- runs_registry / runs_natural_history_study: true only if the page says this organization runs,
  manages or has launched a patient registry / natural history study; give the study name and an
  exact quote
- contact_url: a contact page URL if one is written in the text
Quotes must be copied character for character from the page. Use null or false when the page does
not say."""


class Served(BaseModel):
    name: str
    quote: str


class OrgPage(BaseModel):
    is_patient_organization: bool
    organization_name: str | None
    name_quote: str | None
    diseases_served: list[Served]
    country: str | None
    runs_registry: bool
    registry_name: str | None
    registry_quote: str | None
    runs_natural_history_study: bool
    natural_history_study_name: str | None
    natural_history_study_quote: str | None
    contact_url: str | None


def _contact_url(url: str | None, page_url: str) -> str | None:
    if not url or not url.startswith(("http://", "https://")):
        return None
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return url if host == urlparse(page_url).netloc.lower().removeprefix("www.") else None


async def run(scope: Scope, llm: LLMRun) -> dict[str, Any]:
    out = EXTRACTED / NAME
    out.mkdir(parents=True, exist_ok=True)
    src = NORMALIZED / NAME / "pages.parquet"
    pages = pl.read_parquet(src) if src.exists() else pl.DataFrame()
    matcher = ScopeMatcher(scope)
    curated = load_curated()
    curated_regs: dict[str, list[dict[str, Any]]] = {}
    for reg in curated.get("registries") or []:
        for c in reg.get("runs") or []:
            curated_regs.setdefault(c.get("by", ""), []).append(reg)

    nodes: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    attempted = accepted = 0
    rejected: dict[str, int] = {}

    def reject(reason: str) -> None:
        rejected[reason] = rejected.get(reason, 0) + 1

    def ev(src_id: str, dst: str, relation: str, page: dict[str, Any], quote: str):
        return assertion(
            src_id,
            dst,
            relation,
            tier="llm_inferred",
            source_type="patient_org_site",
            source_ref=page["url"],
            url=page["url"],
            quote=quote,
            retrieved_at=page["retrieved_at"],
            origin="observed",
            features={"extractor": "llm_small"},
        )

    page_rows = list(pages.iter_rows(named=True)) if pages.height else []
    for page in page_rows:
        text = (page["text"] or "")[:MAX_PAGE_CHARS]
        # Curated pages without an organization of their own (network, registry and member-list
        # pages) only back curated claims; only discovered pages may create organizations.
        if not text.strip() or (not page["org_id"] and page["origin"] != "brightdata"):
            continue
        res = await llm.structured(OrgPage, instructions=INSTRUCTIONS, input=text, kind="small")
        if res is None or not res.is_patient_organization:
            continue
        org_id = page["org_id"]
        if not org_id:
            attempted += 1
            if not (
                res.organization_name
                and quote_in_text(res.name_quote, text)
                and res.organization_name in (res.name_quote or "")
            ):
                reject("name_not_verified")
                continue
            org_id = f"ORG:{slugify(res.organization_name)}"
        served = []
        for s in res.diseases_served:
            attempted += 1
            if not quote_in_text(s.quote, text):
                reject("quote_not_found")
                continue
            ids = {m.node_id for m in matcher.diseases_in(s.name)} or (
                {matcher.resolve(s.name)} & scope.disease_ids
            )
            if not ids:
                reject("disease_not_in_scope")
                continue
            for d in ids:
                served.append(d)
                rows.append(ev(org_id, d, "serves", page, s.quote))
                accepted += 1
        if not page["org_id"]:
            if not served:
                continue
            accepted += 1
            nodes.append(
                {
                    "id": org_id,
                    "type": "patient_org",
                    "label": res.organization_name,
                    "description": None,
                    "url": page["url"],
                    "attrs": json_attrs(
                        country=res.country,
                        origin=page["origin"],
                        contact_url=_contact_url(res.contact_url, page["url"]),
                        source="llm_extraction",
                    ),
                }
            )
        for kind, flag, name, quote in (
            ("registry", res.runs_registry, res.registry_name, res.registry_quote),
            (
                "natural_history_study",
                res.runs_natural_history_study,
                res.natural_history_study_name,
                res.natural_history_study_quote,
            ),
        ):
            if not flag:
                continue
            attempted += 1
            if not quote_in_text(quote, text):
                reject("quote_not_found")
                continue
            accepted += 1
            known = [r for r in curated_regs.get(org_id, []) if r.get("kind") == kind]
            if known:
                reg_id = known[0]["id"]
            else:
                reg_id = f"REG:{slugify(name or org_id.split(':', 1)[1] + '-' + kind)}"
                nodes.append(
                    {
                        "id": reg_id,
                        "type": "registry",
                        "label": name or f"{kind} ({org_id})",
                        "description": None,
                        "url": page["url"],
                        "attrs": json_attrs(kind=kind, source="llm_extraction"),
                    }
                )
                for d in served:
                    rows.append(ev(reg_id, d, "studies", page, quote))
            rows.append(ev(org_id, reg_id, "runs", page, quote))
        if page["org_id"]:
            checks.append(
                {
                    "org_id": org_id,
                    "page": page["url"],
                    "curated_registry": any(
                        r.get("kind") == "registry" for r in curated_regs.get(org_id, [])
                    ),
                    "extracted_registry": res.runs_registry,
                    "curated_natural_history_study": any(
                        r.get("kind") == "natural_history_study"
                        for r in curated_regs.get(org_id, [])
                    ),
                    "extracted_natural_history_study": res.runs_natural_history_study,
                    "extracted_country": res.country,
                    "contact_url": _contact_url(res.contact_url, page["url"]),
                }
            )

    write_tables(NAME, nodes, [], rows, stage="extracted")
    if not page_rows:
        status = "skipped_no_pages"
    elif llm.client is None and llm.cache_hits == 0:
        status = "skipped_not_logged_in"
    else:
        status = "completed" if llm.stop_reason is None else f"stopped_{llm.stop_reason}"
    report = {
        "status": status,
        "pages": len(page_rows),
        "attempted": attempted,
        "accepted": accepted,
        "rejected": rejected,
        "pass_rate": round(accepted / attempted, 4) if attempted else None,
        "curated_cross_check": checks,
        **llm.summary(),
    }
    (out / "report.json").write_text(json.dumps(report, indent=1))
    log.info(
        "patient_orgs extraction: %s",
        {k: report[k] for k in ("status", "pages", "attempted", "accepted")},
    )
    return report
