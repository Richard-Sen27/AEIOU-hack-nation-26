"""Stage 3a: relations between in-scope entities from PubMed abstracts, with verified quotes.

The model sees only the abstract and the names of in-scope entities found in it. Every proposed
relation must (1) use the fixed relation enum with the right endpoint types, (2) name entities
that resolve to in-scope ids and (3) carry a quote that occurs verbatim in the abstract after
whitespace/unicode normalization. Anything else is rejected and counted in report.json.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import Counter
from typing import Any, Literal

import polars as pl
from pydantic import BaseModel, Field

from pipeline.contracts import Scope, assertion, read_table, write_tables
from pipeline.extract.common import ScopeMatcher, fold, quote_in_text, short_hash
from pipeline.llm import LLMRun
from pipeline.paths import EXTRACTED, NORMALIZED

log = logging.getLogger(__name__)

NAME = "abstracts"
MECHANISMS = {
    "loss of function": "MECH:loss_of_function",
    "gain of function": "MECH:gain_of_function",
    "dominant negative": "MECH:dominant_negative",
}
# relation -> (subject type, object type)
RELATION_TYPES = {
    "caused_by_variant_in": ("disease", "gene"),
    "acts_via": ("gene", "mechanism"),
    "participates_in": ("gene", "pathway"),
    "has_phenotype": ("disease", "phenotype"),
}
ABOUT_TYPES = {"disease", "gene", "pathway", "phenotype"}

INSTRUCTIONS = """You extract biomedical relations from one PubMed abstract.
Use only these relations (subject -> object):
- caused_by_variant_in: disease -> gene (the disease is caused by variants in the gene)
- acts_via: gene -> mechanism (pathogenic variants act via loss of function, gain of function or
  dominant negative effect)
