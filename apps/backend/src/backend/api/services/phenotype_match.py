"""Symptom matching: the HPO term table in memory, and conditions ranked by symptom overlap.

The term table (`hpo_terms`, filled by the pipeline) is read at startup next to the graph: labels,
synonyms, direct parents and information content for every HPO term, also terms that are not
graph nodes. When it is empty (older data, the test fixture) the phenotype nodes stand in: their
`attrs.ic` and `attrs.ancestors`.

`rank` scores every disease in the store against a set of present terms (frequency 1) with
`backend.phenotype_similarity` (the measure the pipeline uses for `similar_symptoms`): the disease
side is its `has_phenotype` edges with their frequencies. A precomputed index makes one query over
about 7,400 diseases a few numpy passes; the best candidates are then scored again with
`phenotype_similarity` itself, absent terms and the disease's excluded terms lower the score, and
only diseases with at least one shared symptom (a citable `has_phenotype` edge) are returned.

The result is an overlap ranking of conditions in the atlas, never a probability or a diagnosis.
Symptom text is health data: it is never logged.
"""

import logging
import math
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.services.graph import GraphStore, get_graph, normalize_name
from backend.phenotype_similarity import (
    SPECIFIC_IC,
    closure,
    frequency_weight,
    phenotype_similarity,
)
from backend.schemas.enums import NodeType, Relation

log = logging.getLogger(__name__)

TOP_K = 10
MAX_RESCORED = 2000  # candidates scored exactly before the ranking stops (bounds the time)
_HP_ID = re.compile(r"^HP[:_ ]?0*(\d{1,7})$", re.IGNORECASE)
_STOPWORDS = frozenset({"a", "an", "and", "for", "in", "of", "on", "the", "to", "with"})
FUZZY_MIN = 0.6  # Dice coefficient of the (singular) words for a non-exact term match


# --- the term table ---------------------------------------------------------------------------


def _singular(word: str) -> str:
    if len(word) > 3 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _loose(key: str) -> str:
    return " ".join(_singular(w) for w in key.split())


def _words(key: str) -> frozenset[str]:
    return frozenset(_singular(w) for w in key.split() if w not in _STOPWORDS and len(w) > 1)


@dataclass
class TermTable:
    """HPO terms: labels, synonyms, information content and proper ancestors."""

    labels: dict[str, str]
    synonyms: dict[str, tuple[str, ...]]
    ic: dict[str, float]
    ancestors: dict[str, frozenset[str]]
    source: str  # "table" (hpo_terms) or "graph" (phenotype nodes)
    names: dict[str, list[str]] = field(default_factory=dict)  # exact key -> ids, labels first
    loose: dict[str, list[str]] = field(default_factory=dict)  # singular words -> ids
    by_word: dict[str, list[int]] = field(default_factory=dict)  # word -> entries
    entries: list[tuple[str, frozenset[str]]] = field(default_factory=list)  # (id, words)

    def __post_init__(self) -> None:
        def add(index: dict[str, list[str]], key: str, tid: str) -> None:
            ids = index.setdefault(key, [])
            if tid not in ids:
                ids.append(tid)

        for pass_labels in (True, False):  # every label before any synonym
            for tid in sorted(self.labels):
                names = [self.labels[tid]] if pass_labels else list(self.synonyms.get(tid, ()))
                for name in names:
                    key = normalize_name(name)
                    if not key:
                        continue
                    add(self.names, key, tid)
                    add(self.loose, _loose(key), tid)
                    words = _words(key)
                    if words:
                        self.entries.append((tid, words))
                        for w in words:
                            self.by_word.setdefault(w, []).append(len(self.entries) - 1)

    def ancestors_of(self, term: str) -> frozenset[str]:
        return self.ancestors.get(term, frozenset())

    def label(self, term: str) -> str:
        return self.labels.get(term, term)

    def resolve(self, mention: str) -> str | None:
        """An HPO id for a symptom mention: an id, an exact label or synonym, the same words
        in singular, else the closest wording (Dice >= FUZZY_MIN); None when nothing fits."""
        raw = mention.strip()
        if m := _HP_ID.match(raw):
            tid = f"HP:{int(m.group(1)):07d}"
            return tid if tid in self.labels else None
        key = normalize_name(raw)
        if not key:
            return None
        if ids := self.names.get(key):
            return ids[0]
        if ids := self.loose.get(_loose(key)):
            return ids[0]
        words = _words(key)
        if not words:
            return None
        best: tuple[float, int, str] | None = None
        for idx in {i for w in words for i in self.by_word.get(w, ())}:
            tid, other = self.entries[idx]
            score = 2 * len(words & other) / (len(words) + len(other))
            cand = (-score, len(other), tid)
            if score >= FUZZY_MIN and (best is None or cand < best):
                best = cand
        return best[2] if best else None


