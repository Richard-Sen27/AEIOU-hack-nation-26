"""Sanity timings on a synthetic graph of realistic size (5k nodes, 40k edges)."""

import random
import time

import pytest

from backend.api.services import export
from backend.api.services import graph as graph_service
from backend.api.services import path as path_service
from backend.schemas.common import Lens
from backend.schemas.enums import RELATION_FAMILY, PathFamily, Relation, Role

TYPES = {
    "disease": ("MONDO", 1500),
    "gene": ("HGNC", 800),
    "phenotype": ("HP", 1100),
    "mechanism": ("MECH", 3),
    "pathway": ("GO", 200),
    "variant": ("CLINVAR", 400),
    "paper": ("PMID", 500),
    "researcher": ("RES", 250),
    "trial": ("NCT", 150),
    "patient_org": ("ORG", 97),
}
LINKS = [  # (relation, source type, target type, count)
    (Relation.caused_by_variant_in, "disease", "gene", 4000),
    (Relation.has_phenotype, "disease", "phenotype", 20000),
    (Relation.acts_via, "gene", "mechanism", 900),
    (Relation.participates_in, "gene", "pathway", 4000),
    (Relation.similar_symptoms, "disease", "disease", 3000),
    (Relation.shared_pathway, "disease", "disease", 1500),
    (Relation.variant_of, "variant", "gene", 400),
    (Relation.about, "paper", "disease", 2500),
    (Relation.authored, "researcher", "paper", 1500),
    (Relation.studies, "trial", "disease", 700),
    (Relation.serves, "patient_org", "disease", 600),
    (Relation.observed_in, "variant", "disease", 900),
]


def synthetic_rows(seed: int = 7):
    rng = random.Random(seed)
    nodes, ids = [], {}
    for ntype, (prefix, count) in TYPES.items():
        ids[ntype] = [f"{prefix}:{i:07d}" for i in range(count)]
        for nid in ids[ntype]:
            nodes.append(
                {
                    "id": nid,
                    "type": ntype,
                    "label": f"{ntype} {nid}",
                    "attrs": {"classification": "pathogenic"} if ntype == "variant" else {},
                    "cluster_id": f"CLUSTER:{rng.randrange(40)}" if ntype == "disease" else None,
                    "x": rng.uniform(-1000, 1000),
                    "y": rng.uniform(-1000, 1000),
                    "centrality": rng.random(),
                }
            )
    edges, evidence, seen = [], [], set()
    for relation, s_type, t_type, count in LINKS:
        targets = ids[t_type]
        weights = [1 / (i + 1) ** 0.8 for i in range(len(targets))]  # power-law hubs
        for _ in range(count):
            s = rng.choice(ids[s_type])
            t = rng.choices(targets, weights)[0]
            eid = f"e_{len(edges):012x}"
            if s == t or (s, relation, t) in seen:
                continue
            seen.add((s, relation, t))
            conf = rng.choice([0.3, 0.5, 0.7, 0.79, 0.9, 0.97])
            edges.append(
                {
                    "id": eid,
                    "source_id": s,
                    "target_id": t,
                    "relation": relation.value,
                    "family": RELATION_FAMILY[relation].value,
                    "confidence": conf,
                    "origin": "observed",
                    "status": "active",
                    "features": None,
                    "data_version": "synthetic",
                }
            )
            evidence.append(
                {
                    "edge_id": eid,
                    "source_type": "PubMed",
                    "polarity": "supports",
                    "n": 1,
                    "source_ids": [f"PMID:{len(edges)}"],
                }
            )
    clusters = [
        {
            "id": f"CLUSTER:{i}",
            "label": f"Cluster {i}",
            "mechanism_summary": None,
            "member_count": None,
            "attrs": {},
        }
        for i in range(40)
    ]
    return nodes, edges, evidence, clusters


@pytest.fixture(scope="module")
def synthetic():
    return synthetic_rows()


def test_synthetic_graph_is_fast(synthetic, restore_graph):
    nodes, edges, evidence, clusters = synthetic
    assert len(nodes) == 5000 and len(edges) >= 38000

    started = time.perf_counter()
    store = graph_service.build_store(
        nodes=nodes,
        edges=edges,
        evidence=evidence,
        clusters=clusters,
        ingestion={"data_version": "synthetic", "source_versions": {"pubmed": "x"}},
    )
    build_s = time.perf_counter() - started
    graph_service.set_graph(store)
    assert build_s < 8, build_s

    started = time.perf_counter()
    graph_service.atlas_payload()
    assert time.perf_counter() - started < 3

    hub = max(store.degree, key=store.degree.get)
    timings = {}
    for role in Role:
        started = time.perf_counter()
        hood = graph_service.neighborhood(hub, Lens(role=role))
        timings[role] = time.perf_counter() - started
    assert len(hood.nodes) > 100
    assert max(timings.values()) < 1.5, timings

    started = time.perf_counter()
    graph_service.neighborhood("MONDO:0000042", Lens())
    graph_service.node_detail("MONDO:0000042", Lens())
    assert time.perf_counter() - started < 0.2

    rng = random.Random(3)
    diseases = [n["id"] for n in nodes if n["type"] == "disease"]
    worst = 0.0
    for _ in range(5):
        a, b = rng.sample(diseases, 2)
        started = time.perf_counter()
        resp = path_service.find_paths(a, b, family=PathFamily.all, k=3)
        worst = max(worst, time.perf_counter() - started)
        assert resp.status in ("ok", "no_supported_route")
    assert worst < 3, worst

    started = time.perf_counter()
    export.export_graph("MONDO:0000042", depth=2)
    assert time.perf_counter() - started < 2
