"""A synthetic store at the wide scope's size (stage A): about 7,430 diseases, 5,172 genes,
10,500 annotated HPO terms out of a 20,000-term ontology, about 290,000 edges.

Shapes follow the measured wide data: has_phenotype per disease median about 19 (max 233),
hub symptoms linked to about 2,000 diseases, up to 19 diseases per gene, 168 focus diseases.
Built with `model_construct` (no validation) so a test can afford it; deterministic per seed.
"""

import math
import random
from dataclasses import dataclass

from backend.api.services import graph as graph_service
from backend.api.services import phenotype_match
from backend.schemas.enums import (
    RELATION_FAMILY,
    EdgeStatus,
    NodeType,
    Origin,
    Relation,
    confidence_level,
)
from backend.schemas.graph import ClusterSummary, Edge, Node

N_DISEASES = 7430
N_FOCUS = 168
N_GENES = 5172
N_TERMS = 20000
N_PATHWAYS = 1578
ROOT = "HP:0000118"
FREQUENCIES = (1.0, 0.895, 0.545, 0.17, 0.025, None)
LABELS = (
    "seizure",
    "hypotonia",
    "developmental delay",
    "ossification",
    "cough",
    "ataxia",
    "microcephaly",
    "scoliosis",
    "cardiomyopathy",
    "hearing loss",
)


@dataclass
class WideData:
    store: graph_service.GraphStore
    terms: phenotype_match.TermTable
    term_rows: list[dict]
    hubs: list[str]  # the most linked annotated terms, most linked first
    focus: list[str]
    core: list[str]


def _edge(eid: str, s: str, relation: Relation, t: str, conf: float, **features) -> Edge:
    return Edge.model_construct(
        id=eid,
        source_id=s,
        target_id=t,
        relation=relation,
        family=RELATION_FAMILY[relation],
        confidence=conf,
        confidence_level=confidence_level(conf),
        origin=Origin.inferred if relation in _INFERRED else Origin.observed,
        status=EdgeStatus.active,
        features=features or None,
        data_version="wide",
        evidence_count=1,
        contradiction_count=0,
        flagged=False,
        explanation=None,
    )


_INFERRED = {Relation.similar_symptoms, Relation.shared_gene}


