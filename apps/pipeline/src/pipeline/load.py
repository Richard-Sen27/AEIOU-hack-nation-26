"""Stage 7a: bulk-load the final graph with psql \\copy into `staging`, then promote it into the
graph tables in one transaction and record an `ingestion_runs` row."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

import polars as pl

from pipeline.build import FINAL, read_graph, require_validated
from pipeline.config import psql_path, settings
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
    # synonyms and parents as JSON arrays (converted to text[] on promote)
    "hpo_terms": "id text, label text, synonyms text, parents text, ic double precision",
}

HPO_TERMS = """
SELECT to_regclass('public.hpo_terms') IS NOT NULL AS has_hpo_terms_table \\gset
\\if :has_hpo_terms_table
TRUNCATE hpo_terms;
INSERT INTO hpo_terms (id, label, synonyms, parents, ic)
  SELECT id, label,
         ARRAY(SELECT jsonb_array_elements_text(COALESCE(synonyms, '[]')::jsonb)),
         ARRAY(SELECT jsonb_array_elements_text(COALESCE(parents, '[]')::jsonb)),
         ic
  FROM staging.hpo_terms;
\\else
\\echo hpo_terms: table missing (migration not applied); HPO term table not loaded
\\endif
"""

PROMOTE = (
    """
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
-- Only the run whose graph is loaded stays recorded (older versions no longer exist here).
DELETE FROM ingestion_runs WHERE data_version <> :'version';
"""
    + HPO_TERMS
    + """
COMMIT;
"""
)


def pipeline_commit() -> str:
    if commit := os.environ.get("PIPELINE_COMMIT"):
        return commit.strip()
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
        "hpo_terms": hpo_terms_frame(tables.get("hpo_terms")),
    }
    paths = {}
    for name, ddl in STAGING_DDL.items():
        cols = [c.strip().split(" ")[0] for c in ddl.split(",")]
        path = LOAD_DIR / f"{name}.csv"
        frames[name].select(cols).write_csv(path, null_value="")
        paths[name] = path
    return paths


def hpo_terms_frame(df: pl.DataFrame | None) -> pl.DataFrame:
    """hpo_terms with its list columns as JSON text for the CSV staging table."""
    cols = {"id": pl.String, "label": pl.String, "synonyms": pl.String, "parents": pl.String}
    if df is None:
        return pl.DataFrame(schema={**cols, "ic": pl.Float64})

    def as_json(col: str) -> pl.Series:
        values = [
            json.dumps(list(v) if v is not None else [], ensure_ascii=False)
            for v in df[col].to_list()
        ]
        return pl.Series(col, values, dtype=pl.String)

    return df.with_columns(as_json("synonyms"), as_json("parents")).select(
        "id", "label", "synonyms", "parents", "ic"
    )


def counts(tables: dict[str, pl.DataFrame]) -> dict[str, Any]:
    summary_file = FINAL / "summary.json"
    summary = json.loads(summary_file.read_text()) if summary_file.exists() else {}
    return {
        "nodes": tables["nodes"].height,
        "edges": tables["edges"].height,
        "evidence": tables["evidence"].height,
        "synonyms": tables["synonyms"].height,
        "clusters": tables["clusters"].height,
        "hpo_terms": tables["hpo_terms"].height if "hpo_terms" in tables else 0,
        "nodes_by_type": summary.get("nodes_by_type"),
        "edges_by_relation": summary.get("edges_by_relation"),
    }


def psql(script: str, variables: dict[str, str] | None = None) -> None:
    cmd = [psql_path(), settings.pipeline_database_url, "-X", "-q", "-v", "ON_ERROR_STOP=1"]
    for k, v in (variables or {}).items():
        cmd += ["-v", f"{k}={v}"]
    proc = subprocess.run(cmd, input=script, text=True, capture_output=True)
    if proc.returncode != 0:
        raise SystemExit(f"psql failed:\n{proc.stderr}")
    for line in proc.stdout.splitlines():  # the scripts' \echo lines (diff and hpo_terms notes)
        if line.strip():
            log.info("psql: %s", line.strip())


def run() -> dict[str, Any]:
    tables = read_graph(FINAL)
    version = require_validated(tables)
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
    key = "synonyms" if name == "node_synonyms" else name
    return tables[key].height if key in tables else 0
