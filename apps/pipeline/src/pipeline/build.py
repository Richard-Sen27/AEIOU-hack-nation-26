"""Stage 4: merge assertions into edges + evidence with tier-weighted confidence."""

from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
from backend.schemas.enums import (
    RELATION_FAMILY,
    SYMMETRIC_RELATIONS,
    TIER_WEIGHTS,
    EdgeStatus,
    EvidenceTier,
    NodeType,
    Origin,
    Polarity,
    Relation,
    compute_confidence,
    edge_id,
)

from pipeline.config import settings
from pipeline.contracts import read_table
from pipeline.paths import GRAPH

log = logging.getLogger(__name__)

STAGE4 = GRAPH / "stage4"
FINAL = GRAPH / "final"
VERSION_FILE = GRAPH / "version.json"

ORIGIN_RANK = {o.value: i for i, o in enumerate(Origin)}  # observed wins over inferred, ...
DROP_FEATURE_KEYS = {"weight", "curated_file"}


# Hypotheses (edges whose evidence is all inferred) keep a score-based confidence so strong ones
# pass the 0.6 threshold, but are capped below "High" (0.8): a hypothesis is never shown as High.
INFERRED_CONFIDENCE_CAP = 0.79
# Weaker kinds of hypothesis have a lower ceiling. Proximity and candidate links stay below the
# 0.6 "supported" threshold, so they can never carry a supported route.
INFERRED_CONFIDENCE_CAPS: dict[str, float] = {
    Relation.near_on_chromosome.value: 0.45,
    Relation.candidate_phenotype.value: 0.55,
    Relation.suggested_by_neighbour.value: 0.55,
}
# Features that describe a hypothesis; an edge that also has observed evidence is not one.
HYPOTHESIS_FEATURE_KEYS = ("explanation", "method", "confidence_basis")


def inferred_cap(relation: str) -> float:
    return INFERRED_CONFIDENCE_CAPS.get(relation, INFERRED_CONFIDENCE_CAP)


def evidence_weight(tier: str, features: dict | None, origin: str = "observed") -> float:
    """Tier weight; inferred rows may carry a lower score-based weight, never above the tier."""
    base = TIER_WEIGHTS[EvidenceTier(tier)]
    if (
        origin == Origin.inferred.value
        and features
        and isinstance(features.get("weight"), int | float)
    ):
        return max(0.0, min(base, float(features["weight"])))
    return base