def _ontology(rng: random.Random) -> tuple[list[str], dict[str, list[str]]]:
    ids = [ROOT] + [f"HP:{9000000 + i:07d}" for i in range(1, N_TERMS)]
    parents: dict[str, list[str]] = {ROOT: []}
    for i, tid in enumerate(ids[1:], start=1):
        # parents come earlier in the list: a DAG about 10 levels deep, 10% with two parents
        low = max(0, i // 3 - 50)
        first = ids[rng.randrange(low, max(low + 1, i // 3 + 1))]
        parents[tid] = [first]
        if i > 30 and rng.random() < 0.1:
            second = ids[rng.randrange(0, i)]
            if second != first:
                parents[tid].append(second)
    return ids, parents


def build(seed: int = 11, scale: float = 1.0) -> WideData:
    """The synthetic store; `scale` < 1 shrinks diseases, genes and links (not the ontology)."""
    n_diseases, n_genes = int(N_DISEASES * scale), int(N_GENES * scale)
    rng = random.Random(seed)
    ids, parents = _ontology(rng)
    anc: dict[str, frozenset[str]] = {}
    for tid in ids:  # parents precede children
        out: set[str] = set()
        for p in parents[tid]:
            out.add(p)
            out |= anc[p]
        anc[tid] = frozenset(out)

    # annotations: deeper terms (second half of the list) by a power law, so a few are hubs
    pool = ids[N_TERMS // 3 :]
    weights = [1 / (i + 1) ** 0.75 for i in range(len(pool))]
    rng.shuffle(pool)
    diseases = [f"MONDO:{8000000 + i:07d}" for i in range(n_diseases)]
    annotations: dict[str, dict[str, float | None]] = {}
    for did in diseases:
        k = min(233, max(1, int(rng.lognormvariate(math.log(23), 0.7))))
        terms = set(rng.choices(pool, weights, k=k))
        annotations[did] = {t: rng.choice(FREQUENCIES) for t in terms}

    # information content over the synthetic corpus
    holders: dict[str, int] = {}
    for terms in annotations.values():
        for t in set().union(*({t} | anc[t] for t in terms)):
            holders[t] = holders.get(t, 0) + 1
    ic = {t: -math.log(n / n_diseases) for t, n in holders.items()}
    term_rows = [
        {
            "id": tid,
            "label": f"{LABELS[i % len(LABELS)]} {tid[-5:]}",
            "synonyms": [f"synonym {tid[-5:]}"],
            "parents": parents[tid],
            "ic": ic.get(tid),
        }
        for i, tid in enumerate(ids)
    ]
    table = phenotype_match.table_from_rows(term_rows)
    assert table is not None

    nodes: dict[str, Node] = {}
    focus, core = diseases[:N_FOCUS], diseases[N_FOCUS:]
    for i, did in enumerate(diseases):
        nodes[did] = Node.model_construct(
            id=did,
            type=NodeType.disease,
            label=f"synthetic disease {i}",
            description=None,
            url=None,
            attrs={"tier": "focus" if i < N_FOCUS else "core"},
            cluster_id=f"CLUSTER:{i % 134}",
            x=0.0,
            y=0.0,
            centrality=None,
        )
    annotated = {t for terms in annotations.values() for t in terms}
    for tid in annotated:
        nodes[tid] = Node.model_construct(
            id=tid,
            type=NodeType.phenotype,
            label=table.labels[tid],
            description=None,
            url=None,
            attrs={"tier": "core", "ic": ic.get(tid), "ancestors": sorted(anc[tid])},
            cluster_id=None,
            x=0.0,
            y=0.0,
            centrality=None,
        )
    genes = [f"HGNC:{70000 + i}" for i in range(n_genes)]
    pathways = [f"R-HSA-{900000 + i}" for i in range(int(N_PATHWAYS * scale))]
    for gid in genes:
        nodes[gid] = Node.model_construct(
            id=gid,
            type=NodeType.gene,
            label=f"G{gid[5:]}",
            description=None,
            url=None,
            attrs={"tier": "core"},
            cluster_id=None,
            x=0.0,
            y=0.0,
            centrality=None,
        )
    for pid in pathways:
        nodes[pid] = Node.model_construct(
            id=pid,
            type=NodeType.pathway,
            label=f"pathway {pid}",
            description=None,
            url=None,
            attrs={},
            cluster_id=None,
            x=0.0,
            y=0.0,
            centrality=None,
        )

    edges: list[Edge] = []

    def add(s: str, relation: Relation, t: str, conf: float, **features) -> None:
        edges.append(_edge(f"e_{len(edges):012x}", s, relation, t, conf, **features))

    for did, terms in annotations.items():
        for t, freq in sorted(terms.items()):
            add(did, Relation.has_phenotype, t, 0.9, **({"frequency": freq} if freq else {}))
    gene_load: dict[str, int] = {}
    by_gene: dict[str, list[str]] = {}
    for did in diseases:
        for _ in range(rng.choice((1, 1, 1, 2, 2, 3))):
            gid = rng.choice(genes)
            if gene_load.get(gid, 0) >= 19:
                continue
            gene_load[gid] = gene_load.get(gid, 0) + 1
            by_gene.setdefault(gid, []).append(did)
            add(did, Relation.caused_by_variant_in, gid, rng.choice((0.79, 0.9, 0.97)))
    for members in by_gene.values():
        for a, b in zip(members, members[1:], strict=False):
            add(a, Relation.shared_gene, b, 0.78)
    for _ in range(int(42000 * scale)):
        a, b = rng.sample(diseases, 2)
        add(a, Relation.similar_symptoms, b, round(rng.uniform(0.45, 0.79), 2))
    for pid in pathways:
        for gid in rng.sample(genes, rng.randint(5, 25)):
            add(gid, Relation.participates_in, pid, 0.9)

    store = graph_service.GraphStore(data_version="wide")
    store.nodes = nodes
    store.clusters = {
        f"CLUSTER:{i}": ClusterSummary.model_construct(
            id=f"CLUSTER:{i}",
            label=f"cluster {i}",
            mechanism_summary=None,
            member_count=0,
            attrs={},
        )
        for i in range(134)
    }
    for edge in edges:
        store.edges[edge.id] = edge
        store.incident.setdefault(edge.source_id, []).append(edge.id)
        store.incident.setdefault(edge.target_id, []).append(edge.id)
    for node in nodes.values():
        if node.cluster_id:
            store.members.setdefault(node.cluster_id, []).append(node.id)
    store.degree = {nid: len(store.incident.get(nid, ())) for nid in nodes}
    degrees = sorted(
        d for nid, d in store.degree.items() if nodes[nid].type in graph_service.GENERIC_TYPES
    )
    pct = degrees[min(len(degrees) - 1, int(graph_service.HUB_PERCENTILE * len(degrees)))]
    store.hub_degree = max(graph_service.HUB_MIN_DEGREE, pct)
    store.path_graphs = {
        family: graph_service._path_graph(store, fams)
        for family, fams in graph_service.PATH_FAMILIES.items()
    }
    hubs = sorted(annotated, key=lambda t: -store.degree[t])
    return WideData(store, table, term_rows, hubs, focus, core)
