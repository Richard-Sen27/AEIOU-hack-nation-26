"""Budget, cache and quote verification of Stage 3, with a fake LLMClient and the mock server."""

import json

import polars as pl
import pytest
from pydantic import BaseModel

from pipeline import llm
from pipeline.extract import abstracts, patient_orgs
from pipeline.llm import LLMRun

ABSTRACT = (
    "Dravet syndrome is caused by de novo variants in SCN1A in most patients. "
    "Most SCN1A variants lead to loss of function of Nav1.1 in inhibitory interneurons. "
    "Children with Dravet syndrome develop seizures in the first year of life."
)


class Echo(BaseModel):
    value: str


class FakeLLMError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class FakeClient:
    def __init__(self, responses=None, error=None):
        self.calls = []
        self.responses = responses or {}
        self.error = error

    async def structured(self, schema, *, instructions, input, kind="small"):
        self.calls.append(input)
        if self.error:
            raise FakeLLMError(self.error)
        if schema is Echo:
            return Echo(value=input)
        return schema.model_validate(self.responses[schema])


async def test_budget_stops_calls(data_dirs):
    client = FakeClient()
    run = LLMRun.start(client=client, max_calls=2)
    out = [await run.structured(Echo, instructions="i", input=s) for s in ("a", "b", "c")]
    assert [o.value if o else None for o in out] == ["a", "b", None]
    assert len(client.calls) == 2 and run.stop_reason == "budget" and run.skipped == 1


async def test_cache_makes_reruns_free(data_dirs):
    first = LLMRun.start(client=FakeClient(), max_calls=10)
    await first.structured(Echo, instructions="i", input="a")
    second_client = FakeClient()
    second = LLMRun.start(client=second_client, max_calls=10)
    assert (await second.structured(Echo, instructions="i", input="a")).value == "a"
    assert second_client.calls == [] and second.cache_hits == 1
    # A different prompt or kind is a different cache entry.
    await second.structured(Echo, instructions="other", input="a")
    await second.structured(Echo, instructions="i", input="a", kind="main")
    assert len(second_client.calls) == 2


async def test_not_logged_in_serves_cache_only(data_dirs, monkeypatch):
    await LLMRun.start(client=FakeClient(), max_calls=10).structured(
        Echo, instructions="i", input="a"
    )
    monkeypatch.setattr(llm, "get_llm", lambda: None)
    run = LLMRun.start()
    assert run.mode == "cache_only"
    assert (await run.structured(Echo, instructions="i", input="a")).value == "a"
    assert await run.structured(Echo, instructions="i", input="b") is None
    assert run.summary()["skipped_uncached"] == 1


async def test_usage_limit_stops_run(data_dirs):
    client = FakeClient(error="usage_limit_exceeded")
    run = LLMRun.start(client=client, max_calls=10)
    assert await run.structured(Echo, instructions="i", input="a") is None
    assert await run.structured(Echo, instructions="i", input="b") is None
    assert run.stop_reason == "usage_limit_exceeded" and len(client.calls) == 1


async def test_other_errors_do_not_stop(data_dirs):
    run = LLMRun.start(client=FakeClient(error="bad_output"), max_calls=10)
    await run.structured(Echo, instructions="i", input="a")
    await run.structured(Echo, instructions="i", input="b")
    assert run.stop_reason is None and run.errors["bad_output"] == 2


def _write_abstracts(data_dirs, text=ABSTRACT):
    out = data_dirs["normalized"] / "pubmed"
    out.mkdir(parents=True)
    pl.DataFrame(
        [
            {
                "pmid": "123",
                "title": "t",
                "abstract": text,
                "tier": "peer_reviewed",
                "publication_types": "[]",
                "year": 2024,
                "url": "https://pubmed.ncbi.nlm.nih.gov/123/",
                "retrieved_at": "2026-10-03T00:00:00+00:00",
                "about_ids": '["MONDO:0100135"]',
            }
        ],
        schema=__import__("pipeline.sources.pubmed", fromlist=["x"]).ABSTRACT_SCHEMA,
        orient="row",
    ).write_parquet(out / "abstracts.parquet")


