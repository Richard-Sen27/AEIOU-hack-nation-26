"""Stage 6: the build fails unless every check passes. Report: data/graph/final/validation.json."""

from __future__ import annotations

import json
import logging
from typing import Any

import polars as pl
from backend.schemas.enums import (
    CONFIDENCE_THRESHOLD,
    RELATION_FAMILY,
    EdgeStatus,
    EvidenceTier,
    NodeType,
    Origin,
    Relation,
    edge_id,
)

from pipeline import bio, taxonomy
from pipeline.build import FINAL, read_graph
from pipeline.paths import EXTRACTED
from pipeline.scope import load_seeds

log = logging.getLogger(__name__)


def _resolver(nodes: pl.DataFrame, synonyms: pl.DataFrame):
    by_label: dict[str, str] = {}
    types = dict(nodes.select("id", "type").iter_rows())
    for nid, label in nodes.select("id", "label").iter_rows():
        by_label.setdefault((label or "").lower(), nid)
    for nid, syn in synonyms.select("node_id", "synonym").iter_rows():
        if types.get(nid) == "disease":
            by_label.setdefault(syn.lower(), nid)

    def resolve(name: str) -> str | None:
        if name in types:
            return name
        if name.upper().startswith("MONDO:") and name.upper() in types:
            return name.upper()
        hid = bio.resolve_gene(name) if name.isupper() or name.startswith("HGNC:") else None
        if hid and hid in types:
            return hid
        return by_label.get(name.lower())

    return resolve


def check_structure(t: dict[str, pl.DataFrame]) -> list[dict[str, Any]]:
    nodes, edges, evidence = t["nodes"], t["edges"], t["evidence"]
    ids = set(nodes["id"].to_list())
    results = []

    def add(name, ok, detail=None):
        results.append({"check": name, "ok": bool(ok), "detail": detail})

    with_ev = set(evidence["edge_id"].to_list())
    missing = [e for e in edges["id"].to_list() if e not in with_ev]
    add(
        "every edge has evidence",
        not missing,
        {"edges_without_evidence": missing[:20], "n": len(missing)},
    )
    used = set(edges["source_id"].to_list()) | set(edges["target_id"].to_list())
    orphans = nodes.filter(~pl.col("id").is_in(list(used)) & (pl.col("type") != "cluster"))
    add(
        "no orphan nodes",
        orphans.height == 0,
        {"orphans": orphans["id"].head(20).to_list(), "n": orphans.height},
    )
    dangling = edges.filter(
        ~pl.col("source_id").is_in(list(ids)) | ~pl.col("target_id").is_in(list(ids))
    )
    add("edge endpoints exist", dangling.height == 0, {"n": dangling.height})
    stray = evidence.filter(~pl.col("edge_id").is_in(edges["id"].to_list()))
    add("evidence points at edges", stray.height == 0, {"n": stray.height})
    add("unique edge ids", edges["id"].n_unique() == edges.height)
    add("unique node ids", nodes["id"].n_unique() == nodes.height)
    bad_ids = [
        r["id"]
        for r in edges.select("id", "source_id", "relation", "target_id").iter_rows(named=True)
        if r["id"] != edge_id(r["source_id"], r["relation"], r["target_id"])
    ]
    add("deterministic edge ids", not bad_ids, {"n": len(bad_ids)})
    enums_ok = (
        set(nodes["type"].unique().to_list()) <= set(NodeType.__members__)
        and set(edges["relation"].unique().to_list()) <= set(Relation.__members__)
        and set(edges["origin"].unique().to_list()) <= set(Origin.__members__)
        and set(edges["status"].unique().to_list()) <= set(EdgeStatus.__members__)
        and set(evidence["tier"].unique().to_list()) <= set(EvidenceTier.__members__)
    )
    add("enum values valid", enums_ok)
    fam_ok = all(
        RELATION_FAMILY[Relation(r)].value == f
        for r, f in edges.select("relation", "family").unique().iter_rows()
    )
    add("edge family matches relation", fam_ok)
    conf = edges["confidence"]
    add("confidence within 0..1", bool(((conf >= 0) & (conf <= 1)).all()))
    inferred_no_feat = edges.filter((pl.col("origin") == "inferred") & pl.col("features").is_null())
    add(
        "inferred edges carry features",
        inferred_no_feat.height == 0,
        {"n": inferred_no_feat.height},
    )
    clustered = nodes.filter((pl.col("type") == "disease") & pl.col("cluster_id").is_null())
    add("every disease has a cluster", clustered.height == 0, {"n": clustered.height})
    results += check_positions(nodes)
    results += check_lineage(nodes)
    return results