def _num(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def merge_features(items: list[dict]) -> dict[str, Any] | None:
    """Numbers keep the maximum, dicts merge key by key (numbers again by maximum), anything else
    keeps the first value. ``frequency_label`` follows the evidence row whose ``frequency`` won."""
    out: dict[str, Any] = {}
    diseases: list[str] = []
    best_freq: float | None = None
    for f in items:
        for k, v in f.items():
            if k in DROP_FEATURE_KEYS or v is None:
                continue
            if k == "disease":
                if v not in diseases:
                    diseases.append(v)
            elif k not in out:
                out[k] = dict(v) if isinstance(v, dict) else v
            elif _num(v) and _num(out[k]):
                out[k] = max(out[k], v)
            elif isinstance(v, dict) and isinstance(out[k], dict):
                for kk, vv in v.items():
                    cur = out[k].get(kk)
                    if cur is None or (_num(vv) and _num(cur) and vv > cur):
                        out[k][kk] = vv
        freq = f.get("frequency")
        if _num(freq) and (best_freq is None or freq > best_freq):
            best_freq = freq
            if f.get("frequency_label") is not None:
                out["frequency_label"] = f["frequency_label"]
    if diseases:
        out["diseases"] = diseases
    return out or None


def merge_nodes(nodes: pl.DataFrame) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for r in nodes.iter_rows(named=True):
        attrs = json.loads(r["attrs"]) if r["attrs"] else {}
        cur = merged.get(r["id"])
        if cur is None:
            merged[r["id"]] = {
                "id": r["id"],
                "type": r["type"],
                "label": r["label"],
                "description": r["description"],
                "url": r["url"],
                "attrs": attrs,
            }
            continue
        for k in ("type", "label", "description", "url"):
            if not cur[k] and r[k]:
                cur[k] = r[k]
        for k, v in attrs.items():
            cur["attrs"].setdefault(k, v)
    return merged


WORK_RELATIONS = ("authored", "pi_of", "investigator_of")


def prune_people(
    nodes: pl.DataFrame, assertions: pl.DataFrame, min_links: int | None = None
) -> tuple[pl.DataFrame, dict[str, int]]:
    """Drop researchers who connect fewer than ``min_links`` works (papers, grants, trials) and
    whose works do not touch two different diseases. Returns filtered assertions and stats.
    Institutions that lose all their people become orphans and are pruned by ``merge``."""
    min_links = settings.researcher_min_links if min_links is None else min_links
    researchers = set(nodes.filter(pl.col("type") == "researcher")["id"].to_list())
    if not researchers:
        return assertions, {"researchers_before": 0, "researchers_kept": 0, "min_links": min_links}
    work = assertions.filter(pl.col("relation").is_in(WORK_RELATIONS))
    topics = assertions.filter(
        pl.col("relation").is_in(["about", "funds_research_on", "studies"])
        & pl.col("target_id").str.starts_with("MONDO:")
    ).select(pl.col("source_id").alias("work"), pl.col("target_id").alias("disease"))
    person_work = work.select(
        pl.col("source_id").alias("person"), pl.col("target_id").alias("work")
    ).unique()
    links = person_work.group_by("person").len("n_works")
    diseases = (
        person_work.join(topics, on="work")
        .group_by("person")
        .agg(pl.col("disease").n_unique().alias("n_diseases"))
    )
    stats = links.join(diseases, on="person", how="left").fill_null(0)
    keep = set(
        stats.filter((pl.col("n_works") >= min_links) | (pl.col("n_diseases") >= 2))[
            "person"
        ].to_list()
    )
    drop = researchers - keep
    out = assertions.filter(
        ~pl.col("source_id").is_in(list(drop)) & ~pl.col("target_id").is_in(list(drop))
    )
    info = {
        "researchers_before": len(researchers),
        "researchers_kept": len(researchers & keep),
        "min_links": min_links,
    }
    log.info("people pruning: %s", info)
    return out, info


def merge(
    nodes: pl.DataFrame, synonyms: pl.DataFrame, assertions: pl.DataFrame
) -> dict[str, pl.DataFrame]:
    """Merge contract tables into graph tables: nodes, synonyms, edges, evidence."""
    assertions, prune_info = prune_people(nodes, assertions)
    node_map = merge_nodes(nodes)
    bad_type = [n for n in node_map.values() if n["type"] not in NodeType.__members__]
    for n in bad_type:
        log.warning("dropping node %s with unknown type %r", n["id"], n["type"])
        del node_map[n["id"]]
    for n in node_map.values():
        if not n["label"]:
            n["label"] = n["id"]

    relations = set(Relation.__members__)
    dropped: dict[str, int] = defaultdict(int)
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for a in assertions.iter_rows(named=True):
        src, rel, tgt = a["source_id"], a["relation"], a["target_id"]
        if rel not in relations:
            dropped[f"unknown relation {rel}"] += 1
            continue
        if src not in node_map or tgt not in node_map:
            dropped[f"unknown endpoint ({a.get('_source', '?')})"] += 1
            continue
        if src == tgt:
            dropped["self loop"] += 1
            continue
        if a["tier"] not in EvidenceTier.__members__:
            dropped[f"unknown tier {a['tier']}"] += 1
            continue
        if Relation(rel) in SYMMETRIC_RELATIONS and src > tgt:
            src, tgt = tgt, src
        groups[(src, rel, tgt)].append(a)
    for reason, n in sorted(dropped.items()):
        log.warning("dropped %d assertions: %s", n, reason)

    edges, evidence = [], []
    for (src, rel, tgt), items in groups.items():
        eid = edge_id(src, rel, tgt)
        seen = set()
        support, n_contra, feats = [], 0, []
        origins = []
        for a in items:
            f = json.loads(a["features"]) if a["features"] else {}
            polarity = a["polarity"] if a["polarity"] in Polarity.__members__ else "supports"
            key = (a["tier"], a["source_type"], a["source_ref"], a["quote"], polarity)
            if key in seen:
                continue
            seen.add(key)
            origins.append(a["origin"] if a["origin"] in Origin.__members__ else "observed")
            if polarity == "contradicts":
                n_contra += 1
            else:
                support.append(evidence_weight(a["tier"], f, origins[-1]))
            feats.append(f)
            evidence.append(
                {
                    "edge_id": eid,
                    "tier": a["tier"],
                    "source_type": a["source_type"],
                    "source_id": a["source_ref"],
                    "url": a["url"],
                    "quote": a["quote"],
                    "retrieved_at": a["retrieved_at"],
                    "polarity": polarity,
                    "claim_type": a["claim_type"],
                }
            )
        origin = min(origins, key=lambda o: ORIGIN_RANK[o])
        confidence = compute_confidence(support, n_contra)
        merged = merge_features(feats)
        if origin == Origin.inferred.value:
            cap = inferred_cap(rel)
            merged = {**(merged or {}), "confidence_raw": confidence, "confidence_cap": cap}
            confidence = min(confidence, cap)
        elif merged:
            for k in HYPOTHESIS_FEATURE_KEYS:
                merged.pop(k, None)
            merged = merged or None
        status = EdgeStatus.active.value
        if origin in (Origin.user_contributed.value, Origin.patient_reported.value):
            status = EdgeStatus.pending_review.value
        edges.append(
            {
                "id": eid,
                "source_id": src,
                "target_id": tgt,
                "relation": rel,
                "family": RELATION_FAMILY[Relation(rel)].value,
                "confidence": confidence,
                "origin": origin,
                "status": status,
                "features": json.dumps(merged, sort_keys=True) if merged else None,
                "n_evidence": len(seen),
                "n_contradicting": n_contra,
            }
        )
    edge_df = pl.DataFrame(edges, infer_schema_length=None) if edges else pl.DataFrame()
    used = (
        set(edge_df["source_id"].to_list()) | set(edge_df["target_id"].to_list())
        if edges
        else set()
    )
    orphans = [nid for nid in node_map if nid not in used]
    if orphans:
        log.info("pruning %d orphan nodes", len(orphans))
    node_rows = [
        {**n, "attrs": json.dumps(n["attrs"], sort_keys=True, ensure_ascii=False)}
        for nid, n in node_map.items()
        if nid in used
    ]
    node_df = pl.DataFrame(node_rows, infer_schema_length=None)
    syn = (
        synonyms.filter(pl.col("node_id").is_in(list(used)) & pl.col("synonym").is_not_null())
        .with_columns(pl.col("synonym").str.strip_chars())
        .filter(pl.col("synonym") != "")
        .unique(["node_id", "synonym"], keep="first", maintain_order=True)
        .select("node_id", "synonym", "source")
    )
    ev_df = pl.DataFrame(evidence, infer_schema_length=None)
    PRUNE_INFO.clear()
    PRUNE_INFO.update(prune_info, orphans_pruned=len(orphans))
    return {"nodes": node_df, "synonyms": syn, "edges": edge_df, "evidence": ev_df}


PRUNE_INFO: dict[str, Any] = {}


def write_graph(tables: dict[str, pl.DataFrame], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.write_parquet(out / f"{name}.parquet")


def read_graph(root: Path = FINAL) -> dict[str, pl.DataFrame]:
    return {p.stem: pl.read_parquet(p) for p in root.glob("*.parquet")}


def require_validated(tables: dict[str, pl.DataFrame]) -> str:
    """The graph's data_version, or exit unless Stage 6 passed for exactly this version."""
    version = tables["nodes"]["data_version"][0]
    report_file = FINAL / "validation.json"
    report = json.loads(report_file.read_text()) if report_file.exists() else {}
    if not report.get("ok") or report.get("data_version") != version:
        raise SystemExit(
            f"refusing: validation for data_version {version} has not passed "
            f"(validation.json: ok={report.get('ok')}, data_version={report.get('data_version')})"
        )
    return version


def content_hash(tables: dict[str, pl.DataFrame]) -> str:
    h = hashlib.sha256()
    for name in sorted(tables):
        df = tables[name].drop("retrieved_at", "data_version", strict=False)
        if df.height:
            h.update(name.encode())
            h.update(str(df.hash_rows(seed=0).sort().to_list()).encode())
    return h.hexdigest()


def assign_version(digest: str) -> str:
    """YYYY-MM-DD.N, bumped only when the graph content changes."""
    prev = json.loads(VERSION_FILE.read_text()) if VERSION_FILE.exists() else {}
    today = date.today().isoformat()
    if prev.get("hash") == digest:
        return prev["data_version"]
    v = prev.get("data_version", "")
    n = int(v.split(".")[-1]) + 1 if v.startswith(today + ".") else 1
    version = f"{today}.{n}"
    VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    VERSION_FILE.write_text(json.dumps({"data_version": version, "hash": digest}))
    return version


def summarize(tables: dict[str, pl.DataFrame]) -> dict[str, Any]:
    e, n = tables["edges"], tables["nodes"]
    return {
        "nodes": n.height,
        "edges": e.height,
        "evidence": tables["evidence"].height,
        "synonyms": tables["synonyms"].height,
        "nodes_by_type": dict(sorted(n.group_by("type").len().iter_rows())),
        "edges_by_relation": dict(sorted(e.group_by("relation").len().iter_rows())),
        "edges_supported": int((e["confidence"] >= 0.6).sum()),
        "pruning": dict(PRUNE_INFO),
    }


def run() -> dict[str, pl.DataFrame]:
    tables = merge(read_table("nodes"), read_table("synonyms"), read_table("assertions"))
    write_graph(tables, STAGE4)
    log.info("stage4: %s", json.dumps(summarize(tables)))
    return tables