def table_from_rows(rows: Iterable[Mapping[str, Any]]) -> TermTable | None:
    """The term table from `hpo_terms` rows (None when there are none)."""
    labels: dict[str, str] = {}
    synonyms: dict[str, tuple[str, ...]] = {}
    parents: dict[str, tuple[str, ...]] = {}
    ic: dict[str, float] = {}
    for row in rows:
        tid = row["id"]
        labels[tid] = row["label"]
        synonyms[tid] = tuple(s for s in row.get("synonyms") or () if s)
        parents[tid] = tuple(p for p in row.get("parents") or () if p)
        if row.get("ic") is not None:
            ic[tid] = float(row["ic"])
    if not labels:
        return None
    ancestors: dict[str, frozenset[str]] = {}

    def walk(tid: str, stack: frozenset[str]) -> frozenset[str]:
        if tid in ancestors:
            return ancestors[tid]
        out: set[str] = set()
        for p in parents.get(tid, ()):
            if p in stack:  # a cycle in the input: ignore that parent
                continue
            out.add(p)
            out |= walk(p, stack | {p})
        ancestors[tid] = frozenset(out)
        return ancestors[tid]

    for tid in labels:
        walk(tid, frozenset({tid}))
    return TermTable(labels, synonyms, ic, ancestors, source="table")


def table_from_graph(store: GraphStore) -> TermTable:
    """Stand-in term table from the phenotype nodes (`attrs.ic`, `attrs.ancestors`). A node
    without `attrs.ic` (older data, the fixture) gets the IC of the store's own annotations:
    -ln(share of annotated diseases carrying the term or a descendant)."""
    labels, synonyms, ic, ancestors = {}, {}, {}, {}
    for node in store.nodes.values():
        if node.type != NodeType.phenotype:
            continue
        labels[node.id] = node.label
        synonyms[node.id] = tuple(store.synonyms.get(node.id, ()))
        value = node.attrs.get("ic")
        if isinstance(value, int | float):
            ic[node.id] = float(value)
        anc = node.attrs.get("ancestors")
        ancestors[node.id] = (
            frozenset(a for a in anc if isinstance(a, str) and a != node.id)
            if isinstance(anc, list)
            else frozenset()
        )
    if len(ic) < len(labels):
        carried: dict[str, set[str]] = defaultdict(set)
        for edge in store.edges.values():
            if edge.relation == Relation.has_phenotype and edge.target_id in labels:
                carried[edge.source_id].add(edge.target_id)
        holders: dict[str, int] = defaultdict(int)
        for terms in carried.values():
            for t in closure(terms, lambda t: ancestors.get(t, ())):
                holders[t] += 1
        for tid in labels:
            if tid not in ic and holders.get(tid):
                ic[tid] = -math.log(holders[tid] / len(carried))
    return TermTable(labels, synonyms, ic, ancestors, source="graph")


_terms: TermTable | None = None

_TERMS_SQL = text("SELECT id, label, synonyms, parents, ic FROM hpo_terms")


def set_terms(table: TermTable | None) -> None:
    """Install the term table read from the database (None: use the phenotype nodes)."""
    global _terms
    _terms = table


async def load_terms(db: AsyncSession) -> int:
    """Read `hpo_terms` into memory; returns the number of terms (0: table empty)."""
    rows = [dict(r) for r in (await db.execute(_TERMS_SQL)).mappings()]
    set_terms(table_from_rows(rows))
    return len(rows)


def get_terms(store: GraphStore | None = None) -> TermTable:
    """The loaded term table, else the phenotype nodes of the store."""
    if _terms is not None:
        return _terms
    return get_index(store).terms


# --- the disease index ------------------------------------------------------------------------


@dataclass
class DiseaseProfile:
    terms: dict[str, float]  # HPO id -> frequency weight
    edges: dict[str, str]  # HPO id -> has_phenotype edge id (highest frequency)
    closure: frozenset[str]
    excluded: frozenset[str]


