"""Stage 0: resolve seeds.yaml into data/scope/scope.json (genes, diseases, phenotypes)."""

from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from datetime import date
from typing import Any

import numpy as np
import polars as pl
import yaml

from pipeline import bio, hpo_sim
from pipeline.paths import SCOPE_FILE, SEEDS_FILE

log = logging.getLogger(__name__)


def load_seeds() -> dict[str, Any]:
    return yaml.safe_load(SEEDS_FILE.read_text())


def disease_index() -> dict[str, list[str]]:
    """Lower-cased label / exact synonym -> MONDO ids (labels listed first)."""
    terms = bio.mondo_terms().filter(~pl.col("deprecated"))
    idx: dict[str, list[str]] = defaultdict(list)
    for mid, label, syns in terms.select("id", "label", "exact_synonyms").iter_rows():
        if label:
            idx[label.lower()].insert(0, mid)
        for s in syns:
            if mid not in idx[s.lower()]:
                idx[s.lower()].append(mid)
    return idx


def resolve_disease(name: str, index: dict[str, list[str]] | None = None) -> str | None:
    name = name.strip()
    if name.upper().startswith("MONDO:"):
        return name.upper()
    hits = (index or disease_index()).get(name.lower(), [])
    return hits[0] if hits else None


def next_version(previous: str | None, content_hash: str, previous_hash: str | None) -> str:
    """YYYY-MM-DD.N: unchanged content keeps its version, otherwise N increments per day."""
    today = date.today().isoformat()
    if previous and previous_hash == content_hash:
        return previous
    if previous and previous.startswith(today + "."):
        return f"{today}.{int(previous.split('.')[-1]) + 1}"
    return f"{today}.1"


def expand(
    seed_diseases: set[str],
    seed_genes: set[str],
    gd: pl.DataFrame,
    cfg: dict[str, Any],
    pathway_genes: dict[str, set[str]] | None = None,
    hpo_scores=None,
    eligible=None,
) -> dict[str, dict[str, Any]]:
    """Breadth-first expansion over the disease graph (shared gene, shared pathway, HPO).

    Returns {mondo_id: {"hop": n, "via": reason, "score": s}}. ``hpo_scores(frontier, pool)``
    returns a (len(frontier), len(pool)) similarity matrix. ``eligible(mondo_id)`` filters every
    non-seed disease (rarity and breadth rules).
    """
    eligible = eligible or (lambda _mid: True)
    disease_genes: dict[str, set[str]] = defaultdict(set)
    gene_diseases: dict[str, set[str]] = defaultdict(set)
    for mid, hid in gd.select("mondo_id", "hgnc_id").iter_rows():
        disease_genes[mid].add(hid)
        gene_diseases[hid].add(mid)
    max_expand = cfg.get("expand_max_genes_per_disease", 8)
    via = set(cfg.get("via", ["shared_gene", "shared_pathway", "hpo_similarity"]))
    caps = cfg.get("max_new_per_hop", [120, 60])
    max_diseases = cfg.get("max_diseases", 250)

    scope: dict[str, dict[str, Any]] = {}
    for mid in seed_diseases:
        scope[mid] = {"hop": 0, "via": "seed", "score": 1.0}
    for g in seed_genes:
        for mid in gene_diseases.get(g, ()):
            if eligible(mid):
                scope.setdefault(mid, {"hop": 0, "via": f"seed gene {g}", "score": 1.0})
    frontier = set(scope)

    gene_pathways: dict[str, set[str]] = defaultdict(set)
    for pid, genes in (pathway_genes or {}).items():
        for g in genes:
            gene_pathways[g].add(pid)

    for hop in range(1, cfg.get("max_hops", 2) + 1):
        if len(scope) >= max_diseases or not frontier:
            break
        cand: dict[str, tuple[float, str]] = {}

        def offer(mid: str, score: float, reason: str, cand=cand) -> None:
            if mid in scope or not eligible(mid):
                return
            if mid not in cand or cand[mid][0] < score:
                cand[mid] = (score, reason)

        expanding = [d for d in frontier if len(disease_genes.get(d, ())) <= max_expand]
        if "shared_gene" in via:
            for d in expanding:
                for g in disease_genes.get(d, ()):
                    for d2 in gene_diseases.get(g, ()):
                        offer(d2, 1.0, f"shared gene {g} with {d}")
        if "shared_pathway" in via and pathway_genes:
            for d in expanding:
                for g in disease_genes.get(d, ()):
                    for pid in gene_pathways.get(g, ()):
                        for g2 in pathway_genes[pid] - {g}:
                            for d2 in gene_diseases.get(g2, ()):
                                if len(disease_genes.get(d2, ())) <= max_expand:
                                    offer(d2, 0.5, f"shared pathway {pid} with {d}")
        if "hpo_similarity" in via and hpo_scores is not None:
            pool = [d for d in hpo_sim.disease_terms() if d not in scope and eligible(d)]
            front = sorted(frontier)
            if pool and front:
                sims = hpo_scores(front, pool)
                thr = cfg.get("hpo_threshold", 0.55)
                k = cfg.get("hpo_top_k_per_disease", 5)
                for i, d in enumerate(front):
                    top = np.argsort(-sims[i])[:k]
                    for j in top:
                        if sims[i, j] >= thr:
                            offer(pool[j], float(sims[i, j]), f"similar phenotype to {d}")
        # Phenotype coherence: candidates must resemble a hop-0 disease (when annotated), so
        # shared housekeeping pathways or pleiotropic genes do not drag in unrelated diseases.
        min_coh = cfg.get("min_coherence", 0.25)
        if hpo_scores is not None and cand and min_coh > 0:
            annotated = hpo_sim.disease_terms()
            core = sorted(d for d, v in scope.items() if v["hop"] == 0 and d in annotated)
            check = sorted(d for d in cand if d in annotated)
            if core and check:
                best = hpo_scores(check, core).max(axis=1)
                for d, b in zip(check, best, strict=True):
                    if b < min_coh:
                        del cand[d]
            for d in [
                d for d in cand if d not in annotated and not cand[d][1].startswith("shared gene")
            ]:
                del cand[d]
        cap = caps[min(hop - 1, len(caps) - 1)]
        room = max_diseases - len(scope)
        ranked = sorted(cand.items(), key=lambda kv: (-kv[1][0], kv[0]))[: min(cap, room)]
        frontier = set()
        for mid, (score, reason) in ranked:
            scope[mid] = {"hop": hop, "via": reason, "score": round(score, 3)}
            frontier.add(mid)
        log.info("hop %d: %d candidates, %d added", hop, len(cand), len(ranked))
    return scope


