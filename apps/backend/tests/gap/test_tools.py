import asyncio

import httpx
import pytest
from gapdata import ABSTRACT, CTGOV, EFETCH, ESEARCH, PAGE_HTML, PAGE_QUOTE

from backend.api.services import gap_search
from backend.api.services.gap_search import fetch
from backend.api.services.gap_search import tools as gap_tools
from backend.api.services.gap_search.fetch import BlockedURL, check_url, is_public_ip, safe_get
from backend.api.services.gap_search.tools import ToolContext
from backend.config import Settings

PUBLIC_IP = "93.184.215.14"


def _ctx(**settings) -> ToolContext:
    return ToolContext(settings=Settings(_env_file=None, **settings), max_steps=8)


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    async def _wait(host, interval):
        return None

    monkeypatch.setattr(fetch.throttle, "wait", _wait)


# ---- public APIs ---------------------------------------------------------------------------------


async def test_pubmed_search(net):
    esearch = net.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi").respond(
        json=ESEARCH
    )
    net.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi").respond(content=EFETCH)
    ctx = _ctx()
    out = await gap_tools.pubmed_search(ctx, "Dravet syndrome STXBP1")
    assert out["results"][0]["pmid"] == "40000001"
    url = "https://pubmed.ncbi.nlm.nih.gov/40000001/"
    assert out["results"][0]["url"] == url
    assert ABSTRACT in ctx.sources[url].text
    assert ctx.sources[url].source_ref == "PMID:40000001"
    request = esearch.calls.last.request
    assert request.url.params["term"] == "Dravet syndrome STXBP1"
    assert request.url.params["tool"] == "amber_rare_disease_atlas"
    assert "AmberRareDiseaseAtlas" in request.headers["user-agent"]
    assert "api_key" not in request.url.params
    assert ctx.steps == 1


async def test_pubmed_uses_ncbi_key_when_configured(net):
    route = net.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi").respond(
        json={"esearchresult": {"idlist": []}}
    )
    out = await gap_tools.pubmed_search(_ctx(ncbi_api_key="k123"), "SCN1A")
    assert out == {"results": []}
    assert route.calls.last.request.url.params["api_key"] == "k123"


async def test_pubmed_failure_is_an_error_result(net):
    net.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi").respond(500)
    out = await gap_tools.pubmed_search(_ctx(), "SCN1A")
    assert out == {"error": "pubmed unavailable"}


async def test_clinicaltrials_search(net):
    route = net.get("https://clinicaltrials.gov/api/v2/studies").respond(json=CTGOV)
    ctx = _ctx()
    out = await gap_tools.clinicaltrials_search(ctx, "Dravet syndrome")
    assert [r["nct_id"] for r in out["results"]] == ["NCT09999999"]
    src = ctx.sources["https://clinicaltrials.gov/study/NCT09999999"]
    assert "natural history study" in src.text and src.source_type == "clinicaltrials"
    assert route.calls.last.request.url.params["query.term"] == "Dravet syndrome"


async def test_step_budget_enforced_in_tools(net):
    net.get("https://clinicaltrials.gov/api/v2/studies").respond(json={"studies": []})
    ctx = ToolContext(settings=Settings(_env_file=None), max_steps=2)
    for _ in range(2):
        assert "results" in await gap_tools.clinicaltrials_search(ctx, "x")
    assert "budget" in (await gap_tools.clinicaltrials_search(ctx, "x"))["error"]
    assert ctx.steps == 2 and ctx.exhausted == "steps"


async def test_web_search_only_with_bright_data_key(net):
    assert [f.__name__ for f in gap_search._bind(_ctx())] == [
        "pubmed_search",
        "clinicaltrials_search",
        "fetch_page",
    ]
    ctx = _ctx(brightdata_api_key="bd-key", brightdata_serp_zone="serp")
    assert "web_search" in [f.__name__ for f in gap_search._bind(ctx)]
    route = net.post("https://api.brightdata.com/request").respond(
        json={"organic": [{"title": "T", "link": "https://example.org/a", "description": "d"}]}
    )
    out = await gap_tools.web_search(ctx, "Dravet syndrome STXBP1")
    assert out["results"][0]["url"] == "https://example.org/a"
    req = route.calls.last.request
    assert req.headers["authorization"] == "Bearer bd-key"
    assert b"Dravet+syndrome+STXBP1" in req.content