- participates_in: gene -> pathway
- has_phenotype: disease -> phenotype
Subject and object must be copied exactly from the entity list; never use other entities.
For each relation give `quote`: one exact, contiguous span copied character for character from the
abstract that supports or contradicts it (no paraphrase, no ellipsis). Set `polarity` to
"contradicts" if the abstract argues against the relation. `claim_type`: patient_observation
(observed in patients or cohorts), experimental (lab or animal work), review (summarizes prior
work), hypothesis (proposed, not shown). `inferred` is true when the relation is not stated in the
quote itself but only follows from it. `confidence` is 0-1. Return an empty list if nothing
qualifies."""


class ExtractedRelation(BaseModel):
    subject: str
    relation: Literal["caused_by_variant_in", "acts_via", "participates_in", "has_phenotype"]
    object: str
    quote: str
    claim_type: Literal["patient_observation", "experimental", "review", "hypothesis"]
    polarity: Literal["supports", "contradicts"]
    inferred: bool = False
    confidence: float = Field(ge=0, le=1)


class AbstractExtraction(BaseModel):
    relations: list[ExtractedRelation]


class EntityIndex:
    """In-scope names (scope + synonyms tables + pathways + mechanisms) with their ids/types."""

    def __init__(self, scope: Scope):
        syn = read_table("synonyms")
        extra = list(zip(syn["node_id"].to_list(), syn["synonym"].to_list(), strict=True))
        self.matcher = ScopeMatcher(scope, extra)
        self.types: dict[str, str] = {}
        for g in scope.genes:
            self.types[g["hgnc_id"]] = "gene"
        for d in scope.diseases:
            self.types[d["mondo_id"]] = "disease"
        for p in scope.phenotypes:
            self.types[p.get("hpo_id") or p.get("id")] = "phenotype"
        self.terms: dict[str, str] = dict(self.matcher_terms())
        nodes = read_table("nodes")
        pathways = nodes.filter(pl.col("type") == "pathway")
        for pid, label in zip(pathways["id"].to_list(), pathways["label"].to_list(), strict=True):
            if label and len(fold(label).split()) >= 2:
                self.terms.setdefault(fold(label), pid)
                self.types[pid] = "pathway"
        for name, mid in MECHANISMS.items():
            self.terms[name] = mid
            self.types[mid] = "mechanism"
        self.gene_symbols = {g["symbol"]: g["hgnc_id"] for g in scope.genes}
        for g in scope.genes:
            for a in g.get("aliases") or []:
                if fold(a) in self.terms and len(a) >= 4:
                    self.gene_symbols.setdefault(a, g["hgnc_id"])

    def matcher_terms(self):
        for term, ids in self.matcher.terms.items():
            node_id = next(iter(ids))
            if node_id in self.types:
                yield term, node_id

    def candidates(self, text: str) -> dict[str, str]:
        """Surface name -> id for every in-scope entity mentioned in the text."""
        found: dict[str, str] = {}
        for sym, gid in self.gene_symbols.items():
            if re.search(rf"(?<![A-Za-z0-9]){re.escape(sym)}(?![A-Za-z0-9])", text):
                found[sym] = gid
        padded = f" {fold(text)} "
        for term, node_id in self.terms.items():
            if len(term) >= 4 and self.types.get(node_id) != "gene" and f" {term} " in padded:
                found[term] = node_id
        # Keep the longest surface name per id.
        best: dict[str, str] = {}
        for name, node_id in found.items():
            if node_id not in best or len(name) > len(best[node_id]):
                best[node_id] = name
        return {name: node_id for node_id, name in best.items()}

    def resolve(self, name: str, candidates: dict[str, str]) -> str | None:
        name = re.sub(r"\s*\((gene|disease|phenotype|pathway|mechanism)\)\s*$", "", name.strip())
        if name in candidates:
            return candidates[name]
        f = fold(name)
        for cand, node_id in candidates.items():
            if fold(cand) == f:
                return node_id
        return None


def _entity_list(candidates: dict[str, str], index: EntityIndex) -> list[str]:
    return sorted(f"{name} ({index.types[node_id]})" for name, node_id in candidates.items())


def validate(
    rel: ExtractedRelation, abstract: str, candidates: dict[str, str], index: EntityIndex
) -> tuple[str | None, str | None, str | None]:
    """(subject_id, object_id, None) if accepted, else (None, None, rejection reason)."""
    if rel.relation not in RELATION_TYPES:
        return None, None, "invalid_relation"
    s = index.resolve(rel.subject, candidates)
    o = index.resolve(rel.object, candidates)
    if not s or not o:
        return None, None, "unresolved_entity"
    if (index.types.get(s), index.types.get(o)) != RELATION_TYPES[rel.relation]:
        return None, None, "wrong_types"
    if not quote_in_text(rel.quote, abstract):
        return None, None, "quote_not_found"
    return s, o, None


def _empty_report(reason: str, **extra) -> dict[str, Any]:
    return {
        "status": reason,
        "attempted": 0,
        "accepted": 0,
        "rejected": {},
        "pass_rate": None,
        **extra,
    }


async def run(scope: Scope, llm: LLMRun) -> dict[str, Any]:
    out = EXTRACTED / NAME
    out.mkdir(parents=True, exist_ok=True)
    src = NORMALIZED / "pubmed" / "abstracts.parquet"
    if not src.exists():
        write_tables(NAME, stage="extracted")
        report = _empty_report("skipped_no_abstracts", **llm.summary())
        (out / "report.json").write_text(json.dumps(report, indent=1))
        log.warning("abstracts: no PubMed abstracts; extraction skipped")
        return report

    papers = pl.read_parquet(src).filter(pl.col("abstract").str.len_chars() > 0)
    index = EntityIndex(scope)
    seeds = {g["hgnc_id"] for g in scope.genes if g.get("seed")}
    seeds |= {d["mondo_id"] for d in scope.diseases if d.get("seed")}

    work = []
    too_few = 0
    for row in papers.iter_rows(named=True):
        cands = index.candidates(row["abstract"])
        types = {index.types[i] for i in cands.values()}
        if not any(a in types and b in types for a, b in RELATION_TYPES.values()):
            too_few += 1
            continue
        about = set(json.loads(row["about_ids"] or "[]"))
        work.append((0 if about & seeds else 1, -(row["year"] or 0), row, cands))
    work.sort(key=lambda w: (w[0], w[1], w[2]["pmid"]))

    async def one(row, cands):
        payload = json.dumps(
            {"entities": _entity_list(cands, index), "abstract": row["abstract"]},
            ensure_ascii=False,
        )
        result = await llm.structured(
            AbstractExtraction, instructions=INSTRUCTIONS, input=payload, kind="small"
        )
        return row, cands, result

    results = await asyncio.gather(*(one(row, cands) for _, _, row, cands in work))

    nodes: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    rejected: Counter = Counter()
    attempted = accepted = processed = dropped_inferred = 0
    for row, cands, result in results:
        if result is None:
            continue
        processed += 1
        pmid, pid = row["pmid"], f"PMID:{row['pmid']}"
        for rel in result.relations:
            if rel.inferred:
                # Not stated in the quote itself: kept out of the graph entirely.
                dropped_inferred += 1
                continue
            attempted += 1
            s, o, reason = validate(rel, row["abstract"], cands, index)
            if reason:
                rejected[reason] += 1
                continue
            accepted += 1
            tier = "llm_inferred" if rel.inferred else row["tier"]
            claim_id = f"CLAIM:{short_hash(pmid, s, rel.relation, o, rel.quote, n=16)}"
            label = f"{_name(cands, s)} {rel.relation.replace('_', ' ')} {_name(cands, o)}"
            nodes.append(
                {
                    "id": claim_id,
                    "type": "claim",
                    "label": label,
                    "description": rel.quote,
                    "url": row["url"],
                    "attrs": json.dumps(
                        {
                            "pmid": pmid,
                            "relation": rel.relation,
                            "subject": s,
                            "object": o,
                            "claim_type": rel.claim_type,
                            "polarity": rel.polarity,
                            "confidence": rel.confidence,
                            "inferred": rel.inferred,
                        }
                    ),
                }
            )
            common = dict(
                source_type="pubmed",
                source_ref=pmid,
                url=row["url"],
                quote=rel.quote,
                retrieved_at=row["retrieved_at"],
                claim_type=rel.claim_type,
            )
            rows.append(assertion(pid, claim_id, "asserts", tier=row["tier"], **common))
            for target in (s, o):
                if index.types.get(target) in ABOUT_TYPES:
                    rows.append(assertion(claim_id, target, "about", tier=row["tier"], **common))
            rows.append(
                assertion(
                    s,
                    o,
                    rel.relation,
                    tier=tier,
                    origin="inferred" if rel.inferred else "observed",
                    polarity=rel.polarity,
                    features={
                        "confidence": rel.confidence,
                        "claim_id": claim_id,
                        "extractor": "llm_small",
                        "inferred": rel.inferred,
                    },
                    **common,
                )
            )
    write_tables(NAME, nodes, [], rows, stage="extracted")
    report = {
        "status": "completed" if llm.stop_reason is None else f"stopped_{llm.stop_reason}",
        "abstracts_total": papers.height,
        "abstracts_with_candidate_pair": len(work),
        "abstracts_skipped_no_candidate_pair": too_few,
        "abstracts_extracted": processed,
        "attempted": attempted,
        "accepted": accepted,
        "rejected": dict(rejected),
        "dropped_inferred": dropped_inferred,
        "pass_rate": round(accepted / attempted, 4) if attempted else None,
        **llm.summary(),
    }
    if processed == 0:
        report["status"] = "skipped_not_logged_in" if llm.client is None else report["status"]
    (out / "report.json").write_text(json.dumps(report, indent=1))
    log.info(
        "abstracts: %s",
        {
            k: report[k]
            for k in ("status", "abstracts_extracted", "attempted", "accepted", "pass_rate")
        },
    )
    return report


def _name(cands: dict[str, str], node_id: str) -> str:
    return next((n for n, i in cands.items() if i == node_id), node_id)
