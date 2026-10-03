import csv
import io
import xml.etree.ElementTree as ET

import networkx as nx

from backend.api.services import graph as graph_service

DRAVET = "MONDO:0100135"


async def test_csv_export(client):
    resp = await client.get("/export/graph", params={"node": DRAVET})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    disposition = resp.headers["content-disposition"]
    assert 'filename="amber-MONDO-0100135-depth1-fixture.csv"' in disposition
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    store = graph_service.get_graph()
    incident = set(store.incident[DRAVET])
    assert incident <= {r["edge_id"] for r in rows}
    row = next(r for r in rows if r["edge_id"] == "e_da7bfb96736c")
    assert row["relation"] == "caused_by_variant_in" and float(row["confidence"]) == 0.97
    assert "fixture:1.1" in row["evidence_source_ids"]
    assert row["evidence_sources"].startswith("fixture:")


async def test_graphml_export_parses(client):
    resp = await client.get(
        "/export/graph", params={"node": DRAVET, "depth": 2, "format": "graphml"}
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/graphml+xml")
    assert resp.headers["content-disposition"].endswith('.graphml"')
    ET.fromstring(resp.content)
    g = nx.parse_graphml(resp.text, force_multigraph=True)
    assert DRAVET in g
    depth1 = await client.get("/export/graph", params={"node": DRAVET, "format": "graphml"})
    assert g.number_of_nodes() > nx.parse_graphml(depth1.text).number_of_nodes()
    attrs = next(d for _, _, d in g.edges(data=True) if d.get("id") == "e_da7bfb96736c")
    assert attrs["confidence"] == 0.97 and "fixture:1.1" in attrs["evidence_source_ids"]


async def test_export_errors(client):
    assert (await client.get("/export/graph", params={"node": "MONDO:0"})).status_code == 404
    bad = await client.get("/export/graph", params={"node": DRAVET, "depth": 9})
    assert bad.status_code == 422