# ---- fetch_page and SSRF guard -----------------------------------------------------------------


async def test_fetch_page_reads_text(net):
    route = net.get(f"https://{PUBLIC_IP}/review").respond(
        200, html=PAGE_HTML, headers={"set-cookie": "sid=1"}
    )
    ctx = _ctx()
    out = await gap_tools.fetch_page(ctx, "https://example.org/review")
    assert PAGE_QUOTE.replace("\n", " ") in " ".join(out["text"].split())
    assert "secret" not in out["text"] and "menu" not in out["text"]
    assert "https://example.org/review" in ctx.sources
    req = route.calls.last.request
    assert req.headers["host"] == "example.org"
    assert "cookie" not in req.headers and "authorization" not in req.headers
    assert req.extensions.get("sni_hostname") == "example.org"


@pytest.mark.parametrize(
    "url,code",
    [
        ("ftp://example.org/x", "scheme_not_allowed"),
        ("file:///etc/passwd", "scheme_not_allowed"),
        ("http://localhost/", "host_not_allowed"),
        ("http://127.0.0.1/", "address_not_allowed"),
        ("http://10.1.2.3/", "address_not_allowed"),
        ("http://192.168.0.1/", "address_not_allowed"),
        ("http://169.254.169.254/latest/meta-data/", "address_not_allowed"),
        ("http://[::1]/", "address_not_allowed"),
        ("http://[::ffff:127.0.0.1]/", "address_not_allowed"),
        ("http://[fe80::1]/", "address_not_allowed"),
        ("http://100.64.0.1/", "address_not_allowed"),
        ("http://0.0.0.0/", "address_not_allowed"),
        ("http://user:pw@example.org/", "credentials_not_allowed"),
        ("http://example.org:8080/", "port_not_allowed"),
        ("http://metadata.internal/", "host_not_allowed"),
        ("http://intranet/", "host_not_allowed"),
    ],
)
def test_check_url_blocks(url, code):
    with pytest.raises(BlockedURL) as exc:
        check_url(url)
    assert exc.value.code == code


def test_public_ip():
    assert is_public_ip("93.184.215.14")
    assert not is_public_ip("172.16.0.1")
    assert not is_public_ip("::1")
    assert not is_public_ip("not-an-ip")


async def test_dns_to_private_address_blocked(net, resolver):
    resolver["evil.example.org"] = ["10.0.0.5"]
    resolver["mixed.example.org"] = [PUBLIC_IP, "127.0.0.1"]
    for host in ("evil.example.org", "mixed.example.org"):
        with pytest.raises(BlockedURL) as exc:
            await safe_get(f"http://{host}/")
        assert exc.value.code == "address_not_allowed"
    assert not net.calls


@pytest.mark.parametrize(
    "location", ["http://127.0.0.1/admin", "http://169.254.169.254/", "http://evil.example.org/"]
)
async def test_redirect_to_private_address_blocked(net, resolver, location):
    resolver["evil.example.org"] = ["192.168.1.10"]
    net.get(f"https://{PUBLIC_IP}/r").respond(302, headers={"location": location})
    out = await gap_tools.fetch_page(_ctx(), "https://example.org/r")
    assert out["error"] == "url not fetched: address_not_allowed"


async def test_redirect_chain_limited(net):
    net.get(f"https://{PUBLIC_IP}/loop").respond(302, headers={"location": "/loop"})
    out = await gap_tools.fetch_page(_ctx(), "https://example.org/loop")
    assert out["error"] == "url not fetched: too_many_redirects"


async def test_size_cap(net):
    net.get(f"https://{PUBLIC_IP}/big").respond(200, text="a" * 5000)
    result = await safe_get("https://example.org/big", max_bytes=1000)
    assert len(result.body) == 1000 and result.truncated


async def test_time_cap(net):
    async def _slow(request):
        await asyncio.sleep(5)
        return httpx.Response(200, text="late")

    net.get(f"https://{PUBLIC_IP}/slow").mock(side_effect=_slow)
    with pytest.raises(BlockedURL) as exc:
        await safe_get("https://example.org/slow", timeout_s=0.3)
    assert exc.value.code == "timeout"


async def test_non_text_content_refused(net):
    net.get(f"https://{PUBLIC_IP}/file.pdf").respond(
        200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"}
    )
    out = await gap_tools.fetch_page(_ctx(), "https://example.org/file.pdf")
    assert out["error"] == "url not fetched: not_text"
