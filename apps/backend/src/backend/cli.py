"""Backend command line.

    uv run python -m backend.cli precompute-explanations [--language en ...] [--limit N]
    uv run python -m backend.cli eval [--mock] [--only golden,refusal,...]
    uv run python -m backend.cli demo-graph-changes MONDO:0100135 [--clear]

precompute-explanations fills explanations_cache for the demo paths in every role and the
requested languages. With a CLI ChatGPT login (`python -m backend.openai_auth.cli login`) the
texts are generated on that plan; without one they are built deterministically from the edge
data. Idempotent: rows cached for the current data_version are skipped.

Demo path selection (kept simple on purpose): seed diseases are the disease nodes marked
`attrs.seed`, else the 6 most central diseases. Their targets are the diseases in the same
cluster or one disease-disease edge away, plus the patient organizations serving any of those
and the registries/studies those organizations run. For each (seed, target) the best path
(family "all") is kept if it is supported (every edge >= 0.6). Paths are ranked by weakest
edge confidence (desc), then length (asc), then path_id, and the first --limit are used.

demo-graph-changes (DEMO DATA, local development only) inserts sample graph_changes rows for one
disease, as if a new load had linked its existing papers, trials, grants and patient groups, so
followers get notifications before a real second load produces changes. The rows use the data
version `demo-<UTC time>`; `--clear` deletes every demo row. Refuses to run unless API_URL and
the pipeline database are loopback addresses.
"""

import argparse
import asyncio
import logging
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from backend.schemas.enums import NodeType, PathFamily, Relation, Role
from backend.schemas.path import Path

log = logging.getLogger("backend.cli")

ROLES = (Role.guest, Role.patient, Role.doctor, Role.researcher)
SEED_COUNT = 6


@dataclass
class PrecomputeReport:
    paths: int = 0
    skipped: int = 0
    model: int = 0
    template: int = 0
    failed: int = 0
    unsupported_language: list[str] = field(default_factory=list)


def cli_llm():
    """LLMClient on the CLI user's ChatGPT login, or None when nobody is logged in."""
    from backend.llm import LLMClient
    from backend.observability.tracing import get_tracer
    from backend.openai_auth.cli import load_cli_token_provider

    try:
        provider = load_cli_token_provider()
    except Exception:  # noqa: BLE001 - unreadable credentials count as logged out
        return None
    return LLMClient(provider, tracer=get_tracer()) if provider else None


def select_demo_paths(limit: int = 12) -> list[Path]:
    from backend.api.services import path as path_service
    from backend.api.services.graph import get_graph

    store = get_graph()
    diseases = [n for n in store.nodes.values() if n.type == NodeType.disease]
    seeds = [n for n in diseases if n.attrs.get("seed")]
    if not seeds:
        seeds = sorted(diseases, key=lambda n: (-(n.centrality or 0.0), n.id))[:SEED_COUNT]

    def incident(node_id: str):
        for eid in store.incident.get(node_id, ()):
            yield store.edges[eid]

    def other(edge, node_id: str) -> str:
        return edge.target_id if edge.source_id == node_id else edge.source_id

    found: dict[str, Path] = {}
    for seed in seeds:
        targets: set[str] = set()
        if seed.cluster_id:
            targets.update(
                m
                for m in store.members.get(seed.cluster_id, ())
                if store.nodes[m].type == NodeType.disease
            )
        for edge in incident(seed.id):
            nb = store.nodes.get(other(edge, seed.id))
            if nb is not None and nb.type == NodeType.disease:
                targets.add(nb.id)
        for disease_id in [seed.id, *sorted(targets)]:
            for edge in incident(disease_id):
                if edge.relation != Relation.serves:
                    continue
                org = edge.source_id
                targets.add(org)
                for run in incident(org):
                    if run.relation == Relation.runs and run.source_id == org:
                        targets.add(run.target_id)
        targets.discard(seed.id)
        for target in sorted(targets):
            try:
                resp = path_service.find_paths(seed.id, target, family=PathFamily.all, k=1)
            except Exception:  # noqa: BLE001 - unknown node or bad pair: skip it
                continue
            for p in resp.paths:
                if p.supported:
                    found.setdefault(p.path_id, p)
    ranked = sorted(found.values(), key=lambda p: (-p.min_confidence, len(p.edge_ids), p.path_id))
    return ranked[:limit]


