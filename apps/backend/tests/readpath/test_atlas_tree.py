import math
import random
from collections import Counter

import pytest

from backend.api.services import atlas_tree
from backend.api.services import graph as graph_service
from backend.api.services.atlas_tree import institution_kind, normalize_country
from backend.schemas.atlas import AtlasCategory, AtlasTree, GroupBasis, TreeNodeKind

from .conftest import refresh_overlays


def _by_id(tree: AtlasTree) -> dict:
    return {n.id: n for n in tree.nodes}


def _children(tree: AtlasTree) -> dict[str, list]:
    out: dict[str, list] = {}
    for n in tree.nodes:
        if n.parent_id:
            out.setdefault(n.parent_id, []).append(n)
    return out


def _with_contribution(store: graph_service.GraphStore) -> graph_service.GraphStore:
    """A copy of the store carrying one contributed asset (a CONTRIB: registry node)."""
    disease = next(n.id for n in store.nodes.values() if n.type == "disease")
    nodes, edges = graph_service.build_contribution_overlay(
        store,
        [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "kind": "asset",
                "status": "pending_review",
                "payload": {"name": "Family-run seizure diary", "disease_ids": [disease]},
            }
        ],
    )
    copy = graph_service.GraphStore(**vars(store))
    copy.contrib_nodes, copy.contrib_edges, copy.tree_cache = nodes, edges, None
    return copy


def _store_from_rows(nodes: list[dict], data_version: str = "rows") -> graph_service.GraphStore:
    return graph_service.build_store(
        nodes=nodes, edges=[], evidence=[], clusters=[], ingestion={"data_version": data_version}
    )


def _node(nid: str, ntype: str, label: str, **attrs) -> dict:
    return {"id": nid, "type": ntype, "label": label, "attrs": attrs, "x": 0.0, "y": 0.0}


def _assert_tree_invariants(tree: AtlasTree, expected_entities: set[str]) -> None:
    by_id = _by_id(tree)
    entities = [n.id for n in tree.nodes if n.kind == TreeNodeKind.entity]
    assert len(entities) == len(set(entities)) and set(entities) == expected_entities
    assert len(by_id) == len(tree.nodes)
    sectors = {c.id: (c.angle_end, c.angle_start) for c in tree.categories}
    kids = _children(tree)
    seen: set[str] = set()
    for node in tree.nodes:
        # pre-order: every parent is emitted before its children
        assert node.parent_id is None or node.parent_id in seen
        seen.add(node.id)
        # every parent chain reaches the root
        cur, hops = node, 0
        while cur.parent_id is not None:
            cur, hops = by_id[cur.parent_id], hops + 1
        assert cur.id == atlas_tree.ROOT_ID and hops == node.depth
        # the 30-leaf rule: no parent holds more than 30 entity leaves
        leaves = [
            c for c in kids.get(node.id, []) if c.kind == TreeNodeKind.entity and not c.child_count
        ]
        assert len(leaves) <= atlas_tree.MAX_LEAVES, node.id
        # every node lies inside its category's sector
        if node.category is not None:
            lo, hi = sectors[node.category]
            a = math.atan2(node.y, node.x)
            while a > hi:
                a -= 2 * math.pi
            while a < lo:
                a += 2 * math.pi
            assert lo <= a <= hi, node.id
        assert (node.entity_type is not None) == (node.kind == TreeNodeKind.entity)
        assert (node.group_basis is not None) == (node.kind == TreeNodeKind.group)
        assert (node.category is None) == (node.kind == TreeNodeKind.root)
        assert node.child_count == len(kids.get(node.id, []))
    assert tree.nodes[0].entity_count == len(expected_entities)
    assert sum(c.entity_count for c in tree.categories) == len(expected_entities)


async def test_tree_contract_and_coverage(client):
    resp = await client.get("/atlas/tree.json")
    assert resp.status_code == 200
    tree = AtlasTree.model_validate(resp.json())
    store = graph_service.get_graph()

    assert tree.root_id == "T:root" and tree.nodes[0].id == "T:root"
    assert tree.data_version == "fixture"
    assert tree.layout_version == atlas_tree.LAYOUT_VERSION
    assert [c.id for c in tree.categories] == list(atlas_tree.CATEGORY_ORDER)
    _assert_tree_invariants(tree, set(store.nodes) | set(store.contrib_nodes))
    assert set(store.edges) <= {e.id for e in tree.edges}


