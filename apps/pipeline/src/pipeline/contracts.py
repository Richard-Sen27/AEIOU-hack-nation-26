"""Table contracts shared by every source and stage.

Every source's ``normalize`` (Stage 2) and every extractor (Stage 3) writes three Parquet tables,
``nodes``, ``synonyms`` and ``assertions``, under ``data/normalized/<source>/`` or
``data/extracted/<name>/``. Stage 4 reads all of them.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import polars as pl

from pipeline.paths import EXTRACTED, NORMALIZED, RAW, SCOPE_FILE

log = logging.getLogger(__name__)

NODE_SCHEMA: dict[str, pl.DataType] = {
    "id": pl.String,
    "type": pl.String,
    "label": pl.String,
    "description": pl.String,
    "url": pl.String,
    "attrs": pl.String,  # JSON object
}

SYNONYM_SCHEMA: dict[str, pl.DataType] = {
    "node_id": pl.String,
    "synonym": pl.String,
    "source": pl.String,
}

ASSERTION_SCHEMA: dict[str, pl.DataType] = {
    "source_id": pl.String,
    "target_id": pl.String,
    "relation": pl.String,
    "origin": pl.String,  # observed | inferred | patient_reported | user_contributed
    "features": pl.String,  # JSON object or null
    "tier": pl.String,  # curated_db | peer_reviewed | review | preprint | llm_inferred | ...
    "source_type": pl.String,  # e.g. clinvar, hpo, pubmed, clinicaltrials, curated
    "source_ref": pl.String,  # record id in that source: PMID, NCT, VariationID, ...
    "url": pl.String,
    "quote": pl.String,
    "retrieved_at": pl.String,  # ISO 8601 UTC
    "polarity": pl.String,  # supports | contradicts
    "claim_type": pl.String,  # patient_observation | experimental | review | hypothesis | null
}

TABLES = {"nodes": NODE_SCHEMA, "synonyms": SYNONYM_SCHEMA, "assertions": ASSERTION_SCHEMA}


@dataclass
class Scope:
    data_version: str
    genes: list[dict[str, Any]] = field(default_factory=list)
    diseases: list[dict[str, Any]] = field(default_factory=list)
    phenotypes: list[dict[str, Any]] = field(default_factory=list)

    @property
    def gene_ids(self) -> set[str]:
        return {g["hgnc_id"] for g in self.genes}

    @property
    def gene_symbols(self) -> set[str]:
        return {g["symbol"] for g in self.genes}

    @property
    def disease_ids(self) -> set[str]:
        return {d["mondo_id"] for d in self.diseases}

    @property
    def phenotype_ids(self) -> set[str]:
        return {p["hpo_id"] for p in self.phenotypes}

    def to_dict(self) -> dict[str, Any]:
        return {
            "data_version": self.data_version,
            "genes": self.genes,
            "diseases": self.diseases,
            "phenotypes": self.phenotypes,
        }


def load_scope(required: bool = True) -> Scope | None:
    if not SCOPE_FILE.exists():
        if required:
            raise FileNotFoundError(f"{SCOPE_FILE} missing; run `atlas-pipeline scope` first")
        return None
    data = json.loads(SCOPE_FILE.read_text())
    return Scope(
        data_version=data["data_version"],
        genes=data.get("genes", []),
        diseases=data.get("diseases", []),
        phenotypes=data.get("phenotypes", []),
    )


@dataclass(frozen=True)
class Source:
    """A connector. ``phase`` is "bulk" (fetch needs no scope) or "scoped" (runs after scope)."""

    name: str
    phase: Literal["bulk", "scoped"]
    fetch: Callable[[Scope | None], Awaitable[None]]
    normalize: Callable[[Scope], None]


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def meta_path(source: str) -> Path:
    return RAW / source / "_meta.json"


def read_meta(source: str) -> list[dict[str, Any]]:
    p = meta_path(source)
    return json.loads(p.read_text()) if p.exists() else []


def record_raw(
    source: str,
    url: str,
    path: Path,
    source_version: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Record (or replace) the metadata entry for one raw file in data/raw/<source>/_meta.json."""
    path = Path(path)
    rel = path.relative_to(RAW / source).as_posix() if path.is_relative_to(RAW / source) else str(path)
    record = {
        "file": rel,
        "url": url,
        "retrieved_at": now_iso(),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "source_version": source_version,
        **extra,
    }
    records = [r for r in read_meta(source) if r.get("file") != rel]
    records.append(record)
    meta_path(source).parent.mkdir(parents=True, exist_ok=True)
    meta_path(source).write_text(json.dumps(records, indent=2))
    return record


