"""Phenotype information content and similarity inputs.

Analytics uses the corpus information content below (every disease in phenotype.hpoa) and the
shared similarity function in ``backend.phenotype_similarity``. Scope selection still uses
pyhpo's OMIM-based IC (``ic``), so the scope stays as it was.

pyhpo 4 cannot parse the axiom annotations that current hp.obo releases put on ``is_a`` lines,
so a sanitized copy of the fetched release is prepared in data/cache/pyhpo/.
"""

from __future__ import annotations

import logging
import math
import re
import shutil
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from functools import cache

import numpy as np
import polars as pl
from backend.phenotype_similarity import closure, frequency_weight
from scipy import sparse

from pipeline import bio, taxonomy
from pipeline.paths import CACHE, RAW

log = logging.getLogger(__name__)

PYHPO_DIR = CACHE / "pyhpo"
IC_KIND = "omim"


def _prepare() -> None:
    PYHPO_DIR.mkdir(parents=True, exist_ok=True)
    src = RAW / "hpo" / "hp.obo"
    dst = PYHPO_DIR / "hp.obo"
    if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
        pattern = re.compile(r"^(is_a: \S+)( \{[^}]*\})?")
        with src.open() as fin, dst.open("w") as fout:
            for line in fin:
                fout.write(pattern.sub(r"\1", line))
    for name in ("phenotype.hpoa", "genes_to_phenotype.txt"):
        if (
            not (PYHPO_DIR / name).exists()
            or (PYHPO_DIR / name).stat().st_mtime < (RAW / "hpo" / name).stat().st_mtime
        ):
            shutil.copy(RAW / "hpo" / name, PYHPO_DIR / name)


@cache
def ontology():
    from pyhpo import Ontology

    _prepare()
    Ontology(data_folder=str(PYHPO_DIR))
    return Ontology


def term(hpo_id: str):
    try:
        return ontology().get_hpo_object(hpo_id)
    except (RuntimeError, KeyError, ValueError):
        return None


def ic(hpo_id: str) -> float:
    t = term(hpo_id)
    return float(t.information_content[IC_KIND]) if t else 0.0


@cache
def ancestors(hpo_id: str) -> frozenset[str]:
    t = term(hpo_id)
    if t is None:
        return frozenset()
    return frozenset([t.id, *(p.id for p in t.all_parents)])


@cache
def disease_terms() -> dict[str, frozenset[str]]:
    """MONDO id -> annotated HPO terms (HPO annotations + Orphanet), known to pyhpo only."""
    dp = bio.disease_phenotypes().select("mondo_id", "hpo_id").unique()
    out: dict[str, set[str]] = {}
    for mid, hid in dp.iter_rows():
        if term(hid) is not None:
            out.setdefault(mid, set()).add(hid)
    return {k: frozenset(v) for k, v in out.items()}


def cosine_matrix(
    rows: list[str],
    cols: list[str],
    terms: Mapping[str, Iterable[str]] | None = None,
    ic_fn: Callable[[str], float] | None = None,
    ancestors_fn: Callable[[str], Iterable[str]] | None = None,
) -> np.ndarray:
    """Cheap IC-weighted cosine on ancestor-expanded term sets (pre-filter for similarity).

    Defaults: all HPO / Orphanet annotations and pyhpo's IC (as used at scope time); analytics
    passes the graph's annotations and the corpus IC instead.
    """
    dt = terms if terms is not None else disease_terms()
    ic_fn = ic_fn or ic
    ancestors_fn = ancestors_fn or ancestors
    vocab: dict[str, int] = {}
    min_ic = 0.5  # ignore near-root terms

    def vec(ids: list[str]) -> sparse.csr_matrix:
        data, ind, ptr = [], [], [0]
        for mid in ids:
            expanded = set()
            for t in dt.get(mid, ()):
                expanded.add(t)
                expanded |= set(ancestors_fn(t))
            for t in expanded:
                w = ic_fn(t)
                if w >= min_ic:
                    ind.append(vocab.setdefault(t, len(vocab)))
                    data.append(w)
            ptr.append(len(ind))
        return data, ind, ptr

    a = vec(rows)
    b = vec(cols)
    n = len(vocab)
    ma = sparse.csr_matrix((a[0], a[1], a[2]), shape=(len(rows), n))
    mb = sparse.csr_matrix((b[0], b[1], b[2]), shape=(len(cols), n))

    def norm(m):
        s = np.sqrt(np.asarray(m.multiply(m).sum(axis=1)).ravel())
        s[s == 0] = 1
        return sparse.diags(1 / s) @ m

    return (norm(ma) @ norm(mb).T).toarray()


def frame_for(ids: list[str]) -> pl.DataFrame:
    dt = disease_terms()
    return pl.DataFrame({"mondo_id": ids, "n_terms": [len(dt.get(i, ())) for i in ids]})


# ---------------------------------------------------------------- corpus information content


@dataclass(frozen=True)
class Corpus:
    """Information content over an annotation corpus: IC(t) = -ln(n_t / N), n_t = diseases
    annotated to t or a descendant. Terms never annotated get the IC of a single disease."""

    n_diseases: int
    counts: dict[str, int]
    ic: dict[str, float]
    ancestors: Callable[[str], frozenset[str]]
    labels: dict[str, str]
    annotations: dict[str, dict[str, float]]  # corpus disease -> HPO term -> frequency weight


def corpus_from(
    annotations: Mapping[str, Mapping[str, float | None]],
    parents: dict[str, list[str]],
    labels: dict[str, str] | None = None,
) -> Corpus:
    anc = taxonomy.ancestor_fn(parents)
    counts: Counter[str] = Counter()
    for terms in annotations.values():
        counts.update(closure(terms, anc))
    n = len(annotations)
    ic = {t: max(0.0, -math.log(c / n)) for t, c in counts.items()}
    single = math.log(n) if n else 0.0
    for t in parents:
        ic.setdefault(t, single)
    weights = {
        d: {t: frequency_weight(f) for t, f in terms.items()} for d, terms in annotations.items()
    }
    return Corpus(n, dict(counts), ic, anc, labels or {}, weights)


@cache
def corpus() -> Corpus:
    """Corpus IC over every disease in phenotype.hpoa (OMIM, ORPHA, DECIPHER; aspect P; NOT and
    excluded (0%) annotations left out)."""
    parents, labels = taxonomy.hpo()
    a = bio.hpoa().filter(~pl.col("negated") & (pl.col("frequency") != 0).fill_null(True))
    per: dict[str, dict[str, float | None]] = {}
    for d, t, f in a.select("disease_id", "hpo_id", "frequency").iter_rows():
        terms = per.setdefault(d, {})
        cur = terms.get(t)
        terms[t] = f if cur is None else (cur if f is None else max(cur, f))
    c = corpus_from(per, parents, labels)
    log.info("corpus IC: %d diseases, %d annotated terms", c.n_diseases, len(c.counts))
    return c