async def test_contributed_nodes_go_under_their_own_group(app):
    store = _with_contribution(graph_service.get_graph())
    tree = atlas_tree.build_tree(store)
    _assert_tree_invariants(tree, set(store.nodes) | set(store.contrib_nodes))
    by_id = _by_id(tree)
    (cid,) = store.contrib_nodes
    node = by_id[cid]
    assert node.contributed and node.entity_type == "registry"
    group = by_id[node.parent_id]
    assert group.group_basis == GroupBasis.contributed
    assert group.label == "Contributed, pending review" and group.parent_id == "T:community"
    assert not any(n.contributed for n in tree.nodes if n.id != cid)


async def test_build_is_deterministic(app):
    store = graph_service.get_graph()
    first = atlas_tree.build_tree(store).model_dump_json()
    assert atlas_tree.build_tree(store).model_dump_json() == first
    # the same data loaded in a different order gives the same bytes
    shuffled = graph_service.GraphStore(**vars(store))
    items = list(store.nodes.items())
    random.Random(5).shuffle(items)
    shuffled.nodes = dict(items)
    assert atlas_tree.build_tree(shuffled).model_dump_json() == first


async def test_tree_etag_and_caching(client):
    resp = await client.get("/atlas/tree.json", headers={"Accept-Encoding": "gzip"})
    etag = resp.headers["etag"]
    assert etag.startswith(f'"fixture.{atlas_tree.LAYOUT_VERSION}.')
    assert resp.headers["content-encoding"] == "gzip"
    assert "max-age" in resp.headers["cache-control"]
    again = await client.get("/atlas/tree.json", headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.headers["etag"] == etag


async def test_etag_follows_data_and_layout_version(app, restore_graph, monkeypatch):
    store = graph_service.get_graph()
    _, etag = atlas_tree.tree_payload()

    copy = graph_service.GraphStore(**vars(store))
    copy.data_version, copy.tree_cache = "fixture-2", None
    graph_service.set_graph(copy)
    _, etag_data = atlas_tree.tree_payload()
    assert etag_data.startswith(f'"fixture-2.{atlas_tree.LAYOUT_VERSION}.') and etag_data != etag

    monkeypatch.setattr(atlas_tree, "LAYOUT_VERSION", atlas_tree.LAYOUT_VERSION + 1)
    copy.tree_cache = None
    body, etag_layout = atlas_tree.tree_payload()
    assert etag_layout.startswith(f'"fixture-2.{atlas_tree.LAYOUT_VERSION}.')
    assert AtlasTree.model_validate_json(body).layout_version == atlas_tree.LAYOUT_VERSION


async def test_cache_resets_on_overlay_refresh(app):
    atlas_tree.get_tree()
    store = graph_service.get_graph()
    cached = store.tree_cache
    assert cached is not None and atlas_tree.get_tree() is cached.tree
    await refresh_overlays()
    assert store.tree_cache is None
    assert atlas_tree.get_tree() is not cached.tree


async def test_symptom_tree_from_hpo_lineage(app):
    tree = atlas_tree.get_tree()
    by_id, kids = _by_id(tree), _children(tree)

    organ_systems = kids["T:symptoms"]
    assert {n.ref_id for n in organ_systems} == {"HP:0000707", "HP:0033127", "HP:0025031"}
    assert all(n.group_basis == GroupBasis.hpo_class for n in organ_systems)

    physiology = by_id["T:symptoms/HP:0012638"]
    assert physiology.parent_id == "T:symptoms/HP:0000707"
    # single-child chains are spliced out: Ataxia, Migraine and Autistic behavior hang on
    # "Abnormal nervous system physiology" directly
    for hp in ("HP:0001251", "HP:0002076", "HP:0000729"):
        assert by_id[hp].parent_id == physiology.id
    for spliced in ("HP:0011097", "HP:0012758", "HP:0011443", "HP:0002315", "HP:0000708"):
        assert f"T:symptoms/{spliced}" not in by_id
    # a class with two children stays
    assert {c.id for c in kids["T:symptoms/HP:0012759"]} == {"HP:0001263", "HP:0001249"}
    # a graph phenotype that is an ancestor of others is an internal entity node
    seizure = by_id["HP:0001250"]
    assert seizure.kind == TreeNodeKind.entity and seizure.parent_id == physiology.id
    assert {c.id for c in kids["HP:0001250"]} == {"HP:0002373", "HP:0002133", "HP:0012469"}
    assert by_id["HP:0001252"].parent_id == "T:symptoms/HP:0033127"
    assert "T:symptoms/none" not in by_id


def _without_lineage(store: graph_service.GraphStore, keep: set[str]) -> graph_service.GraphStore:
    copy = graph_service.GraphStore(**vars(store))
    copy.nodes = {
        k: (
            n
            if n.type != "phenotype" or k in keep
            else n.model_copy(
                update={"attrs": {a: v for a, v in n.attrs.items() if a != "hpo_lineage"}}
            )
        )
        for k, n in store.nodes.items()
    }
    copy.tree_cache = None
    return copy


async def test_symptom_tree_falls_back_without_lineage(app):
    store = graph_service.get_graph()
    phenotypes = {k for k, n in store.nodes.items() if n.type == "phenotype"}

    tree = atlas_tree.build_tree(_without_lineage(store, keep=set()))
    by_id, kids = _by_id(tree), _children(tree)
    (fallback,) = kids["T:symptoms"]
    assert fallback.id == "T:symptoms/none" and fallback.label == "Classification not loaded"
    assert fallback.group_basis == GroupBasis.not_recorded
    assert {c.id for c in kids[fallback.id]} == phenotypes
    _assert_tree_invariants(tree, set(store.nodes) | set(store.contrib_nodes))

    # partly loaded: terms without a lineage wait in the fallback, the rest form the tree;
    # a term named in another term's lineage still gets its place there
    partial = atlas_tree.build_tree(
        _without_lineage(store, keep=phenotypes - {"HP:0001250", "HP:0011968"})
    )
    by_id = _by_id(partial)
    assert by_id["HP:0011968"].parent_id == "T:symptoms/none"
    assert by_id["HP:0001250"].parent_id == "T:symptoms/HP:0012638"
    _assert_tree_invariants(partial, set(store.nodes) | set(store.contrib_nodes))


def test_alphabetical_ranges_and_not_recorded():
    nodes = [
        _node(f"INST:{i:03d}", "institution", f"Hospital {i:03d}", country="France")
        for i in range(75)
    ]
    nodes += [_node("INST:x", "institution", "Somewhere Lab")]  # no country recorded
    tree = atlas_tree.build_tree(_store_from_rows(nodes))
    by_id, kids = _by_id(tree), _children(tree)
    ranges = kids["T:institutions/clinical/France"]
    assert [len(kids[r.id]) for r in ranges] == [25, 25, 25]
    assert all(r.group_basis == GroupBasis.alpha_range and r.ref_id is None for r in ranges)
    assert ranges[0].label == "Ho–Ho"
    assert by_id["INST:x"].parent_id == "T:institutions/academic/none"
    assert by_id["T:institutions/academic/none"].group_basis == GroupBasis.not_recorded
    _assert_tree_invariants(tree, {n["id"] for n in nodes})


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("Boston Children's Hospital", "clinical"),
        ("University Hospital Gent/Ghent University", "clinical"),
        ("Hôpital Necker", "clinical"),
        ("Klinik für Neuropädiatrie", "clinical"),
        ("Mayo Clinic", "clinical"),
        ("CHU Rouen", "clinical"),
        ("Fondazione IRCCS Istituto Neurologico Carlo Besta", "clinical"),
        ("Oxford University Hospitals NHS Foundation Trust", "clinical"),
        ("Erasmus MC University Medical Center", "clinical"),
        ("Danish Epilepsy Centre Filadelfia", "clinical"),
        ("Centre de Référence Maladies Rares « déficience intellectuelle »", "clinical"),
        ("Children's Hosp Of Philadelphia", "clinical"),
        ("Johns Hopkins University", "academic"),
        ("Weill Medical Coll Of Cornell Univ", "academic"),
        ("New York Genome Center", "academic"),
        ("Baylor College of Medicine", "academic"),
        ("Broad Institute of MIT and Harvard", "academic"),
        ("Istituto Italiano di Tecnologia", "academic"),
        ("MSD Research Laboratories", "academic"),
        ("Simons Foundation", "other"),
        ("Capsida Biotherapeutics, Inc.", "other"),
    ],
)
def test_institution_kind(name, kind):
    assert institution_kind(name) == kind


