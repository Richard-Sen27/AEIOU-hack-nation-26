"""Phenotype similarity on top of pyhpo.

pyhpo 4 cannot parse the axiom annotations that current hp.obo releases put on ``is_a`` lines,
so a sanitized copy of the fetched release is prepared in data/cache/pyhpo/.
"""

from __future__ import annotations

import logging
import math
import re
import shutil
from functools import cache

import numpy as np
import polars as pl
from scipy import sparse

from pipeline import bio
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
        if not (PYHPO_DIR / name).exists() or (PYHPO_DIR / name).stat().st_mtime < (
            RAW / "hpo" / name
        ).stat().st_mtime:
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


def hposet(terms):
    from pyhpo import HPOSet

    return HPOSet.from_queries(sorted(terms))


def bma(terms_a, terms_b, method: str = "lin") -> float:
    """pyhpo best-match-average similarity between two term sets."""
    if not terms_a or not terms_b:
        return 0.0
    return float(hposet(terms_a).similarity(hposet(terms_b), kind=IC_KIND, method=method, combine="BMA"))


def cosine_matrix(rows: list[str], cols: list[str]) -> np.ndarray:
    """Cheap IC-weighted cosine on ancestor-expanded term sets (used to pre-filter at scope time)."""
    dt = disease_terms()
    vocab: dict[str, int] = {}
    min_ic = 0.5  # ignore near-root terms

    def vec(ids: list[str]) -> sparse.csr_matrix:
        data, ind, ptr = [], [], [0]
        for mid in ids:
            expanded = set()
            for t in dt.get(mid, ()):
                expanded |= ancestors(t)
            for t in expanded:
                w = ic(t)
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


def shared_terms(terms_a, terms_b, limit: int = 12) -> list[dict]:
    """The most specific HPO terms (or common ancestors) shared by two diseases."""
    exact = set(terms_a) & set(terms_b)
    anc_a = set().union(*(ancestors(t) for t in terms_a)) if terms_a else set()
    anc_b = set().union(*(ancestors(t) for t in terms_b)) if terms_b else set()
    common = (anc_a & anc_b) - exact
    # Keep only the most specific common ancestors (drop those that are ancestors of others).
    covered = set()
    for t in exact | common:
        covered |= ancestors(t) - {t}
    candidates = [t for t in exact | common if t not in covered]
    ranked = sorted(candidates, key=lambda t: -ic(t))[:limit]
    out = []
    for t in ranked:
        obj = term(t)
        out.append(
            {
                "hpo_id": t,
                "label": obj.name if obj else t,
                "ic": round(ic(t), 3),
                "exact": t in exact,
            }
        )
    return out


def specificity(hpo_id: str) -> float:
    """IC rescaled to 0-1 by the maximum possible IC (a single annotated disease)."""
    n = max(1, len(ontology().omim_diseases))
    return min(1.0, ic(hpo_id) / math.log(n))


def frame_for(ids: list[str]) -> pl.DataFrame:
    dt = disease_terms()
    return pl.DataFrame({"mondo_id": ids, "n_terms": [len(dt.get(i, ())) for i in ids]})
