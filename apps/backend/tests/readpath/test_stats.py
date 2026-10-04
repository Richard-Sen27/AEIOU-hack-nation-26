from backend.api.services import graph as graph_service
from backend.api.services import stats


async def test_stats_counts_match_the_store(client):
    resp = await client.get("/stats")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    store = graph_service.get_graph()
    nodes, edges = store.nodes.values(), store.edges.values()
    assert body == {
        "data_version": "fixture",
        "diseases": sum(n.type == "disease" for n in nodes),
        "genes": sum(n.type == "gene" for n in nodes),
        "symptoms": sum(n.type == "phenotype" for n in nodes),
        "links_cited": sum(e.origin == "observed" for e in edges),
        "links_computed": sum(e.origin == "inferred" for e in edges),
    }
    assert body["diseases"] > 0 and body["links_cited"] > 0 and body["links_computed"] > 0
    assert resp.headers["cache-control"] == "public, max-age=300"
    assert resp.headers["etag"].startswith('"fixture.')


async def test_stats_etag_revalidates(client):
    etag = (await client.get("/stats")).headers["etag"]
    resp = await client.get("/stats", headers={"If-None-Match": etag})
    assert resp.status_code == 304 and resp.headers["etag"] == etag


async def test_stats_computed_once_per_store(client, restore_graph, monkeypatch):
    calls = []
    real = stats.compute_stats
    monkeypatch.setattr(stats, "compute_stats", lambda s: calls.append(s) or real(s))
    graph_service.set_graph(graph_service.GraphStore(**vars(restore_graph)))
    for _ in range(3):
        assert (await client.get("/stats")).status_code == 200
    assert len(calls) == 1
    empty = graph_service.GraphStore()
    graph_service.set_graph(empty)
    body = (await client.get("/stats")).json()
    assert len(calls) == 2 and body["diseases"] == 0 and body["data_version"] is None