def _attrs_by_id(nodes: pl.DataFrame, node_type: str) -> dict[str, dict]:
    sub = nodes.filter(pl.col("type") == node_type)
    if "attrs" not in sub.columns:
        return {nid: {} for nid in sub["id"].to_list()}
    return {
        nid: (json.loads(a) if a else {})
        for nid, a in zip(sub["id"].to_list(), sub["attrs"].to_list(), strict=True)
    }


def _well_formed_span(a: dict, end_key: str) -> bool:
    start, end = a.get("start"), a.get(end_key)
    return (
        isinstance(a.get("chromosome"), str)
        and isinstance(start, int)
        and isinstance(end, int)
        and 0 < start <= end
        and bool(a.get("assembly"))
    )


def check_positions(nodes: pl.DataFrame) -> list[dict[str, Any]]:
    """Genes and variants either carry a well-formed GRCh38 position or are listed as missing.

    Missing positions are reported, not failed (MANE has no coordinates for some loci, ClinVar
    for some records); a position that is present but malformed fails the check.
    """
    out = []
    for node_type, end_key, label in (
        ("gene", "end", "every gene has coordinates or is listed as missing"),
        ("variant", "stop", "every variant has a position or is listed as missing"),
    ):
        attrs = _attrs_by_id(nodes, node_type)
        missing = sorted(
            (a.get("symbol") or nid) if node_type == "gene" else nid
            for nid, a in attrs.items()
            if a.get("start") is None
        )
        malformed = sorted(
            nid
            for nid, a in attrs.items()
            if a.get("start") is not None and not _well_formed_span(a, end_key)
        )
        out.append(
            {
                "check": label,
                "ok": not malformed,
                "detail": {
                    "n": len(attrs),
                    "with_position": len(attrs) - len(missing) - len(malformed),
                    "missing": missing,
                    "malformed": malformed[:20],
                },
            }
        )
    return out


def check_lineage(nodes: pl.DataFrame) -> list[dict[str, Any]]:
    """Every phenotype carries an hpo_lineage that starts at an organ system and follows is_a."""
    lineages = {nid: a.get("hpo_lineage") for nid, a in _attrs_by_id(nodes, "phenotype").items()}
    problems = taxonomy.lineage_problems(lineages) if lineages else {}
    missing = problems.get("missing", [])
    bad_root = problems.get("bad_root", [])
    broken = problems.get("broken_path", [])
    return [
        {
            "check": "every phenotype has an hpo_lineage",
            "ok": not missing,
            "detail": {"missing": missing[:20], "n": len(missing)},
        },
        {
            "check": "hpo_lineage starts at an organ system and follows is_a",
            "ok": not bad_root and not broken,
            "detail": {
                "bad_root": bad_root[:20],
                "broken_path": broken[:20],
                "n": len(bad_root) + len(broken),
                "empty": len(problems.get("empty", [])),
            },
        },
    ]


def check_golden(t, resolve, golden: list[dict]) -> list[dict[str, Any]]:
    edges = t["edges"]
    conf = {r[0]: r[1] for r in edges.select("id", "confidence").iter_rows()}
    out = []
    for g in golden:
        s, tg = resolve(g["source"]), resolve(g["target"])
        detail = {"fact": g, "source_id": s, "target_id": tg}
        if not s or not tg:
            out.append(
                {
                    "check": f"golden: {g['source']} {g['relation']} {g['target']}",
                    "ok": False,
                    "detail": detail,
                }
            )
            continue
        eid = edge_id(s, g["relation"], tg)
        c = conf.get(eid)
        detail |= {"edge_id": eid, "confidence": c}
        ok = c is not None and c >= CONFIDENCE_THRESHOLD
        out.append(
            {
                "check": f"golden: {g['source']} {g['relation']} {g['target']}",
                "ok": ok,
                "detail": detail,
            }
        )
    return out