class PhenotypeIndex:
    """Per disease its `has_phenotype` terms and closure, plus inverted arrays for numpy scoring.

    Built once per store and term table (about 7,400 diseases and 195,000 annotations)."""

    def __init__(self, store: GraphStore, terms: TermTable) -> None:
        self.terms = terms
        anc = terms.ancestors_of
        ic = terms.ic
        weights: dict[str, dict[str, float]] = defaultdict(dict)
        edge_of: dict[str, dict[str, tuple[float, str]]] = defaultdict(dict)
        for edge in store.edges.values():
            if edge.relation != Relation.has_phenotype:
                continue
            disease = store.nodes.get(edge.source_id)
            if disease is None or disease.type != NodeType.disease:
                continue
            raw = (edge.features or {}).get("frequency")
            w = frequency_weight(float(raw) if isinstance(raw, int | float) else None)
            term = edge.target_id
            prev = weights[disease.id].get(term)
            if prev is None or w > prev:
                weights[disease.id][term] = w
            best = edge_of[disease.id].get(term)
            if best is None or w > best[0] or (w == best[0] and edge.id < best[1]):
                edge_of[disease.id][term] = (w, edge.id)
        self.ids = sorted(
            n.id for n in store.nodes.values() if n.type == NodeType.disease and weights.get(n.id)
        )
        self.profiles: dict[str, DiseaseProfile] = {}
        for did in self.ids:
            excluded = store.nodes[did].attrs.get("excluded_phenotypes")
            self.profiles[did] = DiseaseProfile(
                terms=weights[did],
                edges={t: e for t, (_w, e) in edge_of[did].items()},
                closure=frozenset(closure(weights[did], anc)),
                excluded=frozenset(
                    x["id"]
                    for x in excluded or ()
                    if isinstance(x, dict) and isinstance(x.get("id"), str)
                )
                if isinstance(excluded, list)
                else frozenset(),
            )
        n = len(self.ids)
        # disease -> query side: one row per annotation (disease index, term, weight)
        ann_disease, ann_term, ann_w, ann_ic = [], [], [], []
        self.term_ix: dict[str, int] = {}
        for i, did in enumerate(self.ids):
            for term, w in self.profiles[did].terms.items():
                own = ic.get(term, 0.0)
                if w <= 0 or own <= 0:
                    continue
                ann_disease.append(i)
                ann_term.append(self.term_ix.setdefault(term, len(self.term_ix)))
                ann_w.append(w)
                ann_ic.append(own)
        self.ann_disease = np.asarray(ann_disease, dtype=np.int32)
        self.ann_term = np.asarray(ann_term, dtype=np.int32)
        self.ann_w = np.asarray(ann_w, dtype=np.float64)
        self.ann_ic = np.asarray(ann_ic, dtype=np.float64)
        self.den = np.bincount(self.ann_disease, weights=self.ann_w * self.ann_ic, minlength=n)
        # annotated terms below each term (the term itself included), as term indices
        below: dict[str, list[int]] = defaultdict(list)
        for term, ti in self.term_ix.items():
            below[term].append(ti)
            for a in anc(term):
                below[a].append(ti)
        self.below = {t: np.asarray(v, dtype=np.int32) for t, v in below.items()}
        # query -> disease side: diseases whose closure holds each term
        holders: dict[str, list[int]] = defaultdict(list)
        for i, did in enumerate(self.ids):
            for t in self.profiles[did].closure:
                holders[t].append(i)
        self.holders = {t: np.asarray(v, dtype=np.int32) for t, v in holders.items()}

    def fast_scores(self, query: Sequence[str]) -> np.ndarray:
        """phenotype_similarity(query, disease) for every disease at once (query weights 1)."""
        n = len(self.ids)
        ic = self.terms.ic
        q_all = list(dict.fromkeys(query))
        if not q_all or not n:
            return np.zeros(n)
        # query -> disease: per query term the IC of its best common ancestor with the disease
        num = np.zeros(n)
        den = 0.0
        for a in q_all:
            own = ic.get(a, 0.0)
            if own <= 0:
                continue
            den += own
            best = np.zeros(n)
            for t in sorted({a, *self.terms.ancestors_of(a)}, key=lambda t: ic.get(t, 0.0)):
                if (rows := self.holders.get(t)) is not None and ic.get(t, 0.0) > 0:
                    best[rows] = ic[t]
            num += np.minimum(best, own)
        qd = num / den if den > 0 else np.zeros(n)
        # disease -> query: per annotated term the IC of its best common ancestor with the query
        m = np.zeros(len(self.term_ix))
        q_closure = closure(q_all, self.terms.ancestors_of)
        for t in sorted(q_closure, key=lambda t: ic.get(t, 0.0)):
            if (rows := self.below.get(t)) is not None and ic.get(t, 0.0) > 0:
                m[rows] = np.maximum(m[rows], ic[t])
        contrib = self.ann_w * np.minimum(self.ann_ic, m[self.ann_term])
        dnum = np.bincount(self.ann_disease, weights=contrib, minlength=n)
        dq = np.divide(dnum, self.den, out=np.zeros(n), where=self.den > 0)
        return np.clip(0.5 * (qd + dq), 0.0, 1.0)


