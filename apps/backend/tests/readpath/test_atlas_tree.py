from collections import Counter

from backend.api.services import graph as graph_service
from backend.schemas.atlas import AtlasCategory, AtlasTree, TreeNodeKind


async def test_tree_contract_and_coverage(client):
    resp = await client.get("/atlas/tree.json")
    assert resp.status_code == 200
    tree = AtlasTree.model_validate(resp.json())
    store = graph_service.get_graph()

    assert tree.root_id == "T:root" and tree.nodes[0].id == "T:root"
    assert tree.data_version == "fixture"
    assert [c.id for c in tree.categories] == list(AtlasCategory)
    ids = [n.id for n in tree.nodes]
    assert len(ids) == len(set(ids))

    entities = [n.id for n in tree.nodes if n.kind == TreeNodeKind.entity]
    expected = set(store.nodes) | set(store.contrib_nodes)
    assert len(entities) == len(set(entities)) and set(entities) == expected

    # pre-order: every parent is emitted before its children
    seen: set[str] = set()
    children: Counter[str] = Counter()
    for node in tree.nodes:
        assert node.parent_id is None or node.parent_id in seen
        seen.add(node.id)
        if node.parent_id:
            children[node.parent_id] += 1
        assert (node.entity_type is not None) == (node.kind == TreeNodeKind.entity)
        assert (node.group_basis is not None) == (node.kind == TreeNodeKind.group)
        assert (node.category is None) == (node.kind == TreeNodeKind.root)
    assert all(n.child_count == children[n.id] for n in tree.nodes)
    assert tree.nodes[0].entity_count == len(expected)
    assert sum(c.entity_count for c in tree.categories) == len(expected)

    edge_ids = {e.id for e in tree.edges}
    assert set(store.edges) <= edge_ids


async def test_tree_etag_and_caching(client):
    resp = await client.get("/atlas/tree.json")
    etag = resp.headers["etag"]
    assert etag.startswith('"fixture.1.')
    assert "max-age" in resp.headers["cache-control"]
    again = await client.get("/atlas/tree.json", headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.headers["etag"] == etag
