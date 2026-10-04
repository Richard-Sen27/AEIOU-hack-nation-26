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
from pipeline.build import FINAL, inferred_cap, read_graph
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
    results += check_inferred(t)
    return results


# Inferred relations that must never sit on a "supported" route (their cap is below 0.6).
WEAK_HYPOTHESES = ("near_on_chromosome", "candidate_phenotype", "suggested_by_neighbour")


def _explanation_ok(text: object) -> bool:
    return isinstance(text, str) and bool(text.strip()) and "\n" not in text and len(text) <= 400


def check_inferred(t: dict[str, pl.DataFrame], summary: dict | None = None) -> list[dict[str, Any]]:
    """Every inferred edge explains itself in one line, stays within its relation's cap and is
    backed by computed hypothesis rows; weak hypotheses stay below the supported threshold; the
    symptom similarity threshold was calibrated against random pairs."""
    edges, evidence = t["edges"], t["evidence"]
    inf = edges.filter(pl.col("origin") == "inferred")
    no_expl, no_meta, over_cap, weak_supported = [], [], [], []
    for eid, rel, conf, feats in inf.select("id", "relation", "confidence", "features").iter_rows():
        f = json.loads(feats) if feats else {}
        if not _explanation_ok(f.get("explanation")):
            no_expl.append(eid)
        if not (isinstance(f.get("method"), str) and isinstance(f.get("confidence_basis"), str)):
            no_meta.append(eid)
        if conf > inferred_cap(rel) + 1e-9:
            over_cap.append(eid)
        if rel in WEAK_HYPOTHESES and conf >= CONFIDENCE_THRESHOLD:
            weak_supported.append(eid)
    inf_ids = inf["id"].to_list()
    rows = evidence.filter(pl.col("edge_id").is_in(inf_ids))
    if "claim_type" not in rows.columns:
        rows = rows.with_columns(pl.lit(None, dtype=pl.String).alias("claim_type"))
    bad_rows = rows.filter(
        (pl.col("tier") != "computed") | (pl.col("claim_type") != "hypothesis").fill_null(True)
    )
    if summary is None:
        f = FINAL / "summary.json"
        summary = json.loads(f.read_text()) if f.exists() else {}
    cal = summary.get("similar_symptoms_calibration") or {}
    has_sim = inf.filter(pl.col("relation") == "similar_symptoms").height > 0
    cal_ok = not has_sim or (
        isinstance(cal.get("threshold_percentile_random"), int | float)
        and cal.get("threshold", 0) >= cal.get("random_p95", 1)
    )
    return [
        {
            "check": "every inferred edge has a one-line explanation, method and confidence basis",
            "ok": not no_expl and not no_meta,
            "detail": {
                "n": inf.height,
                "missing_explanation": no_expl[:20],
                "missing_method_or_basis": no_meta[:20],
            },
        },
        {
            "check": "inferred edges stay within their relation's confidence cap",
            "ok": not over_cap,
            "detail": {"over_cap": over_cap[:20], "n": len(over_cap)},
        },
        {
            "check": "inferred edges are backed by computed hypothesis evidence only",
            "ok": bad_rows.height == 0,
            "detail": {"n": bad_rows.height, "edges": bad_rows["edge_id"].head(20).to_list()},
        },
        {
            "check": "no proximity or candidate link can sit on a supported path",
            "ok": not weak_supported,
            "detail": {"edges": weak_supported[:20], "n": len(weak_supported)},
        },
        {
            "check": "symptom similarity threshold calibrated against random pairs",
            "ok": bool(cal_ok),
            "detail": cal,
        },
    ]


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