@pytest.mark.parametrize(
    ("raw", "country"),
    [
        ("USA", "United States"),
        ("United States", "United States"),
        ("U.S.A", "United States"),
        ("Texas", "United States"),
        ("NY", "United States"),
        ("UK", "United Kingdom"),
        ("United Kingdom", "United Kingdom"),
        ("The Netherlands", "Netherlands"),
        ("the Netherlands", "Netherlands"),
        ("Republic of Korea", "South Korea"),
        ("P. R. China", "China"),
        ("China)", "China"),
        ("Leuven Belgium", "Belgium"),
        ("Victoria  Australia", "Australia"),
        ("Québec", "Canada"),
        ("Luxemburg", "Luxembourg"),
        ("France", "France"),
        ("and", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_country(raw, country):
    assert normalize_country(raw) == country


def test_category_order_and_sectors():
    nodes = [_node("HGNC:1", "gene", "SCN1A", location="2q24.3"), _node("RES:1", "researcher", "A")]
    tree = atlas_tree.build_tree(_store_from_rows(nodes))
    starts = [c.angle_start for c in tree.categories]
    assert starts == sorted(starts, reverse=True)  # clockwise from 12 o'clock
    assert tree.categories[0].angle_start == pytest.approx(
        math.pi / 2 - atlas_tree.GAP / 2, abs=1e-3
    )
    assert Counter(n.category for n in tree.nodes if n.kind == TreeNodeKind.category) == {
        c: 1 for c in AtlasCategory
    }
    by_id = _by_id(tree)
    assert by_id["HGNC:1"].label == "SCN1A · 2q24.3" and by_id["HGNC:1"].parent_id == "T:genes/chr2"


def _min_distance(tree: AtlasTree) -> float:
    pts = [(n.x, n.y) for n in tree.nodes]
    return min(math.dist(a, b) for i, a in enumerate(pts) for b in pts[i + 1 :])


async def test_nodes_keep_their_distance_and_labels_stay_clear(app):
    store = _with_contribution(graph_service.get_graph())
    tree = atlas_tree.build_tree(store)
    # coordinates are rounded to 0.1, so allow that much below the spacing
    assert _min_distance(tree) >= atlas_tree.SPACING - 0.15
    xs, ys = [n.x for n in tree.nodes], [n.y for n in tree.nodes]
    extent = max(max(xs) - min(xs), (max(ys) - min(ys)) / 0.5625)
    clear = atlas_tree.LABEL_HEIGHT * extent / 2
    for c in tree.categories:
        assert all(math.dist((c.label_x, c.label_y), (n.x, n.y)) >= clear for n in tree.nodes), c.id
        # each label sits on its own sector's side of the map
        a = math.atan2(c.label_y, c.label_x)
        while a > c.angle_start:
            a -= 2 * math.pi
        while a < c.angle_end:
            a += 2 * math.pi
        assert c.angle_end <= a <= c.angle_start, c.id


def test_dense_groups_keep_their_distance():
    nodes = [_node(f"RES:{i:04d}", "researcher", f"Person {i:04d}") for i in range(400)]
    tree = atlas_tree.build_tree(_store_from_rows(nodes))
    assert _min_distance(tree) >= atlas_tree.SPACING - 0.15
    _assert_tree_invariants(tree, {n["id"] for n in nodes})


def test_variant_with_several_genes_has_one_home():
    """A variant overlapping several genes (several variant_of edges) sits once, under the
    gene with the smallest id."""
    nodes = [
        _node("HGNC:20", "gene", "GENEB", location="2q24.3"),
        _node("HGNC:10", "gene", "GENEA", location="2q24.3"),
        _node("CLINVAR:1", "variant", "big deletion"),
    ]
    edges = [
        {
            "id": f"e_{gene}",
            "source_id": "CLINVAR:1",
            "target_id": gene,
            "relation": "variant_of",
            "family": "dna",
            "confidence": 0.9,
            "origin": "observed",
            "status": "active",
            "features": None,
            "data_version": "rows",
        }
        for gene in ("HGNC:20", "HGNC:10")
    ]
    store = graph_service.build_store(
        nodes=nodes, edges=edges, evidence=[], clusters=[], ingestion={"data_version": "rows"}
    )
    tree = atlas_tree.build_tree(store)
    assert [n.id for n in tree.nodes].count("CLINVAR:1") == 1
    assert _by_id(tree)["CLINVAR:1"].parent_id == "HGNC:10"
    _assert_tree_invariants(tree, {n["id"] for n in nodes})