def raw_record(source: str, file: str) -> dict[str, Any] | None:
    return next((r for r in read_meta(source) if r.get("file") == file), None)


def _frame(rows: pl.DataFrame | Iterable[Mapping[str, Any]], schema: dict[str, pl.DataType]):
    if isinstance(rows, pl.DataFrame):
        df = rows
        for col, dtype in schema.items():
            if col not in df.columns:
                df = df.with_columns(pl.lit(None, dtype=dtype).alias(col))
        df = df.select([pl.col(c).cast(t) for c, t in schema.items()])
    else:
        rows = [{c: _cell(r.get(c)) for c in schema} for r in rows]
        df = pl.DataFrame(rows, schema=schema, orient="row") if rows else pl.DataFrame(schema=schema)
    return df


def _cell(v: Any) -> Any:
    if isinstance(v, dict | list):
        return json.dumps(v, sort_keys=True, ensure_ascii=False)
    return v


def write_tables(
    source: str,
    nodes: pl.DataFrame | Iterable[Mapping[str, Any]] = (),
    synonyms: pl.DataFrame | Iterable[Mapping[str, Any]] = (),
    assertions: pl.DataFrame | Iterable[Mapping[str, Any]] = (),
    stage: Literal["normalized", "extracted"] = "normalized",
) -> Path:
    """Write the three contract tables. dict/list values in attrs/features are JSON-encoded."""
    out = (NORMALIZED if stage == "normalized" else EXTRACTED) / source
    out.mkdir(parents=True, exist_ok=True)
    frames = {
        "nodes": _frame(nodes, NODE_SCHEMA).unique("id", keep="first", maintain_order=True),
        "synonyms": _frame(synonyms, SYNONYM_SCHEMA).unique(maintain_order=True),
        "assertions": _frame(assertions, ASSERTION_SCHEMA),
    }
    for name, df in frames.items():
        df.write_parquet(out / f"{name}.parquet")
    log.info(
        "%s/%s: %d nodes, %d synonyms, %d assertions",
        stage,
        source,
        frames["nodes"].height,
        frames["synonyms"].height,
        frames["assertions"].height,
    )
    return out


def read_table(
    table: Literal["nodes", "synonyms", "assertions"],
    stages: Iterable[str] = ("normalized", "extracted"),
    sources: Iterable[str] | None = None,
) -> pl.DataFrame:
    """Concatenate one table across all sources (adds a `_source` column)."""
    schema = TABLES[table]
    wanted = set(sources) if sources is not None else None
    frames = []
    for stage in stages:
        root = NORMALIZED if stage == "normalized" else EXTRACTED
        if not root.exists():
            continue
        for d in sorted(p for p in root.iterdir() if p.is_dir()):
            f = d / f"{table}.parquet"
            if not f.exists() or (wanted is not None and d.name not in wanted):
                continue
            df = _frame(pl.read_parquet(f), schema)
            frames.append(df.with_columns(pl.lit(f"{stage}/{d.name}").alias("_source")))
    if not frames:
        return pl.DataFrame(schema={**schema, "_source": pl.String})
    return pl.concat(frames, how="vertical")


def assertion(
    source_id: str,
    target_id: str,
    relation: str,
    *,
    tier: str,
    source_type: str,
    source_ref: str | None = None,
    url: str | None = None,
    origin: str = "observed",
    features: dict[str, Any] | None = None,
    quote: str | None = None,
    retrieved_at: str | None = None,
    polarity: str = "supports",
    claim_type: str | None = None,
) -> dict[str, Any]:
    """Convenience constructor for one assertion row."""
    return {
        "source_id": source_id,
        "target_id": target_id,
        "relation": relation,
        "origin": origin,
        "features": features,
        "tier": tier,
        "source_type": source_type,
        "source_ref": source_ref,
        "url": url,
        "quote": quote,
        "retrieved_at": retrieved_at or now_iso(),
        "polarity": polarity,
        "claim_type": claim_type,
    }