def check_core(t: dict[str, pl.DataFrame], min_qualified: int | None) -> list[dict[str, Any]]:
    """Wide core: enough diseases with a gene and a symptom, a tier on every disease, gene and
    phenotype node, and the HPO term table covering every phenotype node."""
    nodes, edges = t["nodes"], t["edges"]
    out = []
    if min_qualified:
        with_gene = set(
            edges.filter(pl.col("relation") == "caused_by_variant_in")["source_id"].to_list()
        )
        with_phen = set(edges.filter(pl.col("relation") == "has_phenotype")["source_id"].to_list())
        diseases = set(nodes.filter(pl.col("type") == "disease")["id"].to_list())
        n = len(diseases & with_gene & with_phen)
        out.append(
            {
                "check": f"at least {min_qualified} diseases with a gene and a recorded symptom",
                "ok": n >= min_qualified,
                "detail": {"n": n, "diseases": len(diseases)},
            }
        )
    tiers: dict[str, dict[str, int]] = {}
    bad = []
    for nid, typ, attrs in nodes.select("id", "type", "attrs").iter_rows():
        if typ not in ("disease", "gene", "phenotype"):
            continue
        tier = (json.loads(attrs) if attrs else {}).get("tier")
        if tier not in ("focus", "core"):
            bad.append(nid)
        tiers.setdefault(typ, {}).setdefault(str(tier), 0)
        tiers[typ][str(tier)] += 1
    out.append(
        {
            "check": "every disease, gene and phenotype has attrs.tier focus or core",
            "ok": not bad,
            "detail": {"by_type": tiers, "missing": bad[:20], "n": len(bad)},
        }
    )
    hpo = t.get("hpo_terms")
    if hpo is not None:
        phen = set(nodes.filter(pl.col("type") == "phenotype")["id"].to_list())
        missing = sorted(phen - set(hpo["id"].to_list()))
        out.append(
            {
                "check": "hpo_terms export covers every phenotype node",
                "ok": not missing and hpo.height > 0,
                "detail": {"rows": hpo.height, "missing": missing[:20], "n": len(missing)},
            }
        )
    return out


def lineage_fanout(lineages: dict[str, list]) -> tuple[int, int]:
    """(first-level groups, largest number of children of any group) of the tree the lineages
    span, after splicing single-child chains as the Atlas does; clusters are the leaves."""
    kids: dict[str, set[str]] = {}
    for cid, lin in lineages.items():
        path = ["", *(g["id"] for g in lin), cid]
        for a, b in zip(path, path[1:], strict=False):
            kids.setdefault(a, set()).add(b)

    def children(node: str) -> set[str]:
        out = set()
        for k in kids.get(node, ()):
            while len(kids.get(k, ())) == 1:
                k = next(iter(kids[k]))
            out.add(k)
        return out

    return len(children("")), max((len(children(k)) for k in kids), default=0)


def check_cluster_lineage(t: dict[str, pl.DataFrame], max_roots: int | None) -> list[dict]:
    """Every cluster carries attrs.lineage (organ system down to its parent group), and the
    clusters holding focus diseases start from at most ``max_roots`` first-level groups."""
    nodes = t["nodes"]
    tier = {
        nid: (json.loads(a) if a else {}).get("tier")
        for nid, a in nodes.filter(pl.col("type") == "disease").select("id", "attrs").iter_rows()
    }
    lineages: dict[str, list] = {}
    focus: dict[str, list] = {}
    bad = []
    for cid, attrs in nodes.filter(pl.col("type") == "cluster").select("id", "attrs").iter_rows():
        a = json.loads(attrs) if attrs else {}
        lin = a.get("lineage")
        if (
            not isinstance(lin, list)
            or not lin
            or not all(isinstance(g, dict) and g.get("id") and g.get("label") for g in lin)
        ):
            bad.append(cid)
            continue
        lineages[cid] = lin
        if any(tier.get(m) == "focus" for m in a.get("members", [])):
            focus[cid] = lin
    f_roots, f_max = lineage_fanout(focus)
    a_roots, a_max = lineage_fanout(lineages)
    out = [
        {
            "check": "every cluster has a lineage",
            "ok": not bad,
            "detail": {"clusters": len(lineages) + len(bad), "missing": bad[:20], "n": len(bad)},
        }
    ]
    if max_roots:
        out.append(
            {
                "check": f"clusters with focus diseases start from at most {max_roots} groups",
                "ok": f_roots <= max_roots,
                "detail": {
                    "focus_clusters": len(focus),
                    "focus_first_level": f_roots,
                    "focus_max_children": f_max,
                    "all_first_level": a_roots,
                    "all_max_children": a_max,
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
    results += check_core(t, seeds.get("min_qualified_diseases"))
    results += check_cluster_lineage(t, seeds.get("max_focus_cluster_roots"))
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
