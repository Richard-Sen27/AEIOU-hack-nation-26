"""The shared phenotype similarity on a toy ontology (no database, no HPO files)."""

import math

import pytest

from backend.phenotype_similarity import (
    SPECIFIC_IC,
    UNKNOWN_FREQUENCY_WEIGHT,
    closure,
    frequency_weight,
    mica_ic,
    one_sided_similarity,
    phenotype_similarity,
)

# root
# ├── nerv (nervous system)
# │   ├── seiz (seizure)
# │   │   ├── focal
# │   │   └── spasm (infantile spasms)
# │   └── ataxia
# └── eye
#     └── nyst (nystagmus)
PARENTS = {
    "root": [],
    "nerv": ["root"],
    "seiz": ["nerv"],
    "focal": ["seiz"],
    "spasm": ["seiz"],
    "ataxia": ["nerv"],
    "eye": ["root"],
    "nyst": ["eye"],
}
IC = {
    "root": 0.0,
    "nerv": 0.5,
    "seiz": 1.5,
    "focal": 3.0,
    "spasm": 4.0,
    "ataxia": 2.5,
    "eye": 0.7,
    "nyst": 3.5,
}


def ancestors(term: str) -> set[str]:
    out: set[str] = set()
    stack = list(PARENTS.get(term, []))
    while stack:
        p = stack.pop()
        if p not in out:
            out.add(p)
            stack.extend(PARENTS.get(p, []))
    return out


def sim(a: dict, b: dict) -> float:
    return phenotype_similarity(a, b, IC, ancestors)


def test_identical_sets_score_one_and_disjoint_branches_score_zero():
    a = {"focal": 1.0, "nyst": 0.5}
    assert sim(a, dict(a)) == pytest.approx(1.0)
    assert sim({"focal": 1.0}, {"nyst": 1.0}) == pytest.approx(0.0)  # only the root is shared


def test_mica_is_the_most_informative_shared_ancestor():
    other = closure({"spasm"}, ancestors)
    assert mica_ic("focal", other, IC, ancestors) == pytest.approx(IC["seiz"])
    assert mica_ic("spasm", other, IC, ancestors) == pytest.approx(IC["spasm"])
    assert mica_ic("nyst", other, IC, ancestors) == pytest.approx(0.0)


def test_partial_match_value():
    # focal vs spasm meet at seizure (1.5 of 3.0 and 1.5 of 4.0)
    expected = 0.5 * (1.5 / 3.0 + 1.5 / 4.0)
    assert sim({"focal": 1.0}, {"spasm": 1.0}) == pytest.approx(expected)


def test_symmetric():
    a = {"focal": 0.9, "ataxia": 0.2, "nyst": 0.5}
    b = {"spasm": 1.0, "nyst": 0.17}
    assert sim(a, b) == pytest.approx(sim(b, a))


def test_range_zero_to_one():
    terms = list(IC)
    for i, x in enumerate(terms):
        for y in terms[i:]:
            for wx, wy in ((1.0, 1.0), (0.1, 0.9), (0.5, 0.025)):
                s = sim({x: wx}, {y: wy})
                assert 0.0 <= s <= 1.0


def test_frequency_weight_shifts_the_score_towards_frequent_terms():
    # A carries a matched term (nystagmus) and an unmatched one (ataxia); B only nystagmus.
    b = {"nyst": 1.0}
    matched_common = sim({"nyst": 0.9, "ataxia": 0.1}, b)
    matched_rare = sim({"nyst": 0.1, "ataxia": 0.9}, b)
    assert matched_common > matched_rare


def test_information_content_shifts_the_score_towards_specific_terms():
    # Sharing a specific term (spasm, IC 4) counts more than sharing a broad one (seiz, IC 1.5),
    # with the same unmatched term on the other side.
    specific = sim({"spasm": 1.0, "ataxia": 1.0}, {"spasm": 1.0, "nyst": 1.0})
    broad = sim({"seiz": 1.0, "ataxia": 1.0}, {"seiz": 1.0, "nyst": 1.0})
    assert specific > broad


def test_one_sided_and_empty_sets():
    a = {"focal": 1.0}
    b = {"focal": 1.0, "nyst": 1.0}
    assert one_sided_similarity(a, b, IC, ancestors) == pytest.approx(1.0)
    assert one_sided_similarity(b, a, IC, ancestors) == pytest.approx(3.0 / 6.5)
    assert sim({}, b) == 0.0
    assert sim(a, {}) == 0.0
    # terms without information content carry no weight
    assert sim({"root": 1.0}, {"root": 1.0}) == 0.0


def test_precomputed_closures_give_the_same_score():
    a = {"focal": 0.9, "nyst": 0.5}
    b = {"spasm": 1.0, "ataxia": 0.3}
    ca, cb = closure(a, ancestors), closure(b, ancestors)
    assert phenotype_similarity(a, b, IC, ancestors, ca, cb) == pytest.approx(sim(a, b))


def test_frequency_weight_defaults_and_clamps():
    assert frequency_weight(None) == UNKNOWN_FREQUENCY_WEIGHT == 0.5
    assert frequency_weight(0.17) == pytest.approx(0.17)
    assert frequency_weight(1.4) == 1.0
    assert frequency_weight(-0.1) == 0.0
    assert math.isclose(SPECIFIC_IC, 2.0)
