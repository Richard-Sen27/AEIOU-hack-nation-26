"""Stage 7a: bulk-load the final graph with psql \\copy into `staging`, then promote it into the
graph tables in one transaction and record an `ingestion_runs` row."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

import polars as pl

from pipeline.build import FINAL, read_graph
from pipeline.config import settings
from pipeline.paths import GRAPH, RAW, ROOT

log = logging.getLogger(__name__)

LOAD_DIR = GRAPH / "load"

STAGING_DDL = {
    "clusters": "id text, label text, mechanism_summary text, member_count int, attrs text,"
    " data_version text",
    "nodes": "id text, type text, label text, description text, url text, attrs text,"
    " cluster_id text, x double precision, y double precision, centrality double precision,"
    " embedding text, data_version text",
    "node_synonyms": "node_id text, synonym text, source text",
    "edges": "id text, source_id text, target_id text, relation text, family text,"
    " confidence double precision, origin text, status text, features text, data_version text",
    "evidence": "edge_id text, tier text, source_type text, source_id text, url text, quote text,"
    " retrieved_at text, polarity text, claim_type text",
}

PROMOTE = """
BEGIN;
DELETE FROM explanations_cache WHERE data_version IS DISTINCT FROM :'version';
TRUNCATE evidence, edges, node_synonyms, nodes, clusters;
INSERT INTO clusters (id, label, mechanism_summary, member_count, attrs, data_version)
  SELECT id, label, mechanism_summary, member_count, COALESCE(attrs, '{}')::jsonb, data_version
  FROM staging.clusters;
INSERT INTO nodes (id, type, label, description, url, attrs, cluster_id, x, y, centrality,
                   embedding, data_version)
  SELECT id, type, COALESCE(label, id), description, url, COALESCE(attrs, '{}')::jsonb,
         cluster_id, x, y, centrality, embedding::vector, data_version
  FROM staging.nodes;
INSERT INTO node_synonyms (node_id, synonym, source)
  SELECT node_id, synonym, source FROM staging.node_synonyms;
INSERT INTO edges (id, source_id, target_id, relation, family, confidence, origin, status,
                   features, data_version)
  SELECT id, source_id, target_id, relation, family, confidence, origin, status,
         features::jsonb, data_version
  FROM staging.edges;
INSERT INTO evidence (edge_id, tier, source_type, source_id, url, quote, retrieved_at, polarity,
                      claim_type)
  SELECT edge_id, tier, source_type, source_id, url, quote, retrieved_at::timestamptz,
         COALESCE(polarity, 'supports'), claim_type
  FROM staging.evidence;
INSERT INTO ingestion_runs (data_version, pipeline_commit, source_versions, counts)
  VALUES (:'version', NULLIF(:'commit', ''), :'sources'::jsonb, :'counts'::jsonb)
  ON CONFLICT (data_version) DO UPDATE
  SET pipeline_commit = EXCLUDED.pipeline_commit, source_versions = EXCLUDED.source_versions,
      counts = EXCLUDED.counts, created_at = now();
COMMIT;
"""


def pipeline_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def source_versions() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for meta in sorted(RAW.glob("*/_meta.json")):
        out[meta.parent.name] = {
            r["file"]: {
                "source_version": r.get("source_version"),
                "retrieved_at": r.get("retrieved_at"),
                "sha256": r.get("sha256"),
            }
            for r in json.loads(meta.read_text())
        }
    return out


def _vector(v) -> str | None:
    if v is None:
        return None
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def export_csv(tables: dict[str, pl.DataFrame]) -> dict[str, Path]:
    LOAD_DIR.mkdir(parents=True, exist_ok=True)
    nodes = tables["nodes"].with_columns(
        pl.col("embedding").map_elements(_vector, return_dtype=pl.String).alias("embedding")
    )
    frames = {
        "clusters": tables["clusters"],
        "nodes": nodes,
        "node_synonyms": tables["synonyms"],
        "edges": tables["edges"],
        "evidence": tables["evidence"],
    }
    paths = {}
    for name, ddl in STAGING_DDL.items():
        cols = [c.strip().split(" ")[0] for c in ddl.split(",")]
        path = LOAD_DIR / f"{name}.csv"
        frames[name].select(cols).write_csv(path, null_value="")
        paths[name] = path
    return paths


def counts(tables: dict[str, pl.DataFrame]) -> dict[str, Any]:
    summary_file = FINAL / "summary.json"
    summary = json.loads(summary_file.read_text()) if summary_file.exists() else {}
    return {
        "nodes": tables["nodes"].height,
        "edges": tables["edges"].height,
        "evidence": tables["evidence"].height,
        "synonyms": tables["synonyms"].height,
        "clusters": tables["clusters"].height,
        "nodes_by_type": summary.get("nodes_by_type"),
        "edges_by_relation": summary.get("edges_by_relation"),
    }


def psql(script: str, variables: dict[str, str] | None = None) -> None:
    cmd = [settings.psql_bin, settings.pipeline_database_url, "-X", "-q", "-v", "ON_ERROR_STOP=1"]
    for k, v in (variables or {}).items():
        cmd += ["-v", f"{k}={v}"]
    proc = subprocess.run(cmd, input=script, text=True, capture_output=True)
    if proc.returncode != 0:
        raise SystemExit(f"psql failed:\n{proc.stderr}")


def run() -> dict[str, Any]:
    tables = read_graph(FINAL)
    version = tables["nodes"]["data_version"][0]
    paths = export_csv(tables)
    staging = []
    for name, ddl in STAGING_DDL.items():
        staging.append(f"DROP TABLE IF EXISTS staging.{name};")
        staging.append(f"CREATE TABLE staging.{name} ({ddl});")
        staging.append(f"\\copy staging.{name} FROM '{paths[name]}' WITH (FORMAT csv, HEADER true)")
    psql("\n".join(staging))
    log.info("staging loaded (%s)", ", ".join(f"{k}={tables_len(tables, k)}" for k in paths))
    c = counts(tables)
    psql(
        PROMOTE,
        {
            "version": version,
            "commit": pipeline_commit(),
            "sources": json.dumps(source_versions()),
            "counts": json.dumps(c),
        },
    )
    log.info("promoted data_version %s into the graph tables", version)
    return c


def tables_len(tables: dict[str, pl.DataFrame], name: str) -> int:
    return tables["synonyms" if name == "node_synonyms" else name].height