RELATIONS = {
    "relations": [
        {
            "subject": "Dravet syndrome (disease)",
            "relation": "caused_by_variant_in",
            "object": "SCN1A",
            "quote": "Dravet syndrome is caused by de novo variants in SCN1A",
            "claim_type": "patient_observation",
            "polarity": "supports",
            "confidence": 0.9,
        },
        {
            "subject": "SCN1A",
            "relation": "acts_via",
            "object": "loss of function",
            "quote": "Most SCN1A variants lead to loss of function",
            "claim_type": "experimental",
            "polarity": "supports",
            "inferred": True,
            "confidence": 0.7,
        },
        {
            "subject": "Dravet syndrome",
            "relation": "has_phenotype",
            "object": "seizures",
            "quote": "Children with Dravet syndrome have seizures",  # paraphrase
            "claim_type": "patient_observation",
            "polarity": "supports",
            "confidence": 0.8,
        },
        {
            "subject": "Dravet syndrome",
            "relation": "caused_by_variant_in",
            "object": "KCNQ2",
            "quote": "Dravet syndrome is caused",
            "claim_type": "review",  # not in scope/text
            "polarity": "supports",
            "confidence": 0.5,
        },
        {
            "subject": "SCN1A",
            "relation": "has_phenotype",
            "object": "seizures",
            "quote": "develop seizures",
            "claim_type": "review",  # wrong endpoint types
            "polarity": "supports",
            "confidence": 0.5,
        },
    ]
}


async def test_abstract_extraction_verifies_quotes(data_dirs, scope):
    _write_abstracts(data_dirs)
    client = FakeClient({abstracts.AbstractExtraction: RELATIONS})
    report = await abstracts.run(scope, LLMRun.start(client=client, max_calls=5))
    # the relation marked inferred is dropped before verification and never written
    assert report["dropped_inferred"] == 1
    assert report["attempted"] == 4 and report["accepted"] == 1
    assert report["rejected"] == {"quote_not_found": 1, "unresolved_entity": 1, "wrong_types": 1}
    assert report["pass_rate"] == 0.25
    sent = json.loads(client.calls[0])
    assert set(sent) == {"entities", "abstract"} and sent["abstract"] == ABSTRACT
    assert "SCN1A (gene)" in sent["entities"] and "dravet syndrome (disease)" in sent["entities"]

    out = data_dirs["extracted"] / "abstracts"
    a = pl.read_parquet(out / "assertions.parquet")
    nodes = pl.read_parquet(out / "nodes.parquet")
    bio = a.filter(pl.col("relation").is_in(["caused_by_variant_in", "acts_via"]))
    rows = {r["relation"]: r for r in bio.iter_rows(named=True)}
    cause = rows["caused_by_variant_in"]
    assert (cause["source_id"], cause["target_id"]) == ("MONDO:0100135", "HGNC:10585")
    assert cause["tier"] == "peer_reviewed" and cause["origin"] == "observed"
    assert cause["source_type"] == "pubmed" and cause["source_ref"] == "123"
    assert "acts_via" not in rows  # inferred: no assertion
    assert (a["origin"] == "inferred").sum() == 0
    assert nodes["type"].to_list() == ["claim"]  # and no claim node
    asserts = a.filter(pl.col("relation") == "asserts")
    assert set(asserts["source_id"]) == {"PMID:123"} and set(asserts["target_id"]) == set(
        nodes["id"]
    )
    about = a.filter(pl.col("relation") == "about")
    assert set(about["target_id"]) == {"MONDO:0100135", "HGNC:10585"}  # never to a mechanism
    assert a.height == 4  # asserts + 2 about + the one relation
    saved = json.loads((out / "report.json").read_text())
    assert saved["accepted"] == 1 and saved["status"] == "completed"
    assert saved["dropped_inferred"] == 1


async def test_abstract_extraction_skipped_without_login(data_dirs, scope, monkeypatch):
    _write_abstracts(data_dirs)
    monkeypatch.setattr(llm, "get_llm", lambda: None)
    report = await abstracts.run(scope, LLMRun.start())
    assert report["status"] == "skipped_not_logged_in" and report["attempted"] == 0
    out = data_dirs["extracted"] / "abstracts"
    assert pl.read_parquet(out / "assertions.parquet").height == 0
    assert json.loads((out / "report.json").read_text())["mode"] == "cache_only"


