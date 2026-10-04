"""Stage 5: inferred disease-disease edges, mechanism inference, clustering, layout, centrality.

Every inferred edge carries one or more evidence rows that cite the underlying datasets, with a
score-scaled weight (``features.weight``) so strong links can pass the 0.6 threshold and weak
ones do not. The final graph (Stage 4 tables + inferred edges + clusters + layout) is written
to data/graph/final/.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import math
from collections import Counter, defaultdict
from itertools import combinations
from typing import Any

import igraph as ig
import leidenalg
import networkx as nx
import numpy as np
import polars as pl
from pydantic import BaseModel

from pipeline import bio, hpo_sim, taxonomy
from pipeline.build import (
    FINAL,
    STAGE4,
    assign_version,
    content_hash,
    merge,
    read_graph,
    summarize,
    write_graph,
)
from pipeline.contracts import (
    ASSERTION_SCHEMA,
    Scope,
    assertion,
    load_scope,
    now_iso,
    raw_record,
    read_table,
)
from pipeline.paths import CACHE, GRAPH, SCOPE_FILE

log = logging.getLogger(__name__)

INFERRED = GRAPH / "inferred"

# Symptom similarity
SYM_PREFILTER_K = 25
SYM_TOP_K = 6
SYM_THRESHOLD = 0.45
# Mechanism inference from ClinVar
MIN_PATHOGENIC = 5
LOF_TRUNC_SHARE = 0.4
NON_LOF_MAX_TRUNC = 0.05
NON_LOF_MIN_N = 10
# Shared pathway
PATHWAY_MAX_GENES = 60
PATHWAY_TOP_K = 5
# Research overlap
RESEARCH_TOP_K = 6
# Clustering layer weights
CLUSTER_WEIGHTS = {
    "same_gene_same_mechanism": 1.0,
    "shared_gene_unknown_mechanism": 0.5,
    "shared_pathway": 0.4,
    "similar_symptoms": 0.6,
    "shared_researcher": 0.15,
}
LEIDEN_RESOLUTION = 1.0
LEIDEN_SEED = 42
FA2_ITERATIONS = 40


def _inferred(src, tgt, rel, *, score: float, features: dict, **kw) -> dict:
    return assertion(
        src,
        tgt,
        rel,
        origin="inferred",
        features={**features, "score": round(score, 4), "weight": round(score, 4)},
        **kw,
    )


# ---------------------------------------------------------------- symptoms


def symptom_similarity(diseases: list[str]) -> list[dict]:
    terms = hpo_sim.disease_terms()
    ids = [d for d in diseases if len(terms.get(d, ())) >= 3]
    if len(ids) < 2:
        return []
    cos = hpo_sim.cosine_matrix(ids, ids)
    np.fill_diagonal(cos, -1)
    pairs = set()
    for i in range(len(ids)):
        for j in np.argsort(-cos[i])[:SYM_PREFILTER_K]:
            if cos[i, j] > 0:
                pairs.add((min(i, j), max(i, j)))
    scores: dict[tuple[int, int], float] = {}
    for i, j in pairs:
        scores[(i, j)] = hpo_sim.bma(terms[ids[i]], terms[ids[j]])
    per: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for (i, j), s in scores.items():
        if s >= SYM_THRESHOLD:
            per[i].append((s, j))
            per[j].append((s, i))
    keep = set()
    for i, lst in per.items():
        for _s, j in sorted(lst, reverse=True)[:SYM_TOP_K]:
            keep.add((min(i, j), max(i, j)))
    version = (raw_record("hpo", "phenotype.hpoa") or {}).get("source_version")
    rows = []
    for i, j in sorted(keep):
        a, b = ids[i], ids[j]
        s = scores[(i, j)]
        shared = hpo_sim.shared_terms(terms[a], terms[b])
        for t in shared:
            t["specificity"] = round(hpo_sim.specificity(t["hpo_id"]), 3)
        names = ", ".join(t["label"] for t in shared[:6])
        rows.append(
            _inferred(
                a,
                b,
                "similar_symptoms",
                score=0.9 * s,
                tier="curated_db",
                source_type="hpo",
                source_ref=f"HPO annotations ({version})" if version else "HPO annotations",
                url="https://hpo.jax.org/data/annotations",
                quote=f"Shared phenotypes: {names}" if names else None,
                features={
                    "similarity": round(s, 4),
                    "method": "pyhpo best-match average, Lin, OMIM information content",
                    "shared_terms": shared,
                    "n_terms": [len(terms[a]), len(terms[b])],
                    "note": "similar experience, possibly different cause",
                },
            )
        )
    log.info("similar_symptoms: %d candidate pairs scored, %d edges", len(scores), len(rows))
    return rows


# ---------------------------------------------------------------- mechanism


def clinvar_stats(scope: Scope) -> tuple[dict, dict]:
    """Per gene and per (gene, disease): P/LP variant counts and truncating share."""
    try:
        df = bio.clinvar_variants()
    except FileNotFoundError:
        return {}, {}
    sym2id = {g["symbol"]: g["hgnc_id"] for g in scope.genes}
    df = df.with_columns(
        pl.coalesce(pl.col("hgnc_id"), pl.col("symbol").replace_strict(sym2id, default=None)).alias(
            "hgnc_id"
        )
    ).filter(
        pl.col("hgnc_id").is_in(list(scope.gene_ids))
        & pl.col("classification").is_in(["pathogenic", "likely_pathogenic"])
        & (pl.col("consequence") != "copy_number")
    )
    gene: dict[str, Counter] = defaultdict(Counter)
    pair: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for hid, cons, ph in df.select("hgnc_id", "consequence", "phenotype_ids").iter_rows():
        kind = (
            "truncating"
            if cons in bio.TRUNCATING
            else ("missense" if cons == "missense" else "other")
        )
        gene[hid][kind] += 1
        for mid in bio.clinvar_disease_ids(ph):
            if mid in scope.disease_ids:
                pair[(hid, mid)][kind] += 1

    def summary(c: Counter) -> dict:
        n = sum(c.values())
        return {
            "n_pathogenic": n,
            "truncating": c["truncating"],
            "missense": c["missense"],
            "truncating_share": round(c["truncating"] / n, 3) if n else None,
        }

    return {k: summary(v) for k, v in gene.items()}, {k: summary(v) for k, v in pair.items()}


def clinvar_label(stats: dict | None) -> tuple[str | None, float]:
    """(mechanism, strength) inferred from the truncating share of P/LP variants."""
    if not stats or stats["n_pathogenic"] < MIN_PATHOGENIC:
        return None, 0.0
    share, n = stats["truncating_share"], stats["n_pathogenic"]
    strength = min(1.0, math.log10(n + 1) / 2)  # 10 variants ~0.52, 100 ~1.0
    if share >= LOF_TRUNC_SHARE:
        return "loss_of_function", strength
    if n >= NON_LOF_MIN_N and share <= NON_LOF_MAX_TRUNC:
        return "non_lof", strength  # missense-only: gain of function or dominant negative
    return None, 0.0


def mechanism_table(
    edges: pl.DataFrame, evidence: pl.DataFrame, scope: Scope, pair_stats: dict
) -> dict[tuple[str, str], dict]:
    """Per (gene, disease) mechanism with its basis, strongest source first.

    Order: curated literature (acts_via with features.diseases) > Orphanet LoF/GoF association
    type > ClinGen haploinsufficiency disease > ClinVar truncating-share inference.
    """
    out: dict[tuple[str, str], dict] = {}

    def put(key, mech, basis, weight, rank):
        cur = out.get(key)
        if cur is None or rank < cur["rank"] or (rank == cur["rank"] and weight > cur["weight"]):
            out[key] = {"mechanism": mech, "basis": basis, "weight": weight, "rank": rank}

    ev_by_edge = defaultdict(list)
    for r in evidence.iter_rows(named=True):
        ev_by_edge[r["edge_id"]].append(r)
    for e in edges.filter(pl.col("relation") == "acts_via").iter_rows(named=True):
        f = json.loads(e["features"]) if e["features"] else {}
        mech = e["target_id"].split(":", 1)[1]
        refs = [ev["source_id"] for ev in ev_by_edge[e["id"]] if ev["source_type"] == "pubmed"]
        for d in f.get("diseases", []):
            put(
                (e["source_id"], d),
                mech,
                {"kind": "literature", "refs": refs, "edge_id": e["id"]},
                min(0.9, e["confidence"]),
                0,
            )
        hi = f.get("hi_disease")
        if hi in scope.disease_ids and f.get("clingen_hi_score") == 3:
            put(
                (e["source_id"], hi),
                "loss_of_function",
                {"kind": "clingen_dosage", "refs": ["ClinGen HI score 3"], "edge_id": e["id"]},
                0.85,
                2,
            )
    for e in edges.filter(pl.col("relation") == "caused_by_variant_in").iter_rows(named=True):
        f = json.loads(e["features"]) if e["features"] else {}
        if f.get("mechanism_hint"):
            refs = [
                ev["source_id"] for ev in ev_by_edge[e["id"]] if ev["source_type"] == "orphanet"
            ]
            put(
                (e["target_id"], e["source_id"]),
                f["mechanism_hint"],
                {"kind": "orphanet", "refs": refs, "edge_id": e["id"]},
                0.85,
                1,
            )
    for (hid, mid), stats in pair_stats.items():
        mech, strength = clinvar_label(stats)
        if mech:
            put(
                (hid, mid),
                mech,
                {"kind": "clinvar", "stats": stats},
                round(0.45 + 0.4 * strength, 3),
                3,
            )
    return out


def compatible(a: str, b: str) -> bool | None:
    """True = same mechanism, False = different, None = cannot tell."""
    if a == b:
        return True
    if "non_lof" in (a, b):
        other = b if a == "non_lof" else a
        if other == "loss_of_function":
            return False
        return None  # non-LoF vs GoF/DN: ambiguous
    return False


def gene_mechanism_edges(scope: Scope, gene_stats: dict, mech_pairs: dict) -> list[dict]:
    """acts_via gene -> mechanism inferred from ClinVar (gene level)."""
    retrieved = (raw_record("clinvar", "variant_summary.scope.tsv.gz") or {}).get("retrieved_at")
    rows = []
    for hid, stats in gene_stats.items():
        mech, strength = clinvar_label(stats)
        if mech != "loss_of_function":
            continue
        score = 0.45 + 0.4 * strength
        rows.append(
            _inferred(
                hid,
                "MECH:loss_of_function",
                "acts_via",
                score=score,
                tier="curated_db",
                source_type="clinvar",
                source_ref="variant_summary (P/LP variants)",
                url="https://www.ncbi.nlm.nih.gov/clinvar/",
                retrieved_at=retrieved,
                quote=(
                    f"{stats['truncating']} of {stats['n_pathogenic']} pathogenic/likely "
                    "pathogenic variants are truncating (nonsense, frameshift, canonical splice)"
                ),
                features={"basis": "clinvar_truncating_share", **stats},
            )
        )
    # Pair-level mechanisms (Orphanet, ClinVar) also surface as gene-level acts_via edges.
    for (hid, mid), m in mech_pairs.items():
        if m["mechanism"] == "non_lof" or m["basis"]["kind"] not in ("orphanet",):
            continue
        rows.append(
            assertion(
                hid,
                f"MECH:{m['mechanism']}",
                "acts_via",
                tier="curated_db",
                source_type="orphanet",
                source_ref=";".join(m["basis"]["refs"]) or None,
                url=None,
                quote=f"Orphanet gene-disease association type: {m['mechanism'].replace('_', ' ')}",
                features={"disease": mid},
            )
        )
    return rows


def disease_genes(edges: pl.DataFrame, min_conf: float = 0.0) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for d, g, c in (
        edges.filter(pl.col("relation") == "caused_by_variant_in")
        .select("source_id", "target_id", "confidence")
        .iter_rows()
    ):
        if c >= min_conf:
            out[d].add(g)
    return out


def same_gene_edges(
    dg: dict[str, set[str]], mech: dict, symbols: dict[str, str]
) -> tuple[list[dict], list[tuple]]:
    """same_gene_same_mechanism / same_gene_different_mechanism; returns rows and unknown pairs."""
    gene_dis: dict[str, list[str]] = defaultdict(list)
    for d, genes in dg.items():
        for g in genes:
            gene_dis[g].append(d)
    rows, unknown = [], []
    for g, ds in gene_dis.items():
        if len(ds) > 25:  # grouping genes in umbrella diseases would explode pairs
            ds = [d for d in ds if (g, d) in mech]
        for a, b in combinations(sorted(ds), 2):
            ma, mb = mech.get((g, a)), mech.get((g, b))
            if not ma or not mb:
                unknown.append((a, b, g))
                continue
            same = compatible(ma["mechanism"], mb["mechanism"])
            if same is None:
                unknown.append((a, b, g))
                continue
            rel = "same_gene_same_mechanism" if same else "same_gene_different_mechanism"
            weight = min(ma["weight"], mb["weight"])
            sym = symbols.get(g, g)
            desc = {
                "loss_of_function": "loss of function",
                "gain_of_function": "gain of function",
                "dominant_negative": "dominant negative",
                "non_lof": "missense-only (not loss of function)",
            }
            rows.append(
                _inferred(
                    a,
                    b,
                    rel,
                    score=weight,
                    tier="curated_db",
                    source_type="analytics",
                    source_ref=f"{sym}: {ma['basis']['kind']} + {mb['basis']['kind']}",
                    url=None,
                    quote=(
                        f"{sym} acts via {desc[ma['mechanism']]} in one condition and "
                        f"{desc[mb['mechanism']]} in the other"
                    ),
                    features={
                        "gene": g,
                        "gene_symbol": sym,
                        "mechanisms": {a: ma["mechanism"], b: mb["mechanism"]},
                        "basis": {a: ma["basis"], b: mb["basis"]},
                    },
                )
            )
    return rows, unknown


def pathway_edges(dg: dict[str, set[str]], edges: pl.DataFrame, nodes: pl.DataFrame) -> list[dict]:
    sizes = {}
    for nid, attrs in nodes.filter(pl.col("type") == "pathway").select("id", "attrs").iter_rows():
        sizes[nid] = json.loads(attrs).get("n_genes") or 999
    gene_pw: dict[str, set[str]] = defaultdict(set)
    for g, p in (
        edges.filter(pl.col("relation") == "participates_in")
        .select("source_id", "target_id")
        .iter_rows()
    ):
        if sizes.get(p, 999) <= PATHWAY_MAX_GENES:
            gene_pw[g].add(p)
    labels = dict(nodes.select("id", "label").iter_rows())
    dis_pw: dict[str, dict[str, set[str]]] = {}
    for d, genes in dg.items():
        if len(genes) > 8:
            continue
        m: dict[str, set[str]] = defaultdict(set)
        for g in genes:
            for p in gene_pw.get(g, ()):
                m[p].add(g)
        if m:
            dis_pw[d] = m
    cand = []
    ds = sorted(dis_pw)
    for a, b in combinations(ds, 2):
        if dg[a] & dg[b]:
            continue  # same gene is covered by the same-gene relations
        shared = set(dis_pw[a]) & set(dis_pw[b])
        if not shared:
            continue
        ws = sorted((0.9 / (1 + math.log10(sizes[p])), p) for p in shared)[::-1]
        score = 1 - math.prod(1 - w for w, _ in ws[:5])
        cand.append((score, a, b, [p for _, p in ws[:8]]))
    per: dict[str, list] = defaultdict(list)
    for c in cand:
        per[c[1]].append(c)
        per[c[2]].append(c)
    keep = {}
    for lst in per.values():
        for c in sorted(lst, reverse=True)[:PATHWAY_TOP_K]:
            keep[(c[1], c[2])] = c
    rows = []
    for (a, b), (score, _, _, pws) in sorted(keep.items()):
        for p in pws[:3]:
            w = 0.9 / (1 + math.log10(sizes[p]))
            genes_a, genes_b = sorted(dis_pw[a][p]), sorted(dis_pw[b][p])
            src = "reactome" if p.startswith("REACT:") else "go"
            rows.append(
                _inferred(
                    a,
                    b,
                    "shared_pathway",
                    score=w,
                    tier="curated_db",
                    source_type=src,
                    source_ref=p.removeprefix("REACT:"),
                    url=bio.REACTOME_URL.format(p.removeprefix("REACT:"))
                    if src == "reactome"
                    else bio.GO_URL.format(p),
                    quote=f"Causal genes participate in {labels.get(p, p)} ({sizes[p]} genes)",
                    features={
                        "pathways": [
                            {"id": q, "label": labels.get(q, q), "n_genes": sizes[q]} for q in pws
                        ],
                        "genes": {a: genes_a, b: genes_b},
                        "combined_score": round(score, 4),
                    },
                )
            )
    log.info("shared_pathway: %d candidate pairs, %d kept", len(cand), len(keep))
    return rows


def research_edges(scope: Scope) -> list[dict]:
    """Diseases that share researchers (authors of papers about them, or PIs of their grants)."""
    a = read_table("assertions")
    if a.height == 0:
        return []
    rel = lambda r: a.filter(pl.col("relation") == r).select("source_id", "target_id", "source_ref")  # noqa: E731
    about = defaultdict(set)
    for p, t, _ in rel("about").iter_rows():
        if t in scope.disease_ids:
            about[p].add(t)
    funds = defaultdict(set)
    for g, t, _ in rel("funds_research_on").iter_rows():
        if t in scope.disease_ids:
            funds[g].add(t)
    person: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for r, p, _ in rel("authored").iter_rows():
        for d in about.get(p, ()):
            person[r][d].add(p)
    for r, g, _ in rel("pi_of").iter_rows():
        for d in funds.get(g, ()):
            person[r][d].add(g)
    pair: dict[tuple[str, str], list[tuple[str, list[str]]]] = defaultdict(list)
    for r, dmap in person.items():
        ds = sorted(dmap)
        if len(ds) > 15:
            continue  # very broad authors (consortia) connect everything
        for x, y in combinations(ds, 2):
            pair[(x, y)].append((r, sorted(dmap[x] | dmap[y])[:6]))
    per = defaultdict(list)
    for (x, y), rs in pair.items():
        per[x].append((len(rs), x, y))
        per[y].append((len(rs), x, y))
    keep = set()
    for lst in per.values():
        for _, x, y in sorted(lst, reverse=True)[:RESEARCH_TOP_K]:
            keep.add((x, y))
    rows = []
    for x, y in sorted(keep):
        rs = pair[(x, y)]
        for r, works in rs[:5]:
            pmids = [w for w in works if w.startswith("PMID:")]
            grants = [w for w in works if w.startswith("GRANT:")]
            rows.append(
                _inferred(
                    x,
                    y,
                    "shared_researcher",
                    score=0.4,
                    tier="peer_reviewed" if pmids else "curated_db",
                    source_type="pubmed" if pmids else "reporter",
                    source_ref=(pmids or grants or [r])[0],
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{pmids[0].split(':')[1]}/"
                    if pmids
                    else None,
                    quote=None,
                    features={"researcher": r, "works": works, "n_shared_researchers": len(rs)},
                )
            )
    log.info("shared_researcher: %d pairs", len(keep))
    return rows


# ---------------------------------------------------------------- clustering


def cluster_diseases(
    diseases: list[str], inferred: list[dict], unknown_same_gene: list[tuple]
) -> dict[str, int]:
    idx = {d: i for i, d in enumerate(diseases)}
    pos: dict[tuple[int, int], float] = defaultdict(float)
    neg: dict[tuple[int, int], float] = defaultdict(float)
    best: dict[tuple[str, str, str], float] = {}
    for r in inferred:
        f = r["features"] if isinstance(r["features"], dict) else json.loads(r["features"] or "{}")
        a, b = sorted((r["source_id"], r["target_id"]))
        key = (a, b, r["relation"])
        best[key] = max(best.get(key, 0.0), f.get("score", 0.0))
    for (a, b, rel), score in best.items():
        if a not in idx or b not in idx:
            continue
        k = (min(idx[a], idx[b]), max(idx[a], idx[b]))
        if rel == "same_gene_different_mechanism":
            neg[k] += 2.0 * score
        elif rel in CLUSTER_WEIGHTS:
            pos[k] += CLUSTER_WEIGHTS[rel] * score
    for a, b, _ in unknown_same_gene:
        if a in idx and b in idx:
            k = (min(idx[a], idx[b]), max(idx[a], idx[b]))
            pos[k] += CLUSTER_WEIGHTS["shared_gene_unknown_mechanism"]
    for k in neg:
        pos.pop(k, None)  # a different-mechanism pair never pulls together
    n = len(diseases)
    g_pos = ig.Graph(n=n, edges=list(pos), edge_attrs={"weight": list(pos.values())})
    g_neg = ig.Graph(n=n, edges=list(neg), edge_attrs={"weight": list(neg.values())})
    p_pos = leidenalg.RBConfigurationVertexPartition(
        g_pos, weights="weight", resolution_parameter=LEIDEN_RESOLUTION
    )
    p_neg = leidenalg.RBConfigurationVertexPartition(
        g_neg, weights="weight", resolution_parameter=LEIDEN_RESOLUTION
    )
    opt = leidenalg.Optimiser()
    opt.set_rng_seed(LEIDEN_SEED)
    opt.optimise_partition_multiplex([p_pos, p_neg], layer_weights=[1, -1], n_iterations=-1)
    membership = list(p_pos.membership)
    # Hard constraint: no community may hold a different-mechanism pair. Move the offending
    # disease to the compatible community it is most strongly tied to (or a new one).
    neg_of: dict[int, set[int]] = defaultdict(set)
    for i, j in neg:
        neg_of[i].add(j)
        neg_of[j].add(i)
    pos_of: dict[int, dict[int, float]] = defaultdict(dict)
    for (i, j), w in pos.items():
        pos_of[i][j] = w
        pos_of[j][i] = w
    for i, j in sorted(neg):
        if membership[i] != membership[j]:
            continue
        mover = j if len(pos_of[j]) <= len(pos_of[i]) else i
        banned = {membership[k] for k in neg_of[mover]}
        ties: dict[int, float] = defaultdict(float)
        for k, w in pos_of[mover].items():
            if membership[k] not in banned:
                ties[membership[k]] += w
        membership[mover] = max(ties, key=ties.get) if ties else max(membership) + 1
    # Renumber by size (largest = 1).
    sizes = Counter(membership)
    order = {
        c: k + 1 for k, (c, _) in enumerate(sorted(sizes.items(), key=lambda kv: (-kv[1], kv[0])))
    }
    return {d: order[membership[i]] for d, i in idx.items()}


def _top(counter: Counter, n: int, labels: dict[str, str]) -> list[str]:
    """most_common with a deterministic tie-break on the label."""
    return sorted(counter, key=lambda k: (-counter[k], labels.get(k, k)))[:n]


class ClusterLabel(BaseModel):
    label: str
    mechanism_summary: str


def _get_llm():
    try:
        return importlib.import_module("pipeline.llm").get_llm()
    except Exception:  # noqa: BLE001
        return None


async def label_clusters(
    membership: dict[str, int],
    tables: dict[str, pl.DataFrame],
    mech: dict,
    data_version: str,
) -> list[dict]:
    nodes, edges = tables["nodes"], tables["edges"]
    labels = dict(nodes.select("id", "label").iter_rows())
    dg = disease_genes(edges, 0.6)
    gene_pw: dict[str, set[str]] = defaultdict(set)
    for g, p in (
        edges.filter(pl.col("relation") == "participates_in")
        .select("source_id", "target_id")
        .iter_rows()
    ):
        gene_pw[g].add(p)
    dis_ph: dict[str, set[str]] = defaultdict(set)
    for d, p in (
        edges.filter(pl.col("relation") == "has_phenotype")
        .select("source_id", "target_id")
        .iter_rows()
    ):
        dis_ph[d].add(p)
    members: dict[int, list[str]] = defaultdict(list)
    for d, c in membership.items():
        members[c].append(d)
    llm = _get_llm()
    # Pathways are ranked by how distinctive they are for a cluster (count x inverse frequency
    # across clusters), so ubiquitous channel pathways do not label every cluster.
    cluster_pws = {
        c: Counter(p for g in {g for d in ds for g in dg.get(d, ())} for p in gene_pw.get(g, ()))
        for c, ds in members.items()
    }
    df_pw = Counter(p for cnt in cluster_pws.values() for p in cnt)
    n_clusters = max(1, len(members))
    out = []
    for c, ds in sorted(members.items()):
        genes = Counter(g for d in ds for g in dg.get(d, ()))
        pws = cluster_pws[c]
        phs = Counter(p for d in ds for p in dis_ph.get(d, ()))
        mechs = Counter(
            m["mechanism"] for (g, d), m in mech.items() if d in ds and m["mechanism"] != "non_lof"
        )
        top_genes = [labels.get(g, g) for g in _top(genes, 4, labels)]

        def distinct(p: str, pws=pws) -> tuple[float, str]:
            return (-(pws[p] ** 2) * math.log(1 + n_clusters / df_pw[p]), labels.get(p, p))

        ranked_pw = sorted(pws, key=distinct)
        top_pw = [labels.get(p, p) for p in ranked_pw[:3]]
        top_ph = [labels.get(p, p) for p in _top(phs, 5, labels)]
        if len(ds) == 1:
            label = labels.get(ds[0], ds[0])
        elif top_genes:
            label = f"{', '.join(top_genes[:3])} disorders"
            if top_pw and pws[ranked_pw[0]] > 1:
                label += f" · {top_pw[0]}"
        else:
            label = f"{top_ph[0]} spectrum" if top_ph else f"Cluster {c}"
        if mechs:
            m = _top(mechs, 1, {})[0]
            k = mechs[m]
            summary = (
                f"Mostly {m.replace('_', ' ')} ({k} of {sum(mechs.values())} gene-disease pairs "
                f"with a known mechanism)"
            )
        else:
            summary = "Mechanism not established for the member diseases"
        origin = "template"
        if llm is not None and len(ds) > 1:
            try:
                res = await llm.structured(
                    ClusterLabel,
                    instructions=(
                        "Name a cluster of rare diseases in at most 8 words for patients and "
                        "researchers, based only on the given shared genes, pathways, mechanisms "
                        "and phenotypes. Then summarize the shared mechanism in one sentence, "
                        "without claims beyond the data."
                    ),
                    input=json.dumps(
                        {
                            "diseases": [labels.get(d, d) for d in ds][:15],
                            "genes": top_genes,
                            "pathways": top_pw,
                            "mechanisms": dict(mechs),
                            "phenotypes": top_ph,
                        }
                    ),
                )
                label, summary, origin = res.label, res.mechanism_summary, "llm"
            except Exception as exc:  # noqa: BLE001
                log.warning("cluster %d: LLM label failed (%s); using template", c, exc)
        out.append(
            {
                "id": f"CLUSTER:{c}",
                "label": label,
                "mechanism_summary": summary,
                "member_count": len(ds),
                "attrs": json.dumps(
                    {
                        "inferred": True,
                        "label_origin": origin,
                        "members": sorted(ds),
                        "top_genes": top_genes,
                        "top_pathways": top_pw,
                        "top_phenotypes": top_ph,
                        "mechanisms": dict(mechs),
                    }
                ),
                "data_version": data_version,
            }
        )
    return out


# ---------------------------------------------------------------- layout / centrality / embeddings


LAYOUT_CORE_TYPES = {
    "disease",
    "gene",
    "mechanism",
    "pathway",
    "phenotype",
    "trial",
    "grant",
    "patient_org",
    "registry",
    "network",
}


def layout_and_centrality(nodes: pl.DataFrame, edges: pl.DataFrame) -> pl.DataFrame:
    """ForceAtlas2 positions and PageRank centrality for every node.

    networkx's ForceAtlas2 is O(n^2) per iteration, so it runs on the core graph (biology and
    community nodes), seeded with igraph's DrL layout; leaves (variants, papers, people,
    institutions) are then placed around their already placed neighbours.
    """
    g = nx.Graph()
    g.add_nodes_from(nodes["id"].to_list())
    for s, t, c in edges.select("source_id", "target_id", "confidence").iter_rows():
        w = max(c, 0.05)
        if g.has_edge(s, t):
            g[s][t]["weight"] = max(g[s][t]["weight"], w)
        else:
            g.add_edge(s, t, weight=w)
    types = dict(nodes.select("id", "type").iter_rows())
    core = g.subgraph([n for n in g.nodes if types.get(n) in LAYOUT_CORE_TYPES]).copy()
    order = list(core.nodes)
    index = {n: i for i, n in enumerate(order)}
    ig_g = ig.Graph(n=len(order), edges=[(index[a], index[b]) for a, b in core.edges])
    ig_g.es["weight"] = [core[a][b]["weight"] for a, b in core.edges]
    import random

    random.seed(LEIDEN_SEED)
    coords = np.array(ig_g.layout_drl(weights="weight").coords) if order else np.zeros((0, 2))
    if len(order):
        coords = (coords - coords.mean(axis=0)) / (np.ptp(coords, axis=0).max() or 1) * 100
    init = {n: coords[index[n]] for n in order}
    pos = (
        nx.forceatlas2_layout(
            core,
            pos=init,
            max_iter=FA2_ITERATIONS,
            weight="weight",
            scaling_ratio=2.0,
            gravity=1.0,
            seed=LEIDEN_SEED,
        )
        if order
        else {}
    )
    pos = {n: np.asarray(p, dtype=float) for n, p in pos.items()}
    spread = float(np.std(np.array(list(pos.values())))) if pos else 1.0
    rng = np.random.default_rng(LEIDEN_SEED)
    pending = [n for n in g.nodes if n not in pos]
    while pending:
        progressed = []
        for n in pending:
            placed = [pos[m] for m in g.neighbors(n) if m in pos]
            if placed:
                angle = rng.uniform(0, 2 * np.pi)
                r = 0.04 * spread * rng.uniform(0.5, 1.0)
                pos[n] = np.mean(placed, axis=0) + r * np.array([np.cos(angle), np.sin(angle)])
                progressed.append(n)
        if not progressed:
            for n in pending:
                pos[n] = rng.normal(0, spread, 2)
            break
        done = set(progressed)
        pending = [n for n in pending if n not in done]
    pr = nx.pagerank(g, weight="weight")
    top = max(pr.values()) if pr else 1
    ids = list(g.nodes)
    xs = np.array([pos[n][0] for n in ids])
    ys = np.array([pos[n][1] for n in ids])
    span = max(np.ptp(xs), np.ptp(ys)) or 1
    cx, cy = xs.mean(), ys.mean()
    return pl.DataFrame(
        {
            "id": ids,
            "x": [float((x - cx) / span * 1000) for x in xs],
            "y": [float((y - cy) / span * 1000) for y in ys],
            "centrality": [pr[n] / top for n in ids],
            "degree": [g.degree(n) for n in ids],
        }
    )


def node_clusters(
    membership: dict[str, int], edges: pl.DataFrame, nodes: pl.DataFrame
) -> dict[str, str]:
    """Disease clusters propagate to genes, variants, phenotypes and pathways by majority."""
    out = {d: f"CLUSTER:{c}" for d, c in membership.items()}
    votes: dict[str, Counter] = defaultdict(Counter)
    for s, t, rel in edges.select("source_id", "target_id", "relation").iter_rows():
        if rel == "caused_by_variant_in" and s in membership:
            votes[t][out[s]] += 1
        elif rel == "has_phenotype" and s in membership:
            votes[t][out[s]] += 1
    gene_c = {g: _top(v, 1, {})[0] for g, v in votes.items()}
    out.update({k: v for k, v in gene_c.items() if k not in out})
    for s, t, rel in edges.select("source_id", "target_id", "relation").iter_rows():
        if rel == "variant_of" and t in out:
            out.setdefault(s, out[t])
        elif rel == "participates_in" and s in out:
            votes[t][out[s]] += 1
    for k, v in votes.items():
        out.setdefault(k, _top(v, 1, {})[0])
    return out


def embeddings(nodes: pl.DataFrame) -> dict[str, list[float]]:
    try:
        from backend.embeddings import embed_texts
    except Exception:  # noqa: BLE001
        log.warning("backend.embeddings unavailable; nodes get no embedding")
        return {}
    texts = {
        nid: f"{label}. {desc}" if desc else label
        for nid, label, desc in nodes.select("id", "label", "description").iter_rows()
    }
    cache_file = CACHE / "embeddings.parquet"
    cached: dict[str, list[float]] = {}
    if cache_file.exists():
        cached = {h: v for h, v in pl.read_parquet(cache_file).iter_rows()}
    keyed = {nid: hashlib.sha1(t.encode()).hexdigest() for nid, t in texts.items()}
    todo = sorted({h: texts[nid] for nid, h in keyed.items() if h not in cached}.items())
    if todo:
        log.info("embedding %d node texts locally", len(todo))
        vecs = embed_texts([t[:2000] for _, t in todo])
        for (h, _), v in zip(todo, vecs, strict=True):
            cached[h] = [float(x) for x in v]
        pl.DataFrame({"hash": list(cached), "vec": list(cached.values())}).write_parquet(cache_file)
    return {nid: cached[h] for nid, h in keyed.items()}


def sync_scope_version(version: str) -> None:
    """scope.json carries the data_version of the graph built from it."""
    data = json.loads(SCOPE_FILE.read_text())
    if data.get("data_version") != version:
        data["data_version"] = version
        SCOPE_FILE.write_text(json.dumps(data, indent=1))


def cluster_nodes(clusters: list[dict], nodes: pl.DataFrame) -> pl.DataFrame:
    """One `cluster` node per cluster (no edges; members point at it via cluster_id)."""
    pos = (
        nodes.filter(pl.col("type") == "disease")
        .group_by("cluster_id")
        .agg(pl.col("x").mean(), pl.col("y").mean())
    )
    xy = {c: (x, y) for c, x, y in pos.iter_rows()}
    rows = []
    for c in clusters:
        x, y = xy.get(c["id"], (None, None))
        rows.append(
            {
                "id": c["id"],
                "type": "cluster",
                "label": c["label"],
                "description": c["mechanism_summary"],
                "url": None,
                "attrs": c["attrs"],
                "x": x,
                "y": y,
                "centrality": None,
                "cluster_id": c["id"],
                "embedding": None,
            }
        )
    schema = {k: nodes.schema[k] for k in nodes.columns}
    return pl.DataFrame(rows, schema=schema) if rows else nodes.clear()


# ---------------------------------------------------------------- run


async def run() -> dict[str, Any]:
    scope = load_scope()
    base = read_graph(STAGE4)
    edges, nodes, evidence = base["edges"], base["nodes"], base["evidence"]
    diseases = sorted(nodes.filter(pl.col("type") == "disease")["id"].to_list())
    symbols = dict(nodes.filter(pl.col("type") == "gene").select("id", "label").iter_rows())

    gene_stats, pair_stats = clinvar_stats(scope)
    mech = mechanism_table(edges, evidence, scope, pair_stats)
    dg = disease_genes(edges, 0.6)

    inferred: list[dict] = []
    inferred += symptom_similarity(diseases)
    inferred += gene_mechanism_edges(scope, gene_stats, mech)
    same, unknown = same_gene_edges(dg, mech, symbols)
    inferred += same
    inferred += pathway_edges(dg, edges, nodes)
    inferred += research_edges(scope)
    retrieved = now_iso()
    for r in inferred:
        r["retrieved_at"] = r.get("retrieved_at") or retrieved
    inferred_df = pl.DataFrame(
        [
            {
                c: (json.dumps(r[c], sort_keys=True) if isinstance(r[c], dict) else r[c])
                for c in ASSERTION_SCHEMA
            }
            for r in inferred
        ],
        schema=ASSERTION_SCHEMA,
    )
    INFERRED.mkdir(parents=True, exist_ok=True)
    inferred_df.write_parquet(INFERRED / "assertions.parquet")

    all_assertions = pl.concat([read_table("assertions").drop("_source"), inferred_df])
    tables = merge(read_table("nodes"), read_table("synonyms"), all_assertions)

    membership = cluster_diseases(
        sorted(tables["nodes"].filter(pl.col("type") == "disease")["id"].to_list()),
        inferred,
        unknown,
    )
    lay = layout_and_centrality(tables["nodes"], tables["edges"])
    ncl = node_clusters(membership, tables["edges"], tables["nodes"])
    emb = embeddings(tables["nodes"])

    n = tables["nodes"].join(lay, on="id", how="left")
    n = n.with_columns(
        pl.col("id").replace_strict(ncl, default=None).alias("cluster_id"),
        pl.col("id")
        .replace_strict(emb, default=None, return_dtype=pl.List(pl.Float64))
        .alias("embedding"),
    )
    # Degree goes into attrs so the API can penalize hubs in path search; phenotypes also get
    # their HPO lineage (organ system .. primary parent) for the Atlas symptom tree.
    lineage = taxonomy.hpo_lineages(n.filter(pl.col("type") == "phenotype")["id"].to_list())

    def _attrs(s: dict) -> str:
        a = {**json.loads(s["attrs"]), "degree": s["degree"]}
        if s["id"] in lineage:
            a["hpo_lineage"] = lineage[s["id"]]
        return json.dumps(a, sort_keys=True)

    n = n.with_columns(
        pl.struct("id", "attrs", "degree")
        .map_elements(_attrs, return_dtype=pl.String)
        .alias("attrs")
    ).drop("degree")
    tables["nodes"] = n
    digest = content_hash(
        {k: v for k, v in tables.items() if k != "nodes"}
        | {"nodes": n.drop("embedding", "x", "y", "centrality")}
    )
    version = assign_version(digest)
    sync_scope_version(version)
    clusters = await label_clusters(membership, tables, mech, version)
    tables["clusters"] = pl.DataFrame(clusters)
    tables["nodes"] = pl.concat(
        [tables["nodes"], cluster_nodes(clusters, tables["nodes"])], how="vertical_relaxed"
    )
    for k in ("nodes", "edges", "clusters"):
        tables[k] = tables[k].with_columns(pl.lit(version).alias("data_version"))
    tables["mechanisms"] = pl.DataFrame(
        [
            {
                "gene_id": g,
                "disease_id": d,
                "mechanism": m["mechanism"],
                "basis": json.dumps(m["basis"]),
                "weight": m["weight"],
            }
            for (g, d), m in sorted(mech.items())
        ]
    )
    write_graph(tables, FINAL)
    summary = summarize(tables) | {"clusters": len(clusters), "data_version": version}
    (FINAL / "summary.json").write_text(json.dumps(summary, indent=1))
    log.info("final graph %s", json.dumps(summary))
    for c in clusters:
        log.info("  %s (%d): %s", c["id"], c["member_count"], c["label"])
    return summary
