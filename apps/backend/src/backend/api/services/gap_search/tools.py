"""Gap-search tools: PubMed (E-utilities), ClinicalTrials.gov (API v2), fetch_page and the
optional Bright Data web search. Every text a tool returns is kept in the run's SourceStore so
candidate quotes can be verified against what was actually fetched.
"""

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote_plus

import httpx

from backend.api.services.gap_search.fetch import (
    BlockedURL,
    api_client,
    decode_text,
    safe_get,
    throttle,
)
from backend.config import Settings

log = logging.getLogger(__name__)

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
CTGOV = "https://clinicaltrials.gov/api/v2/studies"
BRIGHTDATA = "https://api.brightdata.com/request"
MAX_RESULTS = 5
MAX_QUERY_CHARS = 300
MODEL_TEXT_CHARS = 1500
PAGE_MODEL_CHARS = 6000
STORE_TEXT_CHARS = 300_000
TOOL_NAMES = ("pubmed_search", "clinicaltrials_search", "fetch_page", "web_search")


@dataclass
class Source:
    url: str
    text: str
    source_type: str  # pubmed | clinicaltrials | web
    source_ref: str | None = None


class BudgetExhausted(Exception):
    pass


@dataclass
class ToolContext:
    settings: Settings
    max_steps: int
    on_step: Callable[[int, str], None] = lambda step, tool: None
    sources: dict[str, Source] = field(default_factory=dict)
    steps: int = 0
    output_chars: int = 0
    token_estimate: int = 0
    max_tokens: int | None = None
    exhausted: str | None = None  # "steps" | "tokens" once a budget stopped a tool call

    def begin(self, tool: str) -> None:
        if self.steps >= self.max_steps:
            self.exhausted = "steps"
            raise BudgetExhausted
        if self.max_tokens is not None and self.token_estimate > self.max_tokens:
            self.exhausted = "tokens"
            raise BudgetExhausted
        self.steps += 1
        self.on_step(self.steps, tool)

    def account(self, output: dict[str, Any]) -> dict[str, Any]:
        """Rough token estimate for runs whose usage is only known at the end: every round
        re-sends the conversation, so each output is counted again on every later round."""
        size = len(str(output))
        self.output_chars += size
        self.token_estimate += (self.output_chars + 2000) // 4
        return output

    def keep(self, source: Source) -> None:
        source.text = source.text[:STORE_TEXT_CHARS]
        self.sources[source.url] = source

    @property
    def web_search_enabled(self) -> bool:
        return bool(self.settings.brightdata_api_key and self.settings.brightdata_serp_zone)


def _query(q: str) -> str:
    q = " ".join(str(q).split())[:MAX_QUERY_CHARS]
    if not q:
        raise ValueError("empty query")
    return q


def _budget_error() -> dict[str, Any]:
    return {"error": "step budget exhausted; give your final answer now"}


async def _get_json(client: httpx.AsyncClient, url: str, params: dict, interval: float) -> Any:
    await throttle.wait(httpx.URL(url).host, interval)
    for attempt in range(2):
        resp = await client.get(url, params=params)
        if resp.status_code == 429 and attempt == 0:
            await asyncio.sleep(1.0)
            continue
        resp.raise_for_status()
        return resp
    resp.raise_for_status()
    return resp


# ---- PubMed -------------------------------------------------------------------------------------


def _ncbi_params(ctx: ToolContext) -> tuple[dict[str, str], float]:
    params = {"tool": "amber_rare_disease_atlas"}
    if ctx.settings.ncbi_api_key:
        params["api_key"] = ctx.settings.ncbi_api_key
        return params, 0.11
    return params, 0.35


def parse_pubmed_xml(xml: bytes) -> list[dict[str, str]]:
    out = []
    root = ET.fromstring(xml)
    for article in root.iter("PubmedArticle"):
        pmid = article.findtext(".//MedlineCitation/PMID") or ""
        title = (
            "".join(article.find(".//ArticleTitle").itertext())
            if article.find(".//ArticleTitle") is not None
            else ""
        )
        parts = []
        for node in article.iterfind(".//Abstract/AbstractText"):
            label = node.get("Label")
            text = "".join(node.itertext()).strip()
            parts.append(f"{label}: {text}" if label else text)
        if pmid:
            out.append({"pmid": pmid, "title": title.strip(), "abstract": "\n".join(parts)})
    return out


async def pubmed_search(ctx: ToolContext, query: str) -> dict[str, Any]:
    try:
        ctx.begin("pubmed_search")
    except BudgetExhausted:
        return _budget_error()
    try:
        term = _query(query)
    except ValueError:
        return {"error": "empty query"}
    base, interval = _ncbi_params(ctx)
    try:
        async with api_client() as client:
            resp = await _get_json(
                client,
                f"{EUTILS}/esearch.fcgi",
                {**base, "db": "pubmed", "term": term, "retmax": MAX_RESULTS, "retmode": "json"},
                interval,
            )
            ids = resp.json().get("esearchresult", {}).get("idlist", [])[:MAX_RESULTS]
            if not ids:
                return ctx.account({"results": []})
            resp = await _get_json(
                client,
                f"{EUTILS}/efetch.fcgi",
                {
                    **base,
                    "db": "pubmed",
                    "id": ",".join(ids),
                    "rettype": "abstract",
                    "retmode": "xml",
                },
                interval,
            )
            articles = parse_pubmed_xml(resp.content)
    except (httpx.HTTPError, ValueError, ET.ParseError) as exc:
        log.warning("pubmed_search failed: %s", type(exc).__name__)
        return {"error": "pubmed unavailable"}
    results = []
    for a in articles:
        url = f"https://pubmed.ncbi.nlm.nih.gov/{a['pmid']}/"
        ctx.keep(Source(url, f"{a['title']}\n{a['abstract']}", "pubmed", f"PMID:{a['pmid']}"))
        results.append(
            {
                "pmid": a["pmid"],
                "url": url,
                "title": a["title"],
                "abstract": a["abstract"][:MODEL_TEXT_CHARS],
            }
        )
    return ctx.account({"results": results})


