"""Stage 5: inferred disease-disease edges, mechanism inference, clustering, layout, centrality.

Every inferred edge carries one or more evidence rows that cite the underlying datasets, with a
score-scaled weight (``features.weight``) so strong links can pass the 0.6 threshold and weak
ones do not. The final graph (Stage 4 tables + inferred edges + clusters + layout) is written
to data/graph/final/.
"""

from __future__ import annotations

import bisect
import hashlib
import importlib
import json
import logging
import math
import random
from collections import Counter, defaultdict
from collections.abc import Iterable
from itertools import combinations
from typing import Any

import igraph as ig
import leidenalg
import networkx as nx
import numpy as np
import polars as pl
from backend.phenotype_similarity import (
    SPECIFIC_IC,
    closure,
    frequency_weight,
    phenotype_similarity,
)
from backend.schemas.enums import SYMMETRIC_RELATIONS, ClaimType, EvidenceTier
from pydantic import BaseModel

from pipeline import bio, hpo_sim, taxonomy
from pipeline.build import (
    FINAL,
    STAGE4,
    assign_version,
    content_hash,
    inferred_cap,
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

# Symptom similarity (shared function: backend.phenotype_similarity)
SYM_PREFILTER_K = 25
SYM_TOP_K = 8
SYM_THRESHOLD = 0.45
SYM_MIN_TERMS = 3
SYM_MIN_SHARED_SPECIFIC = 2
SYM_RANDOM_PAIRS = 5000
SYM_CALIBRATION_QUANTILE = 0.95
SYM_CONF_BASE, SYM_CONF_SLOPE, SYM_CONF_MAX = 0.30, 0.55, 0.75
# Mechanism inference from ClinVar
MIN_PATHOGENIC = 5
LOF_TRUNC_SHARE = 0.4
NON_LOF_MAX_TRUNC = 0.05
NON_LOF_MIN_N = 10
# Shared gene without an established mechanism
SHARED_GENE_MAX_DISEASES = 25
SHARED_GENE_FACTOR = 0.85
# Shared pathway
PATHWAY_MAX_GENES = 60
PATHWAY_TOP_K = 5
PATHWAY_FACTOR = 0.8
# Chromosomal proximity (gene <-> gene)
NEAR_MAX_GAP_BP = 1_000_000
NEAR_TOP_K = 3
NEAR_CONFIDENCE = 0.20
NEAR_CNV_CONFIDENCE = 0.45
NEAR_MIN_CNV = 2
# Only focal copy-number variants count for the boost: larger (multi-megabase, whole-arm)
# events span nearly every pair of neighbouring genes and say nothing about a specific pair.
NEAR_CNV_MAX_BP = 1_000_000
# Research overlap
RESEARCH_TOP_K = 6
RESEARCH_SCORE = 0.4
# Clustering layer weights. near_on_chromosome never feeds the clustering, and shared_gene is
# already represented by the same-gene pairs with an unknown mechanism.
CLUSTER_WEIGHTS = {
    "same_gene_same_mechanism": 1.0,
    "shared_gene_unknown_mechanism": 0.5,
    "shared_pathway": 0.4,
    "similar_symptoms": 0.6,
    "shared_researcher": 0.15,
}
CLUSTER_EXCLUDED = frozenset({"near_on_chromosome", "shared_gene"})
LEIDEN_RESOLUTION = 1.0
# The wide core (thousands of diseases) is clustered at a finer resolution.
LEIDEN_RESOLUTION_WIDE = 10.0
WIDE_MIN_DISEASES = 1000
LEIDEN_SEED = 42
FA2_ITERATIONS = 40
# networkx ForceAtlas2 is O(n^2) per iteration: larger core graphs keep the DrL layout only.
FA2_MAX_NODES = 3000

SOURCE_NAMES = {
    "clinvar": "ClinVar",
    "clingen": "ClinGen",
    "hpo": "HPO annotations",
    "orphanet": "Orphanet",
    "mondo": "MONDO",
    "pubmed": "published studies",
    "curated": "curated literature",
}
BASIS_NAMES = {
    "literature": "published studies",
    "orphanet": "Orphanet",
    "clingen_dosage": "ClinGen dosage curation",
    "clinvar": "ClinVar variant types",
}
MECHANISM_PHRASES = {
    "loss_of_function": "loss of function",
    "gain_of_function": "gain of function",
    "dominant_negative": "a dominant-negative effect",
    "non_lof": "mainly missense variants (not loss of function)",
}


def _inferred(
    src,
    tgt,
    rel,
    *,
    score: float,
    explanation: str,
    method: str,
    confidence_basis: str,
    features: dict | None = None,
    cluster_score: float | None = None,
    **kw,
) -> dict:
    """One evidence row of a computed link: tier ``computed``, a hypothesis, with the link's
    score, a one-line explanation, the method and how the confidence was derived. Rows of the
    same link must carry the same score; ``finalize_inferred`` caps it and sets the weights.

    ``cluster_score`` is what the mechanism clustering reads (default: the score). It keeps the
    clustering formulas of earlier builds, which used the uncapped strength of each link."""
    kw.pop("tier", None)
    return assertion(
        src,
        tgt,
        rel,
        origin="inferred",
        tier=EvidenceTier.computed.value,
        claim_type=ClaimType.hypothesis.value,
        features={
            **(features or {}),
            "explanation": explanation,
            "method": method,
            "confidence_basis": confidence_basis,
            "score": round(score, 4),
            "weight": round(score, 4),
            "cluster_score": round(score if cluster_score is None else cluster_score, 4),
        },
        **kw,
    )


def finalize_inferred(rows: list[dict]) -> list[dict]:
    """Cap each link's score at its relation's cap and split it over the link's evidence rows.

    Stage 4 combines evidence rows as 1 - prod(1 - w); each of the k rows of a link gets
    w = 1 - (1 - score)^(1/k), so the merged confidence equals the link's score (the API shows
    computed rows the same way)."""
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for r in rows:
        if r["origin"] != "inferred":
            continue
        a, b = r["source_id"], r["target_id"]
        if r["relation"] in SYMMETRIC_RELATIONS:
            a, b = sorted((a, b))
        groups[(a, r["relation"], b)].append(r)
    for (_, rel, _), items in groups.items():
        cap = inferred_cap(rel)
        score = min(cap, max(r["features"]["score"] for r in items))
        # Stage 4 keeps one row per distinct source (same key as build.merge).
        k = len({(r["tier"], r["source_type"], r["source_ref"], r["quote"]) for r in items})
        share = 1.0 - (1.0 - score) ** (1.0 / k)
        for r in items:
            r["features"]["score"] = round(score, 4)
            r["features"]["weight"] = round(share, 6)
    return rows


def _join(items: list[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _sources(types: list[str]) -> str:
    return _join(sorted({SOURCE_NAMES.get(t, t) for t in types}))


# ---------------------------------------------------------------- symptoms


def graph_disease_terms(edges: pl.DataFrame, known: set[str] | dict) -> dict[str, dict]:
    """Disease -> {HPO term: recorded frequency or None} from the graph's has_phenotype edges
    (the annotations a user can see), limited to terms of the parsed HPO release."""
    out: dict[str, dict[str, float | None]] = defaultdict(dict)
    for d, t, f in (
        edges.filter(pl.col("relation") == "has_phenotype")
        .select("source_id", "target_id", "features")
        .iter_rows()
    ):
        if t not in known:
            continue
        freq = (json.loads(f) if f else {}).get("frequency")
        out[d][t] = freq if isinstance(freq, int | float) else None
    return dict(out)


def similarity_calibration(
    corpus: hpo_sim.Corpus,
    threshold: float,
    in_scope: list[float],
    n_pairs: int = SYM_RANDOM_PAIRS,
    seed: int = LEIDEN_SEED,
    random_scores: list[float] | None = None,
) -> dict[str, Any]:
    """Scores of random disease pairs from the whole annotation corpus, and where the threshold
    falls among them. The threshold actually used is raised to the 95th percentile if needed."""
    pool = sorted(d for d, t in corpus.annotations.items() if len(t) >= SYM_MIN_TERMS)
    rng = random.Random(seed)
    closures = {}
    scores = []
    seen = set()
    while len(scores) < n_pairs and len(pool) > 1:
        a, b = rng.sample(pool, 2)
        key = (min(a, b), max(a, b))
        if key in seen:
            continue
        seen.add(key)
        for d in key:
            if d not in closures:
                closures[d] = closure(corpus.annotations[d], corpus.ancestors)
        scores.append(
            phenotype_similarity(
                corpus.annotations[a],
                corpus.annotations[b],
                corpus.ic,
                corpus.ancestors,
                closures[a],
                closures[b],
            )
        )
    arr = np.array(scores) if scores else np.zeros(1)
    if random_scores is not None:
        random_scores.extend(scores)
    p95 = float(np.quantile(arr, SYM_CALIBRATION_QUANTILE))
    used = max(threshold, round(p95, 4))
    scope_arr = np.array(in_scope) if in_scope else np.zeros(1)
    return {
        "random_pairs": len(scores),
        "random_pool": len(pool),
        "seed": seed,
        "random_p95": round(p95, 4),
        "random_p99": round(float(np.quantile(arr, 0.99)), 4),
        "random_median": round(float(np.median(arr)), 4),
        "design_threshold": threshold,
        "threshold": used,
        "threshold_percentile_random": round(100 * float((arr < used).mean()), 2),
        "in_scope_pairs": len(in_scope),
        "in_scope_pairs_basis": f"cosine top-{SYM_PREFILTER_K} candidates of each disease",
        "threshold_percentile_in_scope": round(100 * float((scope_arr < used).mean()), 2),
    }


def top_k_cap_stats(
    per: dict[int, list[tuple[float, int]]],
    keep: set[tuple[int, int]],
    qualifying: int,
    random_scores: np.ndarray | None,
) -> dict[str, Any]:
    """How much the per-disease top-K cap decides: qualifying pairs (threshold and shared
    specific terms passed) that the cap dropped, and the similarity at which it bites (the
    lowest kept score of each disease that hit the cap), also as a random-pair percentile."""
    capped = [sorted(lst, reverse=True) for lst in per.values() if len(lst) > SYM_TOP_K]
    bite = [lst[SYM_TOP_K - 1][0] for lst in capped]
    med = float(np.median(bite)) if bite else None
    out: dict[str, Any] = {
        "top_k": SYM_TOP_K,
        "qualifying_pairs": qualifying,
        "kept_pairs": len(keep),
        "dropped_by_top_k": qualifying - len(keep),
        "share_decided_by_top_k": round((qualifying - len(keep)) / qualifying, 4)
        if qualifying
        else 0.0,
        "diseases_at_cap": len(capped),
        "cap_bite_similarity_median": round(med, 4) if med is not None else None,
    }
    if med is not None and random_scores is not None:
        out["cap_bite_percentile_random"] = round(100 * float((random_scores < med).mean()), 2)
    return out


def symptom_similarity(
    diseases: list[str],
    dterms: dict[str, dict[str, float | None]],
    corpus: hpo_sim.Corpus,
    version: str | None = None,
    calibrate: bool = True,
) -> tuple[list[dict], dict[str, Any]]:
    """`similar_symptoms` with the shared frequency-weighted IC best-match average."""
    ids = [d for d in diseases if len(dterms.get(d, ())) >= SYM_MIN_TERMS]
    if len(ids) < 2:
        return [], {}
    ic, anc = corpus.ic, corpus.ancestors
    weights = {d: {t: frequency_weight(f) for t, f in dterms[d].items()} for d in ids}
    closures = {d: closure(weights[d], anc) for d in ids}

    def sim(i: int, j: int) -> float:
        a, b = ids[i], ids[j]
        return phenotype_similarity(weights[a], weights[b], ic, anc, closures[a], closures[b])

    # Only the cosine top-K candidates of each disease are scored (all pairs would be
    # n^2 / 2 similarity computations: 27 M for the wide core).
    pairs = hpo_sim.cosine_top_k(
        ids, dterms, SYM_PREFILTER_K, ic_fn=lambda t: ic.get(t, 0.0), ancestors_fn=anc
    )
    all_pairs = {p: sim(*p) for p in sorted(pairs)}
    random_scores: list[float] = []
    cal = (
        similarity_calibration(
            corpus, SYM_THRESHOLD, list(all_pairs.values()), random_scores=random_scores
        )
        if calibrate
        else {"threshold": SYM_THRESHOLD}
    )
    threshold = cal["threshold"]

    def specific(d: str) -> set[str]:
        return {t for t in dterms[d] if ic.get(t, 0.0) >= SPECIFIC_IC}

    per: dict[int, list[tuple[float, int]]] = defaultdict(list)
    qualifying = 0
    for i, j in pairs:
        s = all_pairs[(i, j)]
        if s >= threshold and len(specific(ids[i]) & specific(ids[j])) >= SYM_MIN_SHARED_SPECIFIC:
            qualifying += 1
            per[i].append((s, j))
            per[j].append((s, i))
    keep = set()
    for i, lst in per.items():
        for _s, j in sorted(lst, reverse=True)[:SYM_TOP_K]:
            keep.add((min(i, j), max(i, j)))
    if calibrate:
        cal |= top_k_cap_stats(per, keep, qualifying, np.array(random_scores))
    rows = []
    for i, j in sorted(keep):
        a, b = ids[i], ids[j]
        s = all_pairs[(i, j)]
        sa, sb = specific(a), specific(b)
        shared = sorted(
            sa & sb,
            key=lambda t: (-ic[t] * (weights[a][t] + weights[b][t]), corpus.labels.get(t, t)),
        )
        names = [corpus.labels.get(t, t) for t in shared[:3]]
        explanation = (
            f"Similar symptom profile: both list {_join(names)} ({len(shared)} of "
            f"{len(sa | sb)} specific recorded symptoms in common; the score weighs how often "
            "each occurs). Similar experience, possibly different cause."
        )
        score = min(SYM_CONF_BASE + SYM_CONF_SLOPE * s, SYM_CONF_MAX)
        rows.append(
            _inferred(
                a,
                b,
                "similar_symptoms",
                score=score,
                cluster_score=0.9 * s,
                explanation=explanation,
                method=(
                    "Frequency-weighted best-match average of recorded HPO terms, information "
                    "content from all diseases in the HPO annotations"
                ),
                confidence_basis=(
                    f"0.30 + 0.55 x similarity {s:.2f}, at most 0.75; threshold {threshold:.2f}"
                ),
                source_type="hpo",
                source_ref=f"HPO annotations ({version})" if version else "HPO annotations",
                url="https://hpo.jax.org/data/annotations",
                quote="Recorded for both: "
                + ", ".join(corpus.labels.get(t, t) for t in shared[:8]),
                features={
                    "similarity": round(s, 4),
                    "shared_specific": len(shared),
                    "specific_total": len(sa | sb),
                    "shared_terms": "; ".join(shared[:12]),
                    "n_terms_source": len(dterms[a]),
                    "n_terms_target": len(dterms[b]),
                },
            )
        )
    log.info(
        "similar_symptoms: %d candidate pairs, threshold %.3f, %d edges (calibration %s)",
        len(pairs),
        threshold,
        len(rows),
        json.dumps(cal),
    )
    return rows, cal


# ---------------------------------------------------------------- mechanism


def clinvar_stats(scope: Scope) -> tuple[dict, dict]:
    """Per gene and per (gene, disease): P/LP variant counts and truncating share."""
    try:
        df = bio.clinvar_plp_or_focus()
    except FileNotFoundError:
        return {}, {}
    df = bio.with_scope_genes(df, scope).filter(
        pl.col("classification").is_in(["pathogenic", "likely_pathogenic"])
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


def gene_mechanism_edges(
    scope: Scope, gene_stats: dict, mech_pairs: dict, symbols: dict[str, str] | None = None
) -> list[dict]:
    """acts_via gene -> mechanism inferred from ClinVar (gene level), for focus genes only
    (mechanism nodes belong to the focus set; core pairs still feed the same-gene links)."""
    symbols = symbols or {}
    focus = scope.focus_gene_ids if scope is not None else None
    focus_diseases = scope.focus_disease_ids if scope is not None else None
    retrieved = (raw_record("clinvar", "variant_summary.scope.tsv.gz") or {}).get("retrieved_at")
    rows = []
    for hid, stats in gene_stats.items():
        if focus is not None and hid not in focus:
            continue
        mech, strength = clinvar_label(stats)
        if mech != "loss_of_function":
            continue
        score = 0.45 + 0.4 * strength
        sym = symbols.get(hid, hid)
        rows.append(
            _inferred(
                hid,
                "MECH:loss_of_function",
                "acts_via",
                score=score,
                explanation=(
                    f"{stats['truncating']} of {stats['n_pathogenic']} pathogenic or likely "
                    f"pathogenic ClinVar variants in {sym} are truncating (nonsense, frameshift, "
                    "splice), a pattern that suggests loss of function."
                ),
                method="Share of truncating variants among pathogenic / likely pathogenic ClinVar "
                "variants of the gene (at least 40%, at least 5 variants)",
                confidence_basis=(
                    f"0.45 + 0.4 x strength {strength:.2f} "
                    f"(strength = log10(n + 1) / 2 for n = {stats['n_pathogenic']}, at most 1)"
                ),
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
        if focus is not None and (hid not in focus or mid not in focus_diseases):
            continue
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
    dg: dict[str, set[str]],
    mech: dict,
    symbols: dict[str, str],
    labels: dict[str, str] | None = None,
) -> tuple[list[dict], list[tuple]]:
    """same_gene_same_mechanism / same_gene_different_mechanism; returns rows and unknown pairs."""
    labels = labels or {}
    gene_dis: dict[str, list[str]] = defaultdict(list)
    for d, genes in dg.items():
        for g in genes:
            gene_dis[g].append(d)
    rows, unknown = [], []
    # Sorted genes: a pair linked through several genes keeps the same first row every run.
    for g, ds in sorted(gene_dis.items()):
        if len(ds) > SHARED_GENE_MAX_DISEASES:  # umbrella genes would explode pairs
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
            ka, kb = ma["basis"]["kind"], mb["basis"]["kind"]
            bases = _join(sorted({BASIS_NAMES.get(ka, ka), BASIS_NAMES.get(kb, kb)}))
            pa, pb = MECHANISM_PHRASES[ma["mechanism"]], MECHANISM_PHRASES[mb["mechanism"]]
            if same:
                what = pa if pa == pb else f"{pa} in one and {pb} in the other"
                explanation = (
                    f"Both are linked to variants in {sym}, and the records point to {what} "
                    f"({bases}); a shared mechanism is suggested, not proven."
                )
                method = "Same causal gene with a compatible mechanism recorded for each disease"
            else:
                explanation = (
                    f"Both are linked to variants in {sym}, but the records point to {pa} in "
                    f"{labels.get(a, a)} and {pb} in {labels.get(b, b)} ({bases}); the same gene "
                    "may act differently in them."
                )
                method = "Same causal gene with opposite mechanisms recorded for the two diseases"
            rows.append(
                _inferred(
                    a,
                    b,
                    rel,
                    score=weight,
                    explanation=explanation,
                    method=method,
                    confidence_basis=(
                        "the weaker of the two mechanism records "
                        f"({ma['weight']:.2f}, {mb['weight']:.2f})"
                    ),
                    source_type="analytics",
                    source_ref=f"{sym}: {ka} + {kb}",
                    url=None,
                    quote=(
                        f"{sym} acts via {pa} in one condition and {pb} in the other"
                        if not same
                        else f"{sym}: {pa} recorded for both conditions"
                    ),
                    features={
                        "gene": g,
                        "gene_symbol": sym,
                        "mechanism_source": ma["mechanism"],
                        "mechanism_target": mb["mechanism"],
                        "basis_source": ka,
                        "basis_target": kb,
                    },
                )
            )
    return rows, unknown


def gene_sources(edges: pl.DataFrame, evidence: pl.DataFrame) -> dict[tuple[str, str], dict]:
    """(disease, gene) -> confidence and evidence source types of its caused_by_variant_in."""
    cv = edges.filter(pl.col("relation") == "caused_by_variant_in")
    types: dict[str, set[str]] = defaultdict(set)
    ids = set(cv["id"].to_list())
    for eid, st in evidence.select("edge_id", "source_type").iter_rows():
        if eid in ids:
            types[eid].add(st)
    return {
        (d, g): {"confidence": c, "sources": sorted(types.get(eid, ()))}
        for eid, d, g, c in cv.select("id", "source_id", "target_id", "confidence").iter_rows()
    }


def shared_gene_edges(
    dg: dict[str, set[str]],
    covered: set[tuple[str, str]],
    causal: dict[tuple[str, str], dict],
    symbols: dict[str, str],
) -> list[dict]:
    """`shared_gene`: two diseases linked to the same gene where no same-gene mechanism link
    exists (mechanism unknown or ambiguous). Genes linked to more than 25 diseases are skipped."""
    gene_dis: dict[str, list[str]] = defaultdict(list)
    for d, genes in dg.items():
        for g in genes:
            gene_dis[g].append(d)
    best: dict[tuple[str, str], list[tuple[float, str]]] = defaultdict(list)
    for g, ds in gene_dis.items():
        if len(ds) > SHARED_GENE_MAX_DISEASES:
            continue
        for a, b in combinations(sorted(ds), 2):
            if (a, b) in covered:
                continue
            conf = min(causal[(a, g)]["confidence"], causal[(b, g)]["confidence"])
            best[(a, b)].append((conf * SHARED_GENE_FACTOR, g))
    rows = []
    for (a, b), cands in sorted(best.items()):
        cands.sort(key=lambda c: (-c[0], symbols.get(c[1], c[1])))
        score, g = cands[0]
        sym = symbols.get(g, g)
        sources = _sources(causal[(a, g)]["sources"] + causal[(b, g)]["sources"]) or "curated"
        others = [symbols.get(x, x) for _, x in cands[1:]]
        rows.append(
            _inferred(
                a,
                b,
                "shared_gene",
                score=score,
                explanation=(
                    f"Both are linked to variants in {sym} (sources: {sources}); whether they "
                    "share a mechanism is not established."
                ),
                method="Same causal gene, no compatible or opposite mechanism on record",
                confidence_basis=(
                    "0.85 x the weaker of the two gene-disease links "
                    f"({causal[(a, g)]['confidence']:.2f}, {causal[(b, g)]['confidence']:.2f})"
                ),
                source_type="analytics",
                source_ref=f"{sym}: caused_by_variant_in x2",
                url=None,
                quote=f"Both conditions are linked to variants in {sym}",
                features={
                    "gene": g,
                    "gene_symbol": sym,
                    "n_shared_genes": len(cands),
                    "other_shared_genes": ", ".join(others) if others else None,
                },
            )
        )
    log.info("shared_gene: %d edges", len(rows))
    return rows


def _pathway_weight(n_genes: int) -> float:
    return PATHWAY_FACTOR * 0.9 / (1 + math.log10(n_genes))


def pathway_edges(
    dg: dict[str, set[str]],
    edges: pl.DataFrame,
    nodes: pl.DataFrame,
    symbols: dict[str, str] | None = None,
) -> list[dict]:
    symbols = symbols or {}
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
    # Candidate pairs share at least one pathway (an inverted index instead of all pairs).
    pw_dis: dict[str, list[str]] = defaultdict(list)
    for d in sorted(dis_pw):
        for p in dis_pw[d]:
            pw_dis[p].append(d)
    pairs = {pair for ds in pw_dis.values() for pair in combinations(ds, 2)}
    for a, b in sorted(pairs):
        if dg[a] & dg[b]:
            continue  # same gene is covered by the same-gene relations
        shared = set(dis_pw[a]) & set(dis_pw[b])
        if not shared:
            continue
        ws = sorted((_pathway_weight(sizes[p]), p) for p in shared)[::-1]
        rank = 1 - math.prod(1 - w for w, _ in ws[:5])
        cand.append((rank, a, b, [p for _, p in ws[:8]]))
    per: dict[str, list] = defaultdict(list)
    for c in cand:
        per[c[1]].append(c)
        per[c[2]].append(c)
    keep = {}
    for lst in per.values():
        for c in sorted(lst, reverse=True)[:PATHWAY_TOP_K]:
            keep[(c[1], c[2])] = c
    rows = []
    for (a, b), (_rank, _, _, pws) in sorted(keep.items()):
        cited = pws[:3]
        score = 1 - math.prod(1 - _pathway_weight(sizes[p]) for p in cited)
        top = cited[0]
        genes_a = sorted(symbols.get(g, g) for g in dis_pw[a][top])
        genes_b = sorted(symbols.get(g, g) for g in dis_pw[b][top])
        kind = "Reactome" if top.startswith("REACT:") else "GO"
        more = len(pws) - 1
        explanation = (
            f"Their linked genes {genes_a[0]} and {genes_b[0]} both take part in "
            f"{labels.get(top, top)} ({sizes[top]} genes, {kind})"
            + (f", plus {more} other shared pathway{'s' if more > 1 else ''}." if more else ".")
        )
        feats = {
            "pathway": top,
            "pathway_label": labels.get(top, top),
            "pathway_genes": sizes[top],
            "n_shared_pathways": len(pws),
            "genes_source": ", ".join(sorted(symbols.get(g, g) for p in pws for g in dis_pw[a][p])),
            "genes_target": ", ".join(sorted(symbols.get(g, g) for p in pws for g in dis_pw[b][p])),
        }
        for p in cited:
            src = "reactome" if p.startswith("REACT:") else "go"
            rows.append(
                _inferred(
                    a,
                    b,
                    "shared_pathway",
                    score=score,
                    cluster_score=_pathway_weight(sizes[p]) / PATHWAY_FACTOR,
                    explanation=explanation,
                    method=(
                        "Causal genes in the same small pathway (Reactome or GO, at most 60 "
                        "genes), top 5 pathway links per disease"
                    ),
                    confidence_basis=(
                        "1 - product of (1 - 0.8 x 0.9 / (1 + log10 pathway size)) over the "
                        f"{len(cited)} smallest shared pathways"
                    ),
                    source_type=src,
                    source_ref=p.removeprefix("REACT:"),
                    url=bio.REACTOME_URL.format(p.removeprefix("REACT:"))
                    if src == "reactome"
                    else bio.GO_URL.format(p),
                    quote=f"Causal genes participate in {labels.get(p, p)} ({sizes[p]} genes)",
                    features=dict(feats),
                )
            )
    log.info("shared_pathway: %d candidate pairs, %d kept", len(cand), len(keep))
    return rows


def _gap(a: dict, b: dict) -> int:
    """Base pairs between two gene spans on the same chromosome (0 when they overlap)."""
    return max(0, max(a["start"], b["start"]) - min(a["end"], b["end"]))


def _cytoband_subband(band: str | None) -> bool:
    return bool(band) and "." in band


def _megabases(bp: int) -> str:
    mb = bp / 1_000_000
    return f"{mb:g} Mb" if mb >= 1 else f"{round(bp / 1000):,} kb"


def near_edges(
    genes: dict[str, dict], cnvs: list[dict] | None = None, cnv_max_bp: int = NEAR_CNV_MAX_BP
) -> list[dict]:
    """`near_on_chromosome` between genes: same chromosome, at most 1 Mb between the MANE spans,
    the 3 nearest per gene. Genes without coordinates fall back to the same cytoband sub-band.
    Confidence 0.20, or 0.45 when at least 2 focal pathogenic / likely pathogenic ClinVar
    copy-number variants (or deletions / duplications of 1 kb up to ``cnv_max_bp``) span both
    genes.

    ``genes``: HGNC id -> attrs (symbol, chromosome, start, end, cytoband).
    """
    placed = {
        g: a
        for g, a in genes.items()
        if a.get("chromosome") not in (None, "MT")
        and isinstance(a.get("start"), int)
        and isinstance(a.get("end"), int)
    }
    by_chr: dict[str, list[str]] = defaultdict(list)
    for g, a in placed.items():
        by_chr[a["chromosome"]].append(g)
    pairs: dict[tuple[str, str], int | None] = {}
    for gs in by_chr.values():
        for g in gs:
            near = sorted(
                (_gap(placed[g], placed[h]), h)
                for h in gs
                if h != g and _gap(placed[g], placed[h]) <= NEAR_MAX_GAP_BP
            )
            for gap, h in near[:NEAR_TOP_K]:
                pairs[tuple(sorted((g, h)))] = gap
    unplaced = [
        g
        for g, a in genes.items()
        if g not in placed and a.get("chromosome") != "MT" and _cytoband_subband(a.get("cytoband"))
    ]
    for g in unplaced:
        for h, a in genes.items():
            if h != g and a.get("cytoband") == genes[g]["cytoband"]:
                pairs.setdefault(tuple(sorted((g, h))), None)
    neighbours: dict[str, set[str]] = defaultdict(set)
    for x, y in pairs:
        neighbours[x].add(y)
        neighbours[y].add(x)
    spans: Counter = Counter()
    # Per-chromosome index by start, so each copy-number variant only checks nearby genes.
    starts: dict[str, list[tuple[int, str]]] = {
        c: sorted((placed[g]["start"], g) for g in gs) for c, gs in by_chr.items()
    }
    longest = max((a["end"] - a["start"] for a in placed.values()), default=0)
    for v in cnvs or []:
        idx = starts.get(v.get("chromosome"), [])
        if not idx or v.get("start") is None:
            continue
        stop = v.get("stop") or v["start"]
        if stop - v["start"] + 1 > cnv_max_bp:
            continue
        lo = bisect.bisect_left(idx, (v["start"] - longest, ""))
        hi = bisect.bisect_right(idx, (stop, "~"))
        nearby = {g: placed[g] for _, g in idx[lo:hi]}
        hit = sorted({h for h, _ in bio.spanned_genes(v, nearby)})
        # Only near pairs can be boosted; large variants would otherwise yield huge pair sets.
        hit_set = set(hit)
        for x in hit:
            for y in neighbours.get(x, ()):
                if x < y and y in hit_set:
                    spans[(x, y)] += 1
    rows = []
    for (a, b), gap in sorted(pairs.items()):
        ga, gb = genes[a], genes[b]
        sa, sb = ga.get("symbol") or a, gb.get("symbol") or b
        chrom = ga.get("chromosome") or gb.get("chromosome") or "?"
        ba, bb = ga.get("cytoband"), gb.get("cytoband")
        band = ba if ba == bb or not bb else (bb if not ba else f"{ba} and {bb}")
        n_cnv = spans.get((a, b), 0)
        boosted = n_cnv >= NEAR_MIN_CNV
        if gap is None:
            where = f"both lie in band {band} on chromosome {chrom} (exact positions not available)"
        elif gap == 0:
            where = f"overlap on chromosome {chrom} ({band})"
        elif gap < 1000:
            where = f"lie less than 1 kb apart on chromosome {chrom} ({band})"
        else:
            where = f"lie {round(gap / 1000):,} kb apart on chromosome {chrom} ({band})"
        cnv = (
            f", and {n_cnv} pathogenic or likely pathogenic copy-number changes of at most "
            f"{_megabases(cnv_max_bp)} in ClinVar span both"
            if boosted
            else ""
        )
        explanation = (
            f"{sa} and {sb} {where}{cnv}. Nearby genes can be deleted or duplicated together, "
            "but closeness alone is weak evidence of a shared cause."
        )
        rows.append(
            _inferred(
                a,
                b,
                "near_on_chromosome",
                score=NEAR_CNV_CONFIDENCE if boosted else NEAR_CONFIDENCE,
                explanation=explanation,
                method=(
                    "Gene spans at most 1 Mb apart on NCBI MANE GRCh38 coordinates, 3 nearest "
                    "per gene"
                    if gap is not None
                    else "Same cytoband sub-band (HGNC), no MANE coordinates"
                ),
                confidence_basis=(
                    f"0.45: {n_cnv} pathogenic / likely pathogenic ClinVar copy-number variants "
                    f"of at most {_megabases(cnv_max_bp)} span both genes"
                    if boosted
                    else "fixed 0.20 for proximity alone"
                ),
                source_type="mane" if gap is not None else "hgnc",
                source_ref="MANE.GRCh38.v1.5" if gap is not None else f"cytoband {band}",
                url="https://www.ncbi.nlm.nih.gov/refseq/MANE/" if gap is not None else None,
                quote=None,
                features={
                    "chromosome": chrom,
                    "gap_bp": gap,
                    "cytoband_source": ba,
                    "cytoband_target": bb,
                    "n_spanning_cnv": n_cnv,
                    "basis": "coordinates" if gap is not None else "cytoband",
                },
            )
        )
    log.info(
        "near_on_chromosome: %d edges (%d by cytoband fallback, %d boosted by copy-number "
        "variants; %d genes without MANE coordinates)",
        len(rows),
        sum(1 for g in pairs.values() if g is None),
        sum(1 for r in rows if r["features"]["n_spanning_cnv"] >= NEAR_MIN_CNV),
        len(genes) - len(placed),
    )
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
            n = len(rs)
            rows.append(
                _inferred(
                    x,
                    y,
                    "shared_researcher",
                    score=RESEARCH_SCORE,
                    explanation=(
                        f"{n} researcher{'s' if n > 1 else ''} published papers or held grants "
                        "about both conditions. Shared research attention, not evidence of a "
                        "biological link."
                    ),
                    method="Authors of papers and principal investigators of grants about each "
                    "disease (authors linked to more than 15 diseases left out)",
                    confidence_basis="fixed 0.40 for shared researchers",
                    source_type="pubmed" if pmids else "reporter",
                    source_ref=(pmids or grants or [r])[0],
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{pmids[0].split(':')[1]}/"
                    if pmids
                    else None,
                    quote=None,
                    features={
                        "researcher": r,
                        "works": ", ".join(works),
                        "n_shared_researchers": n,
                    },
                )
            )
    log.info("shared_researcher: %d pairs", len(keep))
    return rows


# ---------------------------------------------------------------- clustering


def cluster_diseases(
    diseases: list[str],
    inferred: list[dict],
    unknown_same_gene: list[tuple],
    resolution: float | None = None,
) -> dict[str, int]:
    if resolution is None:
        resolution = (
            LEIDEN_RESOLUTION_WIDE if len(diseases) >= WIDE_MIN_DISEASES else LEIDEN_RESOLUTION
        )
    idx = {d: i for i, d in enumerate(diseases)}
    pos: dict[tuple[int, int], float] = defaultdict(float)
    neg: dict[tuple[int, int], float] = defaultdict(float)
    best: dict[tuple[str, str, str], float] = {}
    for r in inferred:
        f = r["features"] if isinstance(r["features"], dict) else json.loads(r["features"] or "{}")
        a, b = sorted((r["source_id"], r["target_id"]))
        key = (a, b, r["relation"])
        best[key] = max(best.get(key, 0.0), f.get("cluster_score", f.get("score", 0.0)))
    for (a, b, rel), score in best.items():
        if a not in idx or b not in idx:
            continue
        k = (min(idx[a], idx[b]), max(idx[a], idx[b]))
        if rel in CLUSTER_EXCLUDED:
            continue
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
        g_pos, weights="weight", resolution_parameter=resolution
    )
    p_neg = leidenalg.RBConfigurationVertexPartition(
        g_neg, weights="weight", resolution_parameter=resolution
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


def distinctive_phenotypes(
    members: dict[int, list[str]], dis_ph: dict[str, set[str]], labels: dict[str, str]
) -> dict[int, list[str]]:
    """Per cluster, its HPO terms ranked by how distinctive they are: the share of member
    diseases recording the term x log(1 + clusters / clusters recording it). Terms recorded by
    a single member rank after shared ones in clusters of two or more."""
    per = {c: Counter(p for d in ds for p in dis_ph.get(d, ())) for c, ds in members.items()}
    df = Counter(p for cnt in per.values() for p in cnt)
    n = max(1, len(members))
    out = {}
    for c, cnt in per.items():
        size = len(members[c])

        def key(p: str, cnt=cnt, size=size) -> tuple:
            shared = cnt[p] >= 2 or size == 1
            return (not shared, -(cnt[p] / size) * math.log(1 + n / df[p]), labels.get(p, p))

        out[c] = sorted(cnt, key=key)
    return out


def template_cluster_label(
    members: list[str], phenotype: str | None, gene: str | None, labels: dict[str, str]
) -> str:
    """Cluster name without a model: the most distinctive recorded symptom and the top gene
    ("Ectopic ossification in muscle tissue · ACVR1"); a single disease keeps its own name."""
    if len(members) == 1:
        return labels.get(members[0], members[0])
    parts = [labels.get(x, x) for x in (phenotype, gene) if x]
    if not parts:
        return f"{len(members)} related conditions"
    if not phenotype:
        return f"{parts[0]} disorders"
    return " · ".join(parts)


LINEAGE_MIN_IC = SPECIFIC_IC  # the term a cluster hangs under must be specific


def cluster_lineages(
    members: dict[int, list[str]],
    dis_ph: dict[str, set[str]],
    ranked_ph: dict[int, list[str]],
    ic: dict[str, float],
    parents: dict[str, list[str]],
    hpo_labels: dict[str, str],
) -> dict[int, list[dict]]:
    """Coarse-to-fine groups above each cluster, from HPO: ``[{"id", "label"}, ...]`` from an
    organ system down to the cluster's direct parent group.

    1. Organ system: the direct child of Phenotypic abnormality recorded (through any of its
       descendants) by the most member diseases; ties go to the smallest id.
    2. Anchor term: the cluster's most distinctive phenotype (``distinctive_phenotypes``) that is
       specific (IC >= 2) and lies under that organ system; without one the cluster hangs
       directly under the organ system.
    3. Path: from the anchor up to the organ system through is_a parents under that system,
       preferring the parent shared by the most anchors (then the smallest id), so clusters
       with related anchors share their upper groups.
    Clusters without any recorded phenotype get an empty lineage."""
    anc = taxonomy.ancestor_fn(parents)
    systems = taxonomy.organ_systems(parents)
    chosen: dict[int, tuple[str | None, str | None]] = {}
    for c, ds in sorted(members.items()):
        votes: Counter[str] = Counter()
        for d in ds:
            votes.update({x for p in dis_ph.get(d, ()) for x in (anc(p) | {p}) & systems})
        if not votes:
            chosen[c] = (None, None)
            continue
        system = min(votes, key=lambda x: (-votes[x], x))
        anchor = next(
            (
                p
                for p in ranked_ph.get(c, [])
                if ic.get(p, 0.0) >= LINEAGE_MIN_IC and system in anc(p)
            ),
            None,
        )
        chosen[c] = (system, anchor)
    shared: Counter[str] = Counter()
    for _system, anchor in chosen.values():
        if anchor:
            shared.update(anc(anchor) | {anchor})
    out: dict[int, list[dict]] = {}
    for c, (system, anchor) in chosen.items():
        if system is None:
            out[c] = []
            continue
        chain, cur = [], anchor
        while cur and cur != system:
            chain.append(cur)
            up = [p for p in parents.get(cur, ()) if p == system or system in anc(p)]
            cur = min(up, key=lambda p: (-shared[p], p)) if up else None
        chain.append(system)
        out[c] = [{"id": t, "label": hpo_labels.get(t, t)} for t in reversed(chain)]
    return out


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
    ic: dict[str, float] | None = None,
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
    ranked_ph = distinctive_phenotypes(members, dis_ph, labels)
    hpo_parents, hpo_labels = taxonomy.hpo()
    lineages = cluster_lineages(members, dis_ph, ranked_ph, ic or {}, hpo_parents, hpo_labels)
    mech_by_disease: dict[str, list[dict]] = defaultdict(list)
    for (_g, d), m in sorted(mech.items()):
        mech_by_disease[d].append(m)
    out = []
    for c, ds in sorted(members.items()):
        genes = Counter(g for d in ds for g in dg.get(d, ()))
        pws = cluster_pws[c]
        phs = Counter(p for d in ds for p in dis_ph.get(d, ()))
        mechs = Counter(
            m["mechanism"]
            for d in ds
            for m in mech_by_disease.get(d, ())
            if m["mechanism"] != "non_lof"
        )
        top_genes = [labels.get(g, g) for g in _top(genes, 4, labels)]

        def distinct(p: str, pws=pws) -> tuple[float, str]:
            return (-(pws[p] ** 2) * math.log(1 + n_clusters / df_pw[p]), labels.get(p, p))

        ranked_pw = sorted(pws, key=distinct)
        top_pw = [labels.get(p, p) for p in ranked_pw[:3]]
        top_ph = [labels.get(p, p) for p in _top(phs, 5, labels)]
        distinct_ph = ranked_ph.get(c, [])
        top_gene = _top(genes, 1, labels)
        label = template_cluster_label(
            ds, distinct_ph[0] if distinct_ph else None, top_gene[0] if top_gene else None, labels
        )
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
                        "distinctive_phenotypes": [labels.get(p, p) for p in distinct_ph[:3]],
                        "lineage": lineages.get(c, []),
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
    if not order:
        pos = {}
    elif len(order) > FA2_MAX_NODES:
        log.info("layout: %d core nodes, DrL only (no ForceAtlas2)", len(order))
        pos = init
    else:
        pos = nx.forceatlas2_layout(
            core,
            pos=init,
            max_iter=FA2_ITERATIONS,
            weight="weight",
            scaling_ratio=2.0,
            gravity=1.0,
            seed=LEIDEN_SEED,
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


def embeddings(nodes: pl.DataFrame, only: set[str] | None = None) -> dict[str, list[float]]:
    """Local text embeddings (cached by text hash); ``only`` limits which nodes get one."""
    if only is not None:
        nodes = nodes.filter(pl.col("id").is_in(list(only)))
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


def spanning_variants() -> list[dict]:
    """Pathogenic / likely pathogenic ClinVar variants that can span several genes (copy-number
    variants, deletions and duplications), from the cached in-scope ClinVar file."""
    try:
        df = bio.clinvar_plp_or_focus()
    except FileNotFoundError:
        return []
    return (
        df.filter(
            pl.col("classification").is_in(["pathogenic", "likely_pathogenic"])
            & pl.col("type").str.to_lowercase().is_in(list(bio.SPANNING_TYPES))
        )
        .select("variation_id", "type", "chromosome", "start", "stop", "assembly")
        .unique("variation_id")
        .to_dicts()
    )


HPO_ROOT = "HP:0000001"


def hpo_terms_table(corpus: hpo_sim.Corpus, extra: Iterable[str] = ()) -> pl.DataFrame:
    """Every live HPO term under Phenotypic abnormality (HP:0000118) and that term itself, graph
    node or not: id, label, synonyms, direct is_a parents and the corpus information content
    (null when neither the term nor a descendant annotates any disease). Loaded into the
    ``hpo_terms`` table for symptom matching.

    ``extra``: further terms to include with their ancestors (below the HPO root HP:0000001),
    for phenotype nodes outside HP:0000118 such as clinical-course terms ("Death in infancy")."""
    terms = bio.hpo_terms().filter(~pl.col("deprecated"))
    parents = {hid: list(ps or []) for hid, ps in terms.select("id", "parents").iter_rows()}
    anc = taxonomy.ancestor_fn(parents)
    root = taxonomy.PHENOTYPIC_ABNORMALITY
    wanted = {t for t in extra if t in parents}
    wanted |= {a for t in wanted for a in anc(t)}
    wanted.discard(HPO_ROOT)
    rows = []
    for r in terms.sort("id").iter_rows(named=True):
        hid = r["id"]
        if hid != root and root not in anc(hid) and hid not in wanted:
            continue
        rows.append(
            {
                "id": hid,
                "label": r["label"] or hid,
                "synonyms": sorted({x for x in r["synonyms"] or [] if x and x != r["label"]}),
                "parents": sorted(p for p in parents[hid] if p in parents),
                "ic": round(corpus.ic[hid], 6) if corpus.counts.get(hid) else None,
            }
        )
    schema = {
        "id": pl.String,
        "label": pl.String,
        "synonyms": pl.List(pl.String),
        "parents": pl.List(pl.String),
        "ic": pl.Float64,
    }
    return pl.DataFrame(rows, schema=schema)


def tier_summary(nodes: pl.DataFrame) -> dict[str, dict[str, int]]:
    """Count of focus and core nodes per tiered type."""
    out: dict[str, dict[str, int]] = {}
    for typ, attrs in nodes.select("type", "attrs").iter_rows():
        if typ in ("disease", "gene", "phenotype"):
            tier = (json.loads(attrs) if attrs else {}).get("tier", "focus")
            out.setdefault(typ, {}).setdefault(tier, 0)
            out[typ][tier] += 1
    return out


def inferred_summary(edges: pl.DataFrame) -> dict[str, dict]:
    """Count and confidence range per inferred relation."""
    inf = edges.filter(pl.col("origin") == "inferred")
    return {
        rel: {"edges": n, "confidence_min": round(lo, 4), "confidence_max": round(hi, 4)}
        for rel, n, lo, hi in inf.group_by("relation")
        .agg(
            pl.len(), pl.col("confidence").min().alias("lo"), pl.col("confidence").max().alias("hi")
        )
        .sort("relation")
        .iter_rows()
    }


# ---------------------------------------------------------------- run


async def run() -> dict[str, Any]:
    scope = load_scope()
    base = read_graph(STAGE4)
    edges, nodes, evidence = base["edges"], base["nodes"], base["evidence"]
    diseases = sorted(nodes.filter(pl.col("type") == "disease")["id"].to_list())
    symbols = dict(nodes.filter(pl.col("type") == "gene").select("id", "label").iter_rows())

    labels = dict(nodes.select("id", "label").iter_rows())

    gene_stats, pair_stats = clinvar_stats(scope)
    mech = mechanism_table(edges, evidence, scope, pair_stats)
    dg = disease_genes(edges, 0.6)
    corpus = hpo_sim.corpus()
    hpo_version = (raw_record("hpo", "phenotype.hpoa") or {}).get("source_version")

    inferred: list[dict] = []
    sym_rows, calibration = symptom_similarity(
        diseases, graph_disease_terms(edges, corpus.ic), corpus, hpo_version
    )
    inferred += sym_rows
    inferred += gene_mechanism_edges(scope, gene_stats, mech, symbols)
    same, unknown = same_gene_edges(dg, mech, symbols, labels)
    inferred += same
    covered = {tuple(sorted((r["source_id"], r["target_id"]))) for r in same}
    inferred += shared_gene_edges(dg, covered, gene_sources(edges, evidence), symbols)
    inferred += pathway_edges(dg, edges, nodes, symbols)
    gene_attrs = {
        nid: {**json.loads(a or "{}"), "symbol": symbols.get(nid, nid)}
        for nid, a in nodes.filter(pl.col("type") == "gene").select("id", "attrs").iter_rows()
    }
    inferred += near_edges(gene_attrs, spanning_variants())
    inferred += research_edges(scope)
    finalize_inferred(inferred)
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
    # Embeddings: every focus node (as before) plus every disease; core genes and symptoms
    # have none (vector search treats a missing embedding as a non-match).
    tiered = {"disease", "gene", "phenotype"}
    embed_ids = {
        nid
        for nid, typ in tables["nodes"].select("id", "type").iter_rows()
        if typ == "disease" or typ not in tiered or scope.tier(nid) != "core"
    }
    emb = embeddings(tables["nodes"], embed_ids)

    n = tables["nodes"].join(lay, on="id", how="left")
    n = n.with_columns(
        pl.col("id").replace_strict(ncl, default=None).alias("cluster_id"),
        pl.col("id")
        .replace_strict(emb, default=None, return_dtype=pl.List(pl.Float64))
        .alias("embedding"),
    )
    # Degree goes into attrs so the API can penalize hubs in path search; phenotypes also get
    # their HPO lineage (organ system .. primary parent) for the Atlas symptom tree, and their
    # corpus information content and is_a ancestors for phenotype matching.
    lineage = taxonomy.hpo_lineages(n.filter(pl.col("type") == "phenotype")["id"].to_list())

    types = dict(n.select("id", "type").iter_rows())

    def _attrs(s: dict) -> str:
        a = {**json.loads(s["attrs"]), "degree": s["degree"]}
        if types.get(s["id"]) in tiered:
            # Disease, gene and phenotype nodes: "focus" (literature, people, variants, on the
            # map) or "core" (biology only). Nodes outside the scope file count as focus.
            a["tier"] = scope.tier(s["id"]) or "focus"
        if s["id"] in lineage:
            a["hpo_lineage"] = lineage[s["id"]]
            a["ic"] = round(corpus.ic.get(s["id"], 0.0), 4)
            a["ancestors"] = sorted(corpus.ancestors(s["id"]))
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
    clusters = await label_clusters(membership, tables, mech, version, corpus.ic)
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
    hpo_table = hpo_terms_table(
        corpus, tables["nodes"].filter(pl.col("type") == "phenotype")["id"].to_list()
    )
    hpo_table.write_parquet(FINAL / "hpo_terms.parquet")
    summary = summarize(tables) | {
        "tiers": tier_summary(tables["nodes"]),
        "hpo_terms": hpo_table.height,
        "clusters": len(clusters),
        "data_version": version,
        "information_content": {
            "corpus": "phenotype.hpoa, all diseases (aspect P, NOT and 0% left out)",
            "hpo_annotations_version": hpo_version,
            "n_diseases": corpus.n_diseases,
        },
        "similar_symptoms_calibration": calibration,
        "inferred_by_relation": inferred_summary(tables["edges"]),
    }
    (FINAL / "summary.json").write_text(json.dumps(summary, indent=1))
    log.info("final graph %s", json.dumps(summary))
    for c in clusters:
        log.info("  %s (%d): %s", c["id"], c["member_count"], c["label"])
    return summary
