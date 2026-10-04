"""Load the fixture graph: replaces all graph tables in one transaction (data_version "fixture").

    uv run python -m backend.fixtures.load [--url URL] [--no-embeddings]

Connects as atlas_pipeline (PIPELINE_DATABASE_URL). Embeddings are filled when
backend.embeddings is importable and works; otherwise nodes.embedding stays NULL.
"""

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from backend.config import get_settings

log = logging.getLogger(__name__)

FIXTURE_PATH = Path(__file__).with_name("demo_graph.json")
GRAPH_TABLES = (
    "evidence",
    "edges",
    "node_synonyms",
    "nodes",
    "clusters",
    "explanations_cache",
    "ingestion_runs",
    "hpo_terms",  # the fixture has no term table: symptom matching falls back to its nodes
    "graph_changes",
)


def plain_url(url: str) -> str:
    """psycopg wants postgresql://; accept SQLAlchemy-style driver suffixes too."""
    return url.replace("postgresql+psycopg://", "postgresql://").replace(
        "postgresql+asyncpg://", "postgresql://"
    )


def read_fixture(path: Path = FIXTURE_PATH) -> dict[str, Any]:
    return json.loads(path.read_text())


def _embeddings(nodes: list[dict[str, Any]]) -> list[str | None]:
    try:
        from backend.embeddings import embed_texts

        texts = [
            ". ".join(
                [n["label"], n.get("description") or "", *(s["synonym"] for s in n["synonyms"])]
            )
            for n in nodes
        ]
        vectors = embed_texts(texts)
        return ["[" + ",".join(f"{v:.6f}" for v in row) + "]" for row in vectors]
    except Exception as exc:  # noqa: BLE001 - embeddings are optional for the fixture
        log.warning("fixture embeddings skipped (%s)", type(exc).__name__)
        return [None] * len(nodes)


def load_fixture(
    url: str | None = None, *, embeddings: bool = True, path: Path = FIXTURE_PATH
) -> dict[str, int]:
    data = read_fixture(path)
    version = data["data_version"]
    nodes, edges = data["nodes"], data["edges"]
    vectors = _embeddings(nodes) if embeddings else [None] * len(nodes)

    with psycopg.connect(plain_url(url or get_settings().pipeline_database_url)) as conn:
        with conn.cursor() as cur:
            cur.execute(f"TRUNCATE {', '.join(GRAPH_TABLES)}")
            cur.executemany(
                "INSERT INTO clusters (id, label, mechanism_summary, member_count, attrs,"
                " data_version) VALUES (%s, %s, %s, %s, %s, %s)",
                [
                    (
                        c["id"],
                        c["label"],
                        c["mechanism_summary"],
                        c["member_count"],
                        Jsonb(c["attrs"]),
                        version,
                    )
                    for c in data["clusters"]
                ],
            )
            cur.executemany(
                "INSERT INTO nodes (id, type, label, description, url, attrs, cluster_id, x, y,"
                " centrality, embedding, data_version)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s)",
                [
                    (
                        n["id"],
                        n["type"],
                        n["label"],
                        n["description"],
                        n["url"],
                        Jsonb(n["attrs"]),
                        n["cluster_id"],
                        n["x"],
                        n["y"],
                        n["centrality"],
                        vec,
                        version,
                    )
                    for n, vec in zip(nodes, vectors, strict=True)
                ],
            )
            cur.executemany(
                "INSERT INTO node_synonyms (node_id, synonym, source) VALUES (%s, %s, %s)",
                [(n["id"], s["synonym"], s["source"]) for n in nodes for s in n["synonyms"]],
            )
            cur.executemany(
                "INSERT INTO edges (id, source_id, target_id, relation, family, confidence,"
                " origin, status, features, data_version)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        e["id"],
                        e["source_id"],
                        e["target_id"],
                        e["relation"],
                        e["family"],
                        e["confidence"],
                        e["origin"],
                        e["status"],
                        Jsonb(e["features"]) if e["features"] is not None else None,
                        version,
                    )
                    for e in edges
                ],
            )
            cur.executemany(
                "INSERT INTO evidence (edge_id, tier, source_type, source_id, url, quote,"
                " retrieved_at, polarity, claim_type)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        e["id"],
                        ev["tier"],
                        ev["source_type"],
                        ev["source_id"],
                        ev["url"],
                        ev["quote"],
                        ev["retrieved_at"],
                        ev["polarity"],
                        ev["claim_type"],
                    )
                    for e in edges
                    for ev in e["evidence"]
                ],
            )
            cur.executemany(
                "INSERT INTO explanations_cache (path_id, role, language, data_version, text,"
                " citations) VALUES (%s, %s, %s, %s, %s, %s)",
                [
                    (
                        x["path_id"],
                        x["role"],
                        x["language"],
                        version,
                        x["text"],
                        Jsonb(x["citations"]),
                    )
                    for x in data["explanations"]
                ],
            )
            counts = {
                "clusters": len(data["clusters"]),
                "nodes": len(nodes),
                "edges": len(edges),
                "evidence": sum(len(e["evidence"]) for e in edges),
                "explanations": len(data["explanations"]),
                "embeddings": sum(v is not None for v in vectors),
            }
            cur.execute(
                "INSERT INTO ingestion_runs (data_version, pipeline_commit, source_versions,"
                " counts) VALUES (%s, %s, %s, %s)",
                (version, "fixture", Jsonb({"fixture": "demo_graph.json"}), Jsonb(counts)),
            )
    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", help="Postgres URL (default: PIPELINE_DATABASE_URL)")
    parser.add_argument("--no-embeddings", action="store_true", help="Leave embeddings NULL")
    args = parser.parse_args()
    embeddings = not args.no_embeddings and os.environ.get("FIXTURE_EMBEDDINGS", "1") != "0"
    counts = load_fixture(args.url, embeddings=embeddings)
    print("fixture loaded:", ", ".join(f"{k}={v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