# ---- ClinicalTrials.gov -------------------------------------------------------------------------


async def clinicaltrials_search(ctx: ToolContext, query: str) -> dict[str, Any]:
    try:
        ctx.begin("clinicaltrials_search")
    except BudgetExhausted:
        return _budget_error()
    try:
        term = _query(query)
    except ValueError:
        return {"error": "empty query"}
    try:
        async with api_client() as client:
            resp = await _get_json(
                client, CTGOV, {"query.term": term, "pageSize": MAX_RESULTS, "format": "json"}, 0.25
            )
            studies = resp.json().get("studies", [])[:MAX_RESULTS]
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("clinicaltrials_search failed: %s", type(exc).__name__)
        return {"error": "clinicaltrials.gov unavailable"}
    results = []
    for s in studies:
        p = s.get("protocolSection", {})
        ident = p.get("identificationModule", {})
        nct = ident.get("nctId")
        if not nct or not re.fullmatch(r"NCT\d{8}", nct):
            continue
        title = ident.get("officialTitle") or ident.get("briefTitle") or ""
        desc = p.get("descriptionModule", {})
        summary = desc.get("briefSummary") or ""
        conditions = p.get("conditionsModule", {}).get("conditions", [])
        url = f"https://clinicaltrials.gov/study/{nct}"
        text = "\n".join(
            [title, summary, desc.get("detailedDescription") or "", "; ".join(conditions)]
        )
        ctx.keep(Source(url, text, "clinicaltrials", nct))
        results.append(
            {
                "nct_id": nct,
                "url": url,
                "title": title,
                "summary": summary[:MODEL_TEXT_CHARS],
                "conditions": conditions[:10],
            }
        )
    return ctx.account({"results": results})


# ---- fetch_page ---------------------------------------------------------------------------------


async def fetch_page(ctx: ToolContext, url: str) -> dict[str, Any]:
    try:
        ctx.begin("fetch_page")
    except BudgetExhausted:
        return _budget_error()
    try:
        result = await safe_get(str(url))
    except BlockedURL as exc:
        return {"error": f"url not fetched: {exc.code}"}
    except httpx.HTTPError as exc:
        log.warning("fetch_page failed: %s", type(exc).__name__)
        return {"error": "url not fetched: network_error"}
    if result.status >= 400:
        return {"error": f"url not fetched: http_{result.status}"}
    text = decode_text(result)
    if text is None:
        return {"error": "url not fetched: not_text"}
    known = ctx.sources.get(str(url))
    source_type = known.source_type if known else "web"
    ref = known.source_ref if known else None
    ctx.keep(Source(str(url), text, source_type, ref))
    if result.url != str(url):
        ctx.keep(Source(result.url, text, source_type, ref))
    return ctx.account(
        {
            "url": str(url),
            "text": text[:PAGE_MODEL_CHARS],
            "truncated": len(text) > PAGE_MODEL_CHARS or result.truncated,
        }
    )


# ---- web_search (Bright Data, optional) ---------------------------------------------------------


async def web_search(ctx: ToolContext, query: str) -> dict[str, Any]:
    if not ctx.web_search_enabled:
        return {"error": "web search is not configured"}
    try:
        ctx.begin("web_search")
    except BudgetExhausted:
        return _budget_error()
    try:
        term = _query(query)
    except ValueError:
        return {"error": "empty query"}
    body = {
        "zone": ctx.settings.brightdata_serp_zone,
        "format": "raw",
        "url": f"https://www.google.com/search?q={quote_plus(term)}&brd_json=1",
    }
    try:
        async with api_client(timeout_s=25.0) as client:
            await throttle.wait("api.brightdata.com", 0.5)
            resp = await client.post(
                BRIGHTDATA,
                json=body,
                headers={"Authorization": f"Bearer {ctx.settings.brightdata_api_key}"},
            )
            resp.raise_for_status()
            organic = resp.json().get("organic", [])
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("web_search failed: %s", type(exc).__name__)
        return {"error": "web search unavailable"}
    results = [
        {
            "title": str(item.get("title") or "")[:300],
            "url": str(item.get("link") or ""),
            "snippet": str(item.get("description") or "")[:500],
        }
        for item in organic[:MAX_RESULTS]
        if str(item.get("link") or "").startswith(("http://", "https://"))
    ]
    return ctx.account(
        {"results": results, "note": "Use fetch_page on a result to read and quote it."}
    )