def eligibility(cfg: dict[str, Any], seeds: set[str]):
    """Rule-based filter for non-seed diseases: rare (MONDO rare subset or an Orphanet entry)
    and not a broad parent term (too many MONDO descendants)."""
    terms = bio.mondo_terms().filter(~pl.col("deprecated"))
    children: dict[str, list[str]] = defaultdict(list)
    rare: set[str] = set()
    for mid, parents, is_rare, matches in terms.select(
        "id", "parents", "rare", "exact_matches"
    ).iter_rows():
        for p in parents:
            children[p].append(mid)
        if is_rare or any(m.startswith("ORPHA:") for m in matches):
            rare.add(mid)
    max_desc = cfg.get("max_descendants", 30)
    require_rare = cfg.get("require_rare", True)
    cache: dict[str, int] = {}

    def n_desc(mid: str) -> int:
        if mid not in cache:
            seen, stack = set(), list(children.get(mid, ()))
            while stack and len(seen) <= max_desc:
                c = stack.pop()
                if c not in seen:
                    seen.add(c)
                    stack.extend(children.get(c, ()))
            cache[mid] = len(seen)
        return cache[mid]

    def ok(mid: str) -> bool:
        if mid in seeds:
            return True
        if require_rare and mid not in rare:
            return False
        return n_desc(mid) <= max_desc

    return ok


def select_genes(
    diseases: set[str], seed_genes: set[str], gd: pl.DataFrame, cfg: dict[str, Any]
) -> list[str]:
    disease_genes: dict[str, set[str]] = defaultdict(set)
    for mid, hid in gd.select("mondo_id", "hgnc_id").iter_rows():
        if mid in diseases:
            disease_genes[mid].add(hid)
    limit = cfg.get("gene_from_disease_max_genes", 8)
    counts: dict[str, int] = defaultdict(int)
    for genes in disease_genes.values():
        if len(genes) <= limit:
            for g in genes:
                counts[g] += 1
    ranked = sorted(counts, key=lambda g: (-counts[g], g))
    out = sorted(seed_genes)
    for g in ranked:
        if len(out) >= cfg.get("max_genes", 150):
            break
        if g not in seed_genes:
            out.append(g)
    return out


