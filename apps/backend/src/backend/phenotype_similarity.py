"""Phenotype similarity shared by the pipeline and the API (stdlib only, no I/O).

The pipeline scores `similar_symptoms` links between diseases with this code, and Dr. Wu ranks
diseases against a patient's symptoms with the same code, so both use one measure:

    sim(A, B) = 1/2 * [ sum_a w_a * IC(MICA(a, B)) / sum_a w_a * IC(a)
                      + sum_b w_b * IC(MICA(b, A)) / sum_b w_b * IC(b) ]

A and B are sets of HPO terms with a frequency weight w per term (how often the symptom occurs
in the disease; `frequency_weight` maps a missing frequency to 0.5). IC is the information
content of a term (-ln of the share of annotated diseases that carry the term or a descendant),
and MICA(a, B) is the most informative common ancestor of a and any term of B, a term counting
as its own ancestor. The result lies in 0..1: 1 when both sets are equal, 0 when they share no
informative ancestor. The ontology is passed in (an IC mapping and an ancestor function), so the
caller decides which release and corpus the numbers come from.
"""

from collections.abc import Callable, Iterable, Mapping

# A term counts as "specific" from this information content on (shared by at most about 1 in 7
# annotated diseases).
SPECIFIC_IC = 2.0
# Weight of an annotation whose frequency is not recorded.
UNKNOWN_FREQUENCY_WEIGHT = 0.5

Ancestors = Callable[[str], Iterable[str]]


def frequency_weight(frequency: float | None) -> float:
    """The weight of one annotation: its frequency (0..1), or 0.5 when it is not recorded."""
    if frequency is None:
        return UNKNOWN_FREQUENCY_WEIGHT
    return min(1.0, max(0.0, float(frequency)))


def closure(terms: Iterable[str], ancestors: Ancestors) -> set[str]:
    """The terms together with all their ancestors."""
    out: set[str] = set()
    for t in terms:
        out.add(t)
        out.update(ancestors(t))
    return out


def mica_ic(
    term: str, other_closure: set[str], ic: Mapping[str, float], ancestors: Ancestors
) -> float:
    """IC of the most informative common ancestor of `term` and any term whose ancestor closure
    is `other_closure` (0 when they share nothing)."""
    best = ic.get(term, 0.0) if term in other_closure else 0.0
    for t in ancestors(term):
        if t in other_closure:
            best = max(best, ic.get(t, 0.0))
    return best


def one_sided_similarity(
    a: Mapping[str, float],
    b: Mapping[str, float],
    ic: Mapping[str, float],
    ancestors: Ancestors,
    b_closure: set[str] | None = None,
) -> float:
    """How well the terms of `a` are matched in `b`: sum w_a * IC(MICA(a, B)) / sum w_a * IC(a).

    `a` and `b` map HPO term ids to frequency weights. Pass `b_closure` (from `closure`) to reuse
    it across many calls.
    """
    if not a or not b:
        return 0.0
    other = b_closure if b_closure is not None else closure(b, ancestors)
    num = den = 0.0
    for term, w in a.items():
        own = ic.get(term, 0.0)
        if w <= 0 or own <= 0:
            continue
        den += w * own
        num += w * min(own, mica_ic(term, other, ic, ancestors))
    return num / den if den > 0 else 0.0


def phenotype_similarity(
    a: Mapping[str, float],
    b: Mapping[str, float],
    ic: Mapping[str, float],
    ancestors: Ancestors,
    a_closure: set[str] | None = None,
    b_closure: set[str] | None = None,
) -> float:
    """Frequency-weighted, IC-based symmetric best-match average of two term sets, in 0..1.

    `a` and `b` map HPO term ids to frequency weights (see `frequency_weight`); `ic` maps term
    ids to information content (missing terms count as 0); `ancestors(term)` returns the term's
    ancestors (with or without the term itself). Symmetric: sim(a, b) == sim(b, a).
    """
    if not a or not b:
        return 0.0
    ab = one_sided_similarity(a, b, ic, ancestors, b_closure)
    ba = one_sided_similarity(b, a, ic, ancestors, a_closure)
    return min(1.0, max(0.0, 0.5 * (ab + ba)))
