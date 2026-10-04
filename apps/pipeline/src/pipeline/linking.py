"""Stage 2 (end): LLM-assisted linking of leftover disease references to MONDO.

Leftovers are OMIM/Orphanet diseases associated with an in-scope gene that MONDO's exact
matches do not map. Candidates come from trigram similarity over MONDO labels and synonyms,
re-ranked by local embedding similarity; the model picks one candidate or "none" through
structured output. Every decision is logged to data/logs/linking.jsonl. Without a logged-in
LLM the leftovers are only logged.
"""

from __future__ import annotations

import importlib
import json
import logging
import re
from collections import defaultdict

import polars as pl
from pydantic import BaseModel, Field

from pipeline import bio
from pipeline.contracts import Scope, assertion, now_iso, write_tables
from pipeline.paths import LOGS

log = logging.getLogger(__name__)

ACCEPT_CONFIDENCE = 0.8
N_TRIGRAM = 30
N_CANDIDATES = 5


class LinkDecision(BaseModel):
    choice: str = Field(description="The chosen candidate MONDO id, or 'none'")
    confidence: float = Field(ge=0, le=1)
    reason: str


def trigrams(s: str) -> set[str]:
    s = "  " + re.sub(r"[^a-z0-9]+", " ", s.lower()).strip() + " "
    return {s[i : i + 3] for i in range(len(s) - 2)}


def trigram_sim(a: str, b: str) -> float:
    ta, tb = trigrams(a), trigrams(b)
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


def leftovers(scope: Scope) -> list[dict]:
    x2m = bio.xref_to_mondo()
    found: dict[str, dict] = {}
    genes = scope.gene_ids
    for r in bio.orphanet_genes().iter_rows(named=True):
        if (
            r["hgnc_id"] in genes
            and r["orpha"] not in x2m
            and r["assoc_type"] in bio.CAUSAL_ORPHA_TYPES
        ):
            found.setdefault(r["orpha"], {"id": r["orpha"], "name": r["name"], "genes": set()})
            found[r["orpha"]]["genes"].add(r["hgnc_id"])
    names = dict(bio.hpoa().select("disease_id", "disease_name").unique("disease_id").iter_rows())
    e2h = bio.entrez_to_hgnc()
    for r in bio.hpo_gene_disease().iter_rows(named=True):
        hid = e2h.get(r["entrez_id"])
        if hid in genes and r["disease_id"] not in x2m and r["disease_id"] in names:
            d = found.setdefault(
                r["disease_id"],
                {"id": r["disease_id"], "name": names[r["disease_id"]], "genes": set()},
            )
            d["genes"].add(hid)
    return list(found.values())


def candidates(name: str, pool: list[tuple[str, str]], embed=None) -> list[dict]:
    scored = sorted(((trigram_sim(name, label), mid, label) for mid, label in pool), reverse=True)
    best: dict[str, tuple[float, str]] = {}
    for s, mid, label in scored:
        if mid not in best:
            best[mid] = (s, label)
        if len(best) >= N_TRIGRAM:
            break
    items = [{"mondo_id": m, "label": lbl, "trigram": round(s, 3)} for m, (s, lbl) in best.items()]
    if embed is not None and items:
        vecs = embed([name] + [i["label"] for i in items])
        sims = vecs[1:] @ vecs[0]
        for i, s in zip(items, sims, strict=True):
            i["embedding"] = round(float(s), 3)
        items.sort(key=lambda i: -(i["trigram"] + i["embedding"]) / 2)
    return items[:N_CANDIDATES]


def _get_llm():
    try:
        return importlib.import_module("pipeline.llm").get_llm()
    except Exception as exc:  # noqa: BLE001 - missing module or no login both mean "no LLM"
        log.info("linking: no LLM available (%s)", exc.__class__.__name__)
        return None


def _embedder():
    try:
        from backend.embeddings import embed_texts

        return embed_texts
    except Exception:  # noqa: BLE001
        return None


async def run(scope: Scope) -> None:
    scope = scope.focus()  # model-assisted linking stays with the focus set
    items = leftovers(scope)
    LOGS.mkdir(parents=True, exist_ok=True)
    log_path = LOGS / "linking.jsonl"
    terms = bio.mondo_terms().filter(~pl.col("deprecated"))
    pool = [(mid, label) for mid, label in terms.select("id", "label").iter_rows() if label]
    for mid, syns in terms.select("id", "exact_synonyms").iter_rows():
        pool += [(mid, s) for s in syns]
    llm = _get_llm() if items else None
    embed = _embedder()
    decisions, rows = [], []
    for item in items:
        cands = candidates(item["name"], pool, embed)
        decision: dict = {
            "at": now_iso(),
            "id": item["id"],
            "name": item["name"],
            "genes": sorted(item["genes"]),
            "candidates": cands,
        }
        chosen = None
        if cands and cands[0]["trigram"] >= 0.95:
            chosen, decision["method"], decision["confidence"] = (
                cands[0]["mondo_id"],
                "exact_label",
                1.0,
            )
        elif llm is None:
            decision["method"] = "skipped_no_llm"
        else:
            try:
                out = await llm.structured(
                    LinkDecision,
                    instructions=(
                        "You map a rare disease name to the matching MONDO disease. Pick the "
                        "candidate that denotes the same disease (not a broader or narrower one), "
                        "or 'none'. Answer with the MONDO id."
                    ),
                    input=json.dumps(
                        {"disease": item["name"], "source_id": item["id"], "candidates": cands}
                    ),
                )
                decision.update(
                    method="llm", choice=out.choice, confidence=out.confidence, reason=out.reason
                )
                valid = {c["mondo_id"] for c in cands}
                if out.choice in valid and out.confidence >= ACCEPT_CONFIDENCE:
                    chosen = out.choice
            except Exception as exc:  # noqa: BLE001
                decision.update(method="llm_error", error=str(exc)[:200])
        decision["accepted"] = chosen
        decisions.append(decision)
        if chosen and chosen in scope.disease_ids:
            for hid in item["genes"]:
                rows.append(
                    assertion(
                        chosen,
                        hid,
                        "caused_by_variant_in",
                        tier="curated_db",
                        source_type="orphanet" if item["id"].startswith("ORPHA") else "hpo",
                        source_ref=item["id"],
                        url=None,
                        quote=(
                            f"{item['name']} ({item['id']}) linked to {chosen} "
                            f"({decision['method']})"
                        ),
                        origin="observed" if decision["method"] == "exact_label" else "inferred",
                        features={
                            "linked_by": decision["method"],
                            "link_confidence": decision.get("confidence"),
                            "candidate": cands[0] if cands else None,
                            "weight": 0.9 * float(decision.get("confidence") or 0),
                        },
                    )
                )
    with log_path.open("w") as f:
        for d in decisions:
            f.write(json.dumps(d) + "\n")
    counts: dict[str, int] = defaultdict(int)
    for d in decisions:
        counts[d["method"]] += 1
    log.info("linking: %d leftovers %s, %d assertions", len(items), dict(counts), len(rows))
    write_tables("linking", [], [], rows)