async def precompute_explanations(
    languages: Sequence[str] = ("en",),
    *,
    limit: int = 12,
    use_llm: bool | None = None,
    out=sys.stdout,
) -> PrecomputeReport:
    from backend.api.services import graph as graph_service
    from backend.api.services.explanation import (
        get_cached,
        store_explanation,
        template_explanation,
    )
    from backend.api.services.explanation.common import reading_grade
    from backend.api.services.explanation.generator import (
        Explanation,
        ExplanationError,
        generate_explanation,
    )
    from backend.api.services.explanation.pathdata import load_path_data
    from backend.api.services.explanation.templates import TEMPLATE_LANGUAGES
    from backend.db.session import user_transaction
    from backend.llm import LLMError
    from backend.schemas.common import Lens

    report = PrecomputeReport()
    if not graph_service.get_graph().nodes:
        async with user_transaction(None) as db:
            await graph_service.load_graph(db)
    llm = cli_llm() if use_llm is not False else None
    if use_llm and llm is None:
        raise SystemExit("no CLI ChatGPT login: uv run python -m backend.openai_auth.cli login")
    print(
        "explanations: " + ("generating with the CLI ChatGPT login" if llm else "template mode"),
        file=out,
    )
    paths = select_demo_paths(limit)
    report.paths = len(paths)
    for p in paths:
        async with user_transaction(None) as db:
            data = await load_path_data(db, p.edge_ids)
        for language in languages:
            if llm is None and language.split("-")[0] not in TEMPLATE_LANGUAGES:
                if language not in report.unsupported_language:
                    report.unsupported_language.append(language)
                continue
            for role in ROLES:
                lens = Lens(role=role, language=language)
                async with user_transaction(None) as db:
                    if await get_cached(db, p.edge_ids, lens) is not None:
                        report.skipped += 1
                        continue
                result: Explanation | None = None
                if llm is not None:
                    try:
                        result = await generate_explanation(llm, data, role, language)
                        report.model += 1
                    except (LLMError, ExplanationError) as exc:
                        log.warning("generation failed for %s (%s)", p.path_id, type(exc).__name__)
                        report.failed += 1
                if result is None:
                    if language.split("-")[0] not in TEMPLATE_LANGUAGES:
                        continue
                    text = template_explanation(data, role, language)
                    result = Explanation(
                        text,
                        list(dict.fromkeys(data.edge_ids)),
                        reading_grade(text, language),
                        generated_by="template",
                    )
                    report.template += 1
                async with user_transaction(None) as db:
                    await store_explanation(db, data, lens, result)
    print(
        f"paths={report.paths} skipped={report.skipped} model={report.model} "
        f"template={report.template} failed={report.failed}"
        + (
            f" unsupported_language={','.join(report.unsupported_language)}"
            if report.unsupported_language
            else ""
        ),
        file=out,
    )
    return report


DEMO_VERSION_PREFIX = "demo-"
DEMO_TYPES = ("trial", "paper", "grant", "patient_org")
DEMO_RELATIONS = ("about", "studies", "funds_research_on", "serves")
_MONDO_ID = re.compile(r"^MONDO:\d{7}$")


def _host_is_loopback(url: str) -> bool:
    from urllib.parse import urlsplit

    from backend.config import is_loopback_url

    host = urlsplit(url).hostname or ""
    return is_loopback_url(f"http://{host}") if host else False