async def test_org_extraction_without_pages(data_dirs, scope, monkeypatch):
    monkeypatch.setattr(llm, "get_llm", lambda: None)
    report = await patient_orgs.run(scope, LLMRun.start())
    assert report["status"] == "skipped_no_pages"
    assert pl.read_parquet(data_dirs["extracted"] / "patient_orgs" / "nodes.parquet").height == 0


async def test_org_extraction_cross_checks_curated(data_dirs, scope):
    from .conftest import FIXTURES

    text = (FIXTURES / "kcnt1_registry_page.txt").read_text()
    url = "https://www.kcnt1epilepsy.org/kcnt1-international-registry/"
    out = data_dirs["normalized"] / "patient_orgs"
    out.mkdir(parents=True)
    pl.DataFrame(
        [
            {
                "url": url,
                "origin": "curated",
                "retrieved_at": "2026-10-03",
                "text": text,
                "org_id": "ORG:kcnt1-epilepsy-foundation",
            }
        ]
    ).write_parquet(out / "pages.parquet")
    response = {
        "is_patient_organization": True,
        "organization_name": "KCNT1 Epilepsy Foundation",
        "name_quote": "managed by the KCNT1 Epilepsy Foundation",
        "diseases_served": [
            {
                "name": "KCNT1-related epilepsy",
                "quote": "dedicated to individuals with changes in the KCNT1 gene",
            },
            {"name": "Dravet syndrome", "quote": "Dravet syndrome"},  # not on the page
        ],
        "country": None,
        "runs_registry": True,
        "registry_name": "KCNT1 International Registry",
        "registry_quote": "The KCNT1 International Registry is a comprehensive database managed "
        "by the KCNT1 Epilepsy Foundation",
        "runs_natural_history_study": False,
        "natural_history_study_name": None,
        "natural_history_study_quote": None,
        "contact_url": "https://evil.example.com/contact",
    }
    client = FakeClient({patient_orgs.OrgPage: response})
    report = await patient_orgs.run(scope, LLMRun.start(client=client, max_calls=5))
    assert report["accepted"] == 2 and report["rejected"] == {"quote_not_found": 1}
    check = report["curated_cross_check"][0]
    assert check["curated_registry"] is True and check["extracted_registry"] is True
    assert check["contact_url"] is None  # other host
    a = pl.read_parquet(data_dirs["extracted"] / "patient_orgs" / "assertions.parquet")
    rels = {(r["source_id"], r["relation"], r["target_id"]) for r in a.iter_rows(named=True)}
    assert rels == {
        ("ORG:kcnt1-epilepsy-foundation", "serves", "MONDO:0013989"),
        ("ORG:kcnt1-epilepsy-foundation", "runs", "REG:kcnt1-international-registry"),
    }
    assert set(a["tier"]) == {"llm_inferred"} and (a["url"] == url).all()


# --- against the OpenAI platform agent's mock server ------------------------------------------


@pytest.fixture
def mock_llm(request):
    try:
        server = request.getfixturevalue("mock_openai_env")
    except pytest.FixtureLookupError:
        pytest.skip("backend mock OpenAI server not available")
    from backend.llm import LLMClient, StaticToken

    return server, LLMClient(StaticToken("mock-static-test"), base_url=server.api_base)


async def test_abstracts_against_mock_server(data_dirs, scope, mock_llm):
    server, client = mock_llm
    _write_abstracts(data_dirs)
    server.enqueue({"json": RELATIONS})
    report = await abstracts.run(scope, LLMRun.start(client=client, max_calls=3))
    assert report["llm_calls"] == 1 and report["accepted"] == 1, report
    assert report["dropped_inferred"] == 1


async def test_usage_limit_from_mock_server(data_dirs, scope, mock_llm):
    server, client = mock_llm
    _write_abstracts(data_dirs)
    server.configure(fail_mode="usage_limit")
    run = LLMRun.start(client=client, max_calls=3)
    report = await abstracts.run(scope, run)
    assert run.stop_reason == "usage_limit_exceeded"
    assert report["status"] == "stopped_usage_limit_exceeded" and report["accepted"] == 0
