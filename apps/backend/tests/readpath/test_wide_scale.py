"""Wide scope, stage A, at full size on a synthetic store (wide_data.py: about 7,430 diseases
and 290,000 edges): symptom ranking is exact and fast, hubs are capped, path search stays
fast, and the tree keeps the focus set only."""

import random
import time

import pytest

from backend.api.services import atlas_summary, atlas_tree, phenotype_match
from backend.api.services import graph as graph_service
from backend.api.services import path as path_service
from backend.phenotype_similarity import phenotype_similarity
from backend.schemas.common import Lens
from backend.schemas.enums import PathFamily, PathStatus, Role

from . import wide_data


@pytest.fixture(scope="module")
def wide():
    return wide_data.build()


@pytest.fixture
def installed(wide):
    """The wide store and its term table as the current ones (restored afterwards)."""
    store = graph_service.get_graph()
    graph_service.set_graph(wide.store)
    phenotype_match.set_terms(wide.terms)
    yield wide
    graph_service.set_graph(store)
    phenotype_match.set_terms(None)


def test_synthetic_store_has_the_wide_size(wide):
    store = wide.store
    assert len([n for n in store.nodes.values() if n.type == "disease"]) == 7430
    assert len(store.edges) > 280_000
    assert store.degree[wide.hubs[0]] > 2000  # a hub symptom


def _exact(index, query, did):
    p = index.profiles[did]
    return phenotype_similarity(
        dict.fromkeys(query, 1.0), p.terms, index.terms.ic, index.terms.ancestors_of
    )


def test_fast_scores_equal_phenotype_similarity(installed):
    index = phenotype_match.get_index()
    rng = random.Random(5)
    for _ in range(3):
        query = rng.sample(installed.hubs[:600], 4) + [rng.choice(list(index.terms.labels))]
        fast = index.fast_scores(query)
        sample = rng.sample(range(len(index.ids)), 300) + [int(fast.argmax())]
        for i in sample:
            assert fast[i] == pytest.approx(_exact(index, query, index.ids[i]), abs=1e-9)


def test_rank_is_the_exact_top_ten():
    """The early stop returns what scoring every disease would (smaller synthetic store)."""
    small = wide_data.build(seed=3, scale=0.1)
    index = phenotype_match.PhenotypeIndex(small.store, small.terms)
    small.store.phenotype_index = index
    phenotype_match.set_terms(small.terms)
    try:
        rng = random.Random(9)
        for _ in range(3):
            present = rng.sample(small.hubs[:300], 4)
            absent = rng.sample(small.hubs[300:400], 2)
            got = phenotype_match.rank(present, absent, store=small.store)
            brute = []
            for did in index.ids:
                profile = index.profiles[did]
                if not phenotype_match._shared(profile, present, index.terms):
                    continue
                sim = _exact(index, present, did)
                score, *_ = phenotype_match._penalized(profile, sim, present, absent, index.terms)
                if score > 0:
                    brute.append((-score, did))
            brute.sort()
            assert [m.disease_id for m in got] == [d for _, d in brute[:10]]
            assert [m.score for m in got] == pytest.approx([-s for s, _ in brute[:10]])
    finally:
        phenotype_match.set_terms(None)


def test_rank_is_fast_over_all_diseases(installed):
    phenotype_match.get_index()  # built at load in the API
    rng = random.Random(1)
    worst = 0.0
    for _ in range(10):
        present = rng.sample(installed.hubs[:400], 5)
        absent = rng.sample(installed.hubs[400:800], 1)
        started = time.perf_counter()
        found = phenotype_match.rank(present, absent)
        worst = max(worst, time.perf_counter() - started)
        assert found and len(found) <= 10
        assert all(m.overlap >= 1 for m in found)
    assert worst < 0.5


def test_index_build_is_quick(wide):
    started = time.perf_counter()
    phenotype_match.PhenotypeIndex(wide.store, wide.terms)
    assert time.perf_counter() - started < 5.0


def test_hub_neighborhood_is_capped(installed):
    hub = installed.hubs[0]
    hood, total = graph_service.neighborhood_with_total(hub, Lens(role=Role.patient))
    assert total == installed.store.degree[hub] > graph_service.MAX_NEIGHBORS
    assert len(hood.nodes) == graph_service.MAX_NEIGHBORS + 1
    ids = {n.id for n in hood.nodes}
    assert all(e.source_id in ids and e.target_id in ids for e in hood.edges)


def test_path_search_stays_fast(installed):
    rng = random.Random(4)
    for family in (PathFamily.all, PathFamily.dna, PathFamily.symptoms):
        a, b = rng.sample(installed.core, 2)
        started = time.perf_counter()
        resp = path_service.find_paths(a, b, family=family, k=3)
        assert time.perf_counter() - started < 3.0
        assert resp.status in (PathStatus.ok, PathStatus.no_supported_route)


def test_tree_keeps_the_focus_set(installed):
    store = installed.store
    tree = atlas_tree.build_tree(store)
    entities = {n.id for n in tree.nodes if n.kind == "entity"}
    diseases = {n for n in entities if store.nodes[n].type == "disease"}
    assert diseases == set(installed.focus)
    assert not entities & set(installed.core)
    assert not any(store.nodes[n].type in ("gene", "phenotype") for n in entities)  # all core
    assert all(e.source in entities and e.target in entities for e in tree.edges)
    focus_clusters = {store.nodes[d].cluster_id for d in installed.focus}
    assert {c.id for c in tree.clusters} == focus_clusters


def test_hub_summary_answers_quickly(installed):
    graph_service.freeze_heap()  # as load_graph does after loading
    atlas_tree.get_tree()  # built at startup in the API
    lens = Lens(role=Role.patient)
    for hub in installed.hubs[:3]:
        started = time.perf_counter()
        summary = atlas_summary.atlas_summary(hub, lens)
        assert time.perf_counter() - started < 1.0
        diseases = next(s for s in summary.sections if s.key == "diseases")
        assert diseases.total == installed.store.degree[hub] and len(diseases.items) == 10
