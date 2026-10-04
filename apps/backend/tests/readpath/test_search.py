import os

import pytest

needs_embeddings = pytest.mark.skipif(
    os.environ.get("AMBER_TEST_EMBEDDINGS", "1") == "0", reason="fixture embeddings disabled"
)


async def _search(client, q, **params):
    resp = await client.get("/search", params={"q": q, **params})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_guest_without_cookie(client):
    assert not client.cookies
    body = await _search(client, "Dravet")
    assert body["results"][0]["id"] == "MONDO:0100135"
    assert body["data_version"] == "fixture"


@pytest.mark.parametrize(
    "q", ["MONDO:0100135", "mondo:0100135", "MONDO_0100135", " MONDO:0100135 "]
)
async def test_exact_id_first(client, q):
    first = (await _search(client, q))["results"][0]
    assert first["id"] == "MONDO:0100135" and first["match_kind"] == "exact"


@pytest.mark.parametrize("q", ["MONDO:0100135", "HP:0001250", "MONDO:0000000"])
async def test_id_query_returns_only_id_matches(client, q):
    """No trigram or vector look-alikes after (or instead of) the exact hit."""
    results = (await _search(client, q))["results"]
    assert [r["id"] for r in results] == ([q] if q != "MONDO:0000000" else [])
    assert all(r["match_kind"] == "exact" for r in results)


@pytest.mark.parametrize("q", ["HP:0001250", "HGNC:11444", "NCT99000001"])
async def test_other_exact_ids(client, q):
    assert (await _search(client, q))["results"][0]["id"] == q


@pytest.mark.parametrize("q", ["SCN1A", "scn1a"])
async def test_gene_symbol_first(client, q):
    results = (await _search(client, q))["results"]
    assert results[0]["id"] == "HGNC:10585" and results[0]["type"] == "gene"
    assert results[0]["match_kind"] == "exact"


async def test_synonym_carries_matched_synonym(client):
    first = (await _search(client, "Ohtahara syndrome"))["results"][0]
    assert first["id"] == "MONDO:9900007"
    assert first["label"] == "STXBP1 encephalopathy"
    assert first["matched_synonym"] == "Ohtahara syndrome"


@pytest.mark.parametrize(
    ("q", "expected"), [("Ohtahra", "MONDO:9900007"), ("Dravett", "MONDO:0100135")]
)
async def test_typo_tolerant(client, q, expected):
    first = (await _search(client, q))["results"][0]
    assert first["id"] == expected and first["match_kind"] == "trigram"


async def test_accent_insensitive_query(client):
    assert (await _search(client, "Drávet sýndrome"))["results"][0]["id"] == "MONDO:0100135"


async def test_accent_insensitive_data(client, connect_as):
    conn = await connect_as("atlas_pipeline")
    await conn.execute(
        "INSERT INTO node_synonyms (node_id, synonym, source) VALUES"
        " ('MONDO:9900002', 'Ménière-like hemiplegic attacks', 'test')"
    )
    try:
        first = (await _search(client, "Meniere"))["results"][0]
        assert first["id"] == "MONDO:9900002"
        assert first["matched_synonym"] == "Ménière-like hemiplegic attacks"
    finally:
        await conn.execute("DELETE FROM node_synonyms WHERE source = 'test'")


async def test_type_filter(client):
    results = (await _search(client, "SCN2A", types=["disease"]))["results"]
    assert results and all(r["type"] == "disease" for r in results)
    mixed = (await _search(client, "SCN2A", types=["gene", "variant"]))["results"]
    assert {r["type"] for r in mixed} <= {"gene", "variant"}
    assert mixed[0]["id"] == "HGNC:10588"


async def test_results_typed_and_limited(client):
    results = (await _search(client, "seizure", limit=3))["results"]
    assert len(results) == 3
    assert results[0]["id"] == "HP:0001250"
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


@needs_embeddings
async def test_vector_only_semantic_hit(client):
    first = (await _search(client, "kid shaking during fever"))["results"][0]
    assert first["id"] == "HP:0002373"
    assert first["match_kind"] == "vector" and first["matched_synonym"] is None


async def test_nonsense_returns_little(client):
    results = (await _search(client, "zzqxv banana bread"))["results"]
    assert all(r["match_kind"] != "exact" for r in results)


async def test_validation_never_echoes_query(client):
    resp = await client.get("/search", params={"q": "x" * 300 + "epilepsy"})
    assert resp.status_code == 422
    assert "epilepsy" not in resp.text


@needs_embeddings
async def test_expert_mechanism_query_ranks_clusters(client):
    body = await _search(client, "AAV gene replacement for loss-of-function", expert="true")
    ranked = body["ranked_clusters"]
    assert ranked and ranked[0]["cluster"]["id"] == "CLUSTER:2"
    top = ranked[0]
    assert top["member_count"] == 3
    assert top["trial_count"] >= 1
    assert 0 < top["evidence_strength"] <= 1 and top["evidence_level"] in {"high", "medium", "low"}
    assert top["edge_ids"]
    assert any(r["id"] == "MECH:loss_of_function" for r in body["results"])


async def test_expert_off_has_no_clusters(client):
    body = await _search(client, "loss of function")
    assert body["ranked_clusters"] == []