def get_index(store: GraphStore | None = None) -> PhenotypeIndex:
    """The index of the store for the current term table (built on first use, cached)."""
    store = store or get_graph()
    terms = _terms
    cached = store.phenotype_index
    if isinstance(cached, PhenotypeIndex) and (
        cached.terms is terms or (terms is None and cached.terms.source == "graph")
    ):
        return cached
    index = PhenotypeIndex(store, terms if terms is not None else table_from_graph(store))
    store.phenotype_index = index
    return index


# --- ranking ----------------------------------------------------------------------------------


@dataclass
class SharedTerm:
    query: str  # the user's term (HPO id)
    term: str  # the disease's recorded term
    edge_id: str
    match: str  # "same", "more_specific" (recorded term is narrower) or "broader"


@dataclass
class Match:
    disease_id: str
    score: float  # phenotype similarity after the penalty, 0..1; not a probability
    similarity: float  # before the penalty
    shared: list[SharedTerm]
    conflicts: list[SharedTerm]  # absent per the user but recorded for the disease
    excluded: list[str]  # present per the user, recorded as absent for the disease (HPO ids)

    @property
    def overlap(self) -> int:
        return len({s.query for s in self.shared})


def _shared(profile: DiseaseProfile, present: Sequence[str], terms: TermTable) -> list[SharedTerm]:
    out = []
    for q in present:
        q_anc = terms.ancestors_of(q)
        for term in sorted(profile.terms, key=lambda t: (-profile.terms[t], t)):
            if term == q:
                match = "same"
            elif q in terms.ancestors_of(term):
                match = "more_specific"
            elif term in q_anc and terms.ic.get(term, 0.0) >= SPECIFIC_IC:
                match = "broader"
            else:
                continue
            out.append(SharedTerm(q, term, profile.edges[term], match))
    return out


def _penalized(
    profile: DiseaseProfile,
    sim: float,
    present: Sequence[str],
    absent: Sequence[str],
    terms: TermTable,
) -> tuple[float, list[SharedTerm], list[str]]:
    """score = similarity * (1 - share): `share` is the IC-weighted part of the user's terms
    that contradict the disease's record (an absent term recorded for it, weighted by its
    recorded frequency; a present term it is recorded not to have)."""
    ic = terms.ic
    total = sum(ic.get(t, 0.0) for t in [*present, *absent])
    conflicts: list[SharedTerm] = []
    excluded: list[str] = []
    against = 0.0
    for a in absent:
        hits = [t for t in profile.terms if t == a or a in terms.ancestors_of(t)]
        if hits:
            top = max(hits, key=lambda t: (profile.terms[t], t))
            against += ic.get(a, 0.0) * profile.terms[top]
            conflicts.append(
                SharedTerm(a, top, profile.edges[top], "same" if top == a else "more_specific")
            )
    for p in present:
        if profile.excluded & ({p} | terms.ancestors_of(p)):
            against += ic.get(p, 0.0)
            excluded.append(p)
    share = min(1.0, against / total) if total > 0 else 0.0
    return sim * (1.0 - share), conflicts, excluded


def rank(
    present: Sequence[str],
    absent: Sequence[str] = (),
    *,
    limit: int = TOP_K,
    store: GraphStore | None = None,
) -> list[Match]:
    """The diseases whose recorded symptoms overlap `present` most (HPO ids), best first.

    Exact top `limit` by the penalized score: candidates are taken in order of their fast
    similarity (an upper bound of the penalized score) until no later one can enter."""
    index = get_index(store)
    terms = index.terms
    present = list(dict.fromkeys(present))
    absent = [a for a in dict.fromkeys(absent) if a not in present]
    if not present or not index.ids:
        return []
    fast = index.fast_scores(present)
    order = np.argsort(-fast, kind="stable")
    query = dict.fromkeys(present, 1.0)
    q_closure = closure(present, terms.ancestors_of)
    found: list[Match] = []
    for pos in order[:MAX_RESCORED]:
        bound = float(fast[pos])
        if bound <= 0 or (len(found) >= limit and bound < found[limit - 1].score - 1e-12):
            break
        did = index.ids[pos]
        profile = index.profiles[did]
        shared = _shared(profile, present, terms)
        if not shared:
            continue
        sim = phenotype_similarity(
            query,
            profile.terms,
            terms.ic,
            terms.ancestors_of,
            a_closure=q_closure,
            b_closure=profile.closure,  # type: ignore[arg-type]  # read-only use
        )
        score, conflicts, excluded = _penalized(profile, sim, present, absent, terms)
        found.append(Match(did, score, sim, shared, conflicts, excluded))
        found.sort(key=lambda m: (-m.score, m.disease_id))
    return [m for m in found if m.score > 0][:limit]