def demo_graph_changes(disease_id: str, *, clear: bool = False, out=sys.stdout) -> list[dict]:
    """Insert (or with clear=True delete) demo graph_changes rows; see the module docstring."""
    import psycopg
    from psycopg.rows import dict_row

    from backend.config import get_settings, is_loopback_url

    settings = get_settings()
    if not is_loopback_url(settings.api_url):
        raise SystemExit("refusing: API_URL is not a loopback address (demo data is local only)")
    if not _host_is_loopback(settings.pipeline_database_url):
        raise SystemExit("refusing: the pipeline database is not on a loopback address")
    url = settings.pipeline_database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url, row_factory=dict_row) as conn:
        if clear:
            n = conn.execute(
                "DELETE FROM graph_changes WHERE data_version LIKE %s",
                (DEMO_VERSION_PREFIX + "%",),
            ).rowcount
            print(f"demo graph_changes deleted: {n}", file=out)
            return []
        if not _MONDO_ID.match(disease_id):
            raise SystemExit("not a disease id (MONDO:0000000)")
        disease = conn.execute(
            "SELECT id, label FROM nodes WHERE id = %s AND type = 'disease'", (disease_id,)
        ).fetchone()
        if disease is None:
            raise SystemExit("no such disease in the atlas")
        linked = conn.execute(
            """
            SELECT DISTINCT ON (n.type) n.id, n.type, n.label, n.attrs->>'status' AS status,
                   e.id AS edge_id
              FROM edges e JOIN nodes n ON n.id = e.source_id
             WHERE e.target_id = %s AND e.relation = ANY(%s) AND n.type = ANY(%s)
             ORDER BY n.type, n.id DESC
            """,
            (disease_id, list(DEMO_RELATIONS), list(DEMO_TYPES)),
        ).fetchall()
        if not linked:
            raise SystemExit("this disease has no papers, trials, grants or patient groups")
        row = conn.execute(
            "SELECT data_version FROM ingestion_runs ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        previous = row["data_version"] if row else None
        version = DEMO_VERSION_PREFIX + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        rows = [
            {"node_id": n["id"], "node_type": n["type"], "change": "added", "edge_id": n["edge_id"]}
            for n in linked
        ]
        rows += [
            {
                "node_id": n["id"],
                "node_type": n["type"],
                "change": "now_recruiting",
                "edge_id": n["edge_id"],
            }
            for n in linked
            if n["type"] == "trial" and (n["status"] or "").lower() == "recruiting"
        ]
        for r in rows:
            conn.execute(
                "INSERT INTO graph_changes (data_version, previous_version, disease_id, node_id,"
                " node_type, change, edge_id) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    version,
                    previous,
                    disease_id,
                    r["node_id"],
                    r["node_type"],
                    r["change"],
                    r["edge_id"],
                ),
            )
    print(f"DEMO DATA: {len(rows)} graph_changes rows for {disease_id} ({version})", file=out)
    for r in rows:
        print(f"  {r['change']:<15} {r['node_type']:<12} {r['node_id']}", file=out)
    return rows


def _run(coro):
    from backend.db.session import configure_engine, dispose_engine

    async def _main():
        configure_engine()
        try:
            return await coro
        finally:
            await dispose_engine()

    return asyncio.run(_main())


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("presidio-analyzer").setLevel(logging.ERROR)
    parser = argparse.ArgumentParser(prog="python -m backend.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    pre = sub.add_parser("precompute-explanations", help="Fill explanations_cache for demo paths")
    pre.add_argument("--language", action="append", help="Output language (repeatable)")
    pre.add_argument("--limit", type=int, default=12, help="Number of demo paths (default 12)")
    mode = pre.add_mutually_exclusive_group()
    mode.add_argument("--template", action="store_true", help="Never call the LLM")
    mode.add_argument("--llm", action="store_true", help="Require the CLI ChatGPT login")

    ev = sub.add_parser("eval", help="Run the agent evaluation harness")
    ev.add_argument("--mock", action="store_true", help="Use the local mock OpenAI server")
    ev.add_argument(
        "--only",
        help="Comma-separated checks: golden,citations,inference,readability,refusal,redaction",
    )
    ev.add_argument("--limit", type=int, default=None, help="Max golden questions")

    demo = sub.add_parser(
        "demo-graph-changes",
        help="DEMO DATA, local only: insert sample graph_changes rows for one disease",
        description="DEMO DATA for local development: inserts sample graph_changes rows (data "
        "version demo-<time>) for a disease, as if a new load had linked its existing papers, "
        "trials, grants and patient groups, so users who follow it get notifications. Follow the "
        "disease first. Refuses to run unless API_URL and the pipeline database are loopback "
        "addresses. Writes as atlas_pipeline (PIPELINE_DATABASE_URL).",
    )
    demo.add_argument("disease_id", nargs="?", help="Disease ID, e.g. MONDO:0100135")
    demo.add_argument("--clear", action="store_true", help="Delete every demo row instead")

    args = parser.parse_args(argv)
    if args.command == "demo-graph-changes":
        if not args.clear and not args.disease_id:
            parser.error("disease_id is required unless --clear is given")
        demo_graph_changes(args.disease_id or "", clear=args.clear)
        return 0
    if args.command == "precompute-explanations":
        use_llm = False if args.template else (True if args.llm else None)
        report = _run(
            precompute_explanations(args.language or ["en"], limit=args.limit, use_llm=use_llm)
        )
        return 0 if report.failed == 0 or report.template else 1
    if args.command == "eval":
        from backend.evals.runner import run_cli

        only = [c.strip() for c in args.only.split(",")] if args.only else None
        return _run(run_cli(mock=args.mock, only=only, limit=args.limit))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