def check_counterexamples(t, resolve, cases: list[dict]) -> list[dict[str, Any]]:
    nodes, edges = t["nodes"], t["edges"]
    cluster = dict(nodes.select("id", "cluster_id").iter_rows())
    sgdm = set(
        tuple(sorted(p))
        for p in edges.filter(pl.col("relation") == "same_gene_different_mechanism")
        .select("source_id", "target_id")
        .iter_rows()
    )
    out = []
    for case in cases:
        gof = {n: resolve(n) for n in case.get("gain_of_function", [])}
        lof = {n: resolve(n) for n in case.get("loss_of_function", [])}
        unresolved = [n for n, i in {**gof, **lof}.items() if not i]
        pairs = [(a, b) for a in gof.values() for b in lof.values() if a and b]
        shared = [(a, b, cluster.get(a)) for a, b in pairs if cluster.get(a) == cluster.get(b)]
        linked = [p for p in pairs if tuple(sorted(p)) in sgdm]
        ok = not unresolved and pairs and not shared and linked
        out.append(
            {
                "check": (
                    f"counterexample: {case['gene']} gain- vs loss-of-function "
                    "in different clusters"
                ),
                "ok": bool(ok),
                "detail": {
                    "gain_of_function": {n: [i, cluster.get(i)] for n, i in gof.items()},
                    "loss_of_function": {n: [i, cluster.get(i)] for n, i in lof.items()},
                    "unresolved": unresolved,
                    "same_cluster_pairs": shared,
                    "same_gene_different_mechanism_edges": len(linked),
                },
            }
        )
    return out


def _report_counts(r: dict[str, Any]) -> tuple[int, int, int]:
    """(checked, passed, rejected) from a Stage 3 report.json or quote_report.json."""
    if "checked" in r:
        return r.get("checked", 0), r.get("passed", 0), r.get("rejected", 0)
    rejected = r.get("rejected") or {}
    n_rej = sum(rejected.values()) if isinstance(rejected, dict) else int(rejected)
    accepted = r.get("accepted", 0) or 0
    return accepted + n_rej, accepted, n_rej


def quote_reports() -> dict[str, Any]:
    reports = {}
    if EXTRACTED.exists():
        for p in sorted(EXTRACTED.glob("*/report.json")) + sorted(
            EXTRACTED.glob("*/quote_report.json")
        ):
            reports.setdefault(p.parent.name, json.loads(p.read_text()))
    totals = [_report_counts(r) for r in reports.values()]
    checked = sum(t[0] for t in totals)
    passed = sum(t[1] for t in totals)
    return {
        "by_extractor": reports,
        "checked": checked,
        "passed": passed,
        "rejected": sum(t[2] for t in totals),
        "pass_rate": round(passed / checked, 4) if checked else None,
        "statuses": {k: r.get("status") for k, r in reports.items()},
    }


def run() -> bool:
    t = read_graph(FINAL)
    seeds = load_seeds().get("validation", {})
    resolve = _resolver(t["nodes"], t["synonyms"])
    results = check_structure(t)
    results += check_golden(t, resolve, seeds.get("golden", []))
    results += check_counterexamples(t, resolve, seeds.get("counterexamples", []))
    quotes = quote_reports()
    report = {
        "data_version": t["nodes"]["data_version"][0],
        "ok": all(r["ok"] for r in results),
        "checks": results,
        "quote_verification": quotes,
    }
    (FINAL / "validation.json").write_text(json.dumps(report, indent=1, default=str))
    for r in results:
        (log.info if r["ok"] else log.error)("%s %s", "PASS" if r["ok"] else "FAIL", r["check"])
        if not r["ok"]:
            log.error("    %s", json.dumps(r["detail"], default=str)[:600])
    if quotes["checked"]:
        log.info(
            "quote verification: %d/%d passed (%.1f%%), %d rejected",
            quotes["passed"],
            quotes["checked"],
            100 * quotes["pass_rate"],
            quotes["rejected"],
        )
    else:
        log.info("quote verification: nothing checked (Stage 3 status: %s)", quotes["statuses"])
    return report["ok"]
