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

from pipeline.contracts import read_table
from pipeline.paths import GRAPH

log = logging.getLogger(__name__)

STAGE4 = GRAPH / "stage4"
FINAL = GRAPH / "final"
VERSION_FILE = GRAPH / "version.json"

ORIGIN_RANK = {o.value: i for i, o in enumerate(Origin)}  # observed wins over inferred, ...
DROP_FEATURE_KEYS = {"weight", "curated_file"}


def evidence_weight(tier: str, features: dict | None) -> float:
    if features and isinstance(features.get("weight"), int | float):
        return max(0.0, min(1.0, float(features["weight"])))
    return TIER_WEIGHTS[EvidenceTier(tier)]


def merge_features(items: list[dict]) -> dict[str, Any] | None:
    out: dict[str, Any] = {}
    diseases: list[str] = []
    for f in items:
        for k, v in f.items():
            if k in DROP_FEATURE_KEYS or v is None:
                continue
            if k == "disease":
                if v not in diseases:
                    diseases.append(v)
            elif k not in out:
                out[k] = v
            elif isinstance(v, int | float) and isinstance(out[k], int | float):
                out[k] = max(out[k], v)
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


def merge(
    nodes: pl.DataFrame, synonyms: pl.DataFrame, assertions: pl.DataFrame
) -> dict[str, pl.DataFrame]:
    """Merge contract tables into graph tables: nodes, synonyms, edges, evidence."""
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
                support.append(evidence_weight(a["tier"], f))
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
                "confidence": compute_confidence(support, n_contra),
                "origin": origin,
                "status": status,
                "features": json.dumps(merge_features(feats), sort_keys=True)
                if merge_features(feats)
                else None,
                "n_evidence": len(seen),
                "n_contradicting": n_contra,
            }
        )
    edge_df = pl.DataFrame(edges, infer_schema_length=None) if edges else pl.DataFrame()
    used = set(edge_df["source_id"].to_list()) | set(edge_df["target_id"].to_list()) if edges else set()
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
    return {"nodes": node_df, "synonyms": syn, "edges": edge_df, "evidence": ev_df}


def write_graph(tables: dict[str, pl.DataFrame], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.write_parquet(out / f"{name}.parquet")


def read_graph(root: Path = FINAL) -> dict[str, pl.DataFrame]:
    return {p.stem: pl.read_parquet(p) for p in root.glob("*.parquet")}


def content_hash(tables: dict[str, pl.DataFrame]) -> str:
    h = hashlib.sha256()
    for name in sorted(tables):
        df = tables[name]
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
    }


def run() -> dict[str, pl.DataFrame]:
    tables = merge(read_table("nodes"), read_table("synonyms"), read_table("assertions"))
    write_graph(tables, STAGE4)
    log.info("stage4: %s", json.dumps(summarize(tables)))
    return tables