def select_phenotypes(diseases: set[str], per_disease: int) -> list[str]:
    dp = bio.disease_phenotypes().filter(pl.col("mondo_id").is_in(list(diseases)))
    dp = dp.group_by("mondo_id", "hpo_id").agg(pl.col("frequency").max())
    dp = dp.with_columns(
        pl.col("hpo_id").map_elements(hpo_sim.ic, return_dtype=pl.Float64).alias("ic"),
    ).filter(pl.col("ic") > 0)
    # Frequent and specific terms first.
    dp = dp.with_columns(
        (pl.col("ic") * pl.col("frequency").fill_null(0.5).clip(0.1, 1.0)).alias("rank")
    )
    top = (
        dp.sort(["mondo_id", "rank"], descending=[False, True])
        .group_by("mondo_id")
        .head(per_disease)
    )
    return sorted(set(top["hpo_id"].to_list()))


def run() -> dict[str, Any]:
    seeds = load_seeds()
    cfg = seeds.get("expansion", {})
    index = disease_index()

    seed_genes: dict[str, str] = {}
    missing = []
    for name in seeds.get("genes", []):
        hid = bio.resolve_gene(name)
        (missing.append(name) if hid is None else seed_genes.__setitem__(hid, name))
    seed_diseases: dict[str, str] = {}
    for name in seeds.get("diseases", []):
        mid = resolve_disease(name, index)
        (missing.append(name) if mid is None else seed_diseases.__setitem__(mid, name))
    if missing:
        raise SystemExit(f"unresolved seeds: {missing}")

    sources = cfg.get("gene_disease_sources", ["mondo", "clingen", "orphanet", "hpo"])
    live = set(bio.mondo_terms().filter(~pl.col("deprecated"))["id"].to_list())
    gd = bio.gene_disease().filter(
        pl.col("source").is_in(sources)
        & (pl.col("polarity") == "supports")
        & pl.col("mondo_id").is_in(list(live))
    )

    pw = bio.reactome()
    sizes = pw.group_by("pathway_id").len("n")
    pw = pw.join(sizes, on="pathway_id").filter(pl.col("n") <= cfg.get("pathway_max_genes", 40))
    pathway_genes: dict[str, set[str]] = defaultdict(set)
    for hid, pid in pw.select("hgnc_id", "pathway_id").iter_rows():
        pathway_genes[pid].add(hid)

    scope_map = expand(
        set(seed_diseases),
        set(seed_genes),
        gd,
        cfg,
        pathway_genes=pathway_genes,
        hpo_scores=hpo_sim.cosine_matrix,
        eligible=eligibility(cfg, set(seed_diseases)),
    )
    gene_ids = select_genes(set(scope_map), set(seed_genes), gd, cfg)
    phenotypes = select_phenotypes(set(scope_map), cfg.get("phenotypes_per_disease", 25))

    terms = bio.mondo_terms().filter(pl.col("id").is_in(list(scope_map)))
    hg = bio.hgnc().filter(pl.col("hgnc_id").is_in(gene_ids))
    hp = bio.hpo_terms().filter(pl.col("id").is_in(phenotypes))
    diseases = [
        {
            "mondo_id": r["id"],
            "label": r["label"],
            "synonyms": r["exact_synonyms"],
            "seed": r["id"] in seed_diseases,
            "hop": scope_map[r["id"]]["hop"],
            "via": scope_map[r["id"]]["via"],
        }
        for r in terms.sort("id").iter_rows(named=True)
    ]
    genes = [
        {
            "hgnc_id": r["hgnc_id"],
            "symbol": r["symbol"],
            "name": r["name"],
            "aliases": sorted(set(r["aliases"] + r["prev_symbols"])),
            "seed": r["hgnc_id"] in seed_genes,
        }
        for r in hg.sort("hgnc_id").iter_rows(named=True)
    ]
    phen = [{"hpo_id": r["id"], "label": r["label"]} for r in hp.sort("id").iter_rows(named=True)]

    body = {"genes": genes, "diseases": diseases, "phenotypes": phen}
    content_hash = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    previous = json.loads(SCOPE_FILE.read_text()) if SCOPE_FILE.exists() else {}
    version = next_version(previous.get("data_version"), content_hash, previous.get("content_hash"))
    out = {
        "data_version": version,
        "content_hash": content_hash,
        "cluster": seeds.get("cluster"),
        **body,
    }
    SCOPE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCOPE_FILE.write_text(json.dumps(out, indent=1))
    log.info(
        "scope %s: %d diseases (%d seeds), %d genes, %d phenotypes",
        version,
        len(diseases),
        sum(d["seed"] for d in diseases),
        len(genes),
        len(phen),
    )
    return out
