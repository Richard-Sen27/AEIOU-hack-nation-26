import pytest

from backend.schemas.atlas import AtlasSummary, SummarySectionKey, TreeNodeKind
from backend.schemas.enums import VUS_NOTICE
from readpath.conftest import DEMO

DRAVET = "MONDO:0100135"


async def test_disease_summary_contract(client):
    resp = await client.get(f"/atlas/summary/{DRAVET}", params={"role": "patient"})
    assert resp.status_code == 200
    summary = AtlasSummary.model_validate(resp.json())
    assert summary.node.id == DRAVET and summary.data_version == "fixture"
    assert summary.headline
    assert [p.kind for p in summary.tree_path][:2] == [TreeNodeKind.root, TreeNodeKind.category]
    assert summary.tree_path[1].id == "T:diseases"

    keys = [s.key for s in summary.sections]
    assert keys == [k for k in SummarySectionKey if k in keys]  # fixed order
    assert {SummarySectionKey.genes, SummarySectionKey.symptoms} <= set(keys)
    assert SummarySectionKey.similar_diseases in keys
    for section in summary.sections:
        assert 0 < len(section.items) <= 10 and section.total >= len(section.items)
        assert all(item.type == section.node_type for item in section.items)
    assert 0 < len(summary.explain_edge_ids) <= 20
    assert len(set(summary.explain_edge_ids)) == len(summary.explain_edge_ids)
    assert summary.vus_notice is None


async def test_vus_notice(client):
    body = (await client.get(f"/atlas/summary/{DEMO['vus_variant_id']}")).json()
    assert body["vus_notice"] == VUS_NOTICE


@pytest.mark.parametrize("node_id", ["MONDO:0000000", "T:root", "T:diseases"])
async def test_unknown_and_group_ids_404(client, node_id):
    resp = await client.get(f"/atlas/summary/{node_id}")
    assert resp.status_code == 404
