"""HPO lineage of each phenotype node, for the Atlas symptom tree (`attrs.hpo_lineage`)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable

from pipeline import bio

PHENOTYPIC_ABNORMALITY = "HP:0000118"

Parents = dict[str, list[str]]


def hpo() -> tuple[Parents, dict[str, str]]:
    """is_a parents and labels of every term in the parsed HPO release."""
    parents: Parents = {}
    labels: dict[str, str] = {}
    for hid, label, ps in bio.hpo_terms().select("id", "label", "parents").iter_rows():
        parents[hid] = list(ps or [])
        labels[hid] = label or hid
    return parents, labels


def ancestor_fn(parents: Parents) -> Callable[[str], frozenset[str]]:
    """Memoised transitive is_a ancestors (the term itself excluded)."""
    cache: dict[str, frozenset[str]] = {}

    def ancestors(term: str) -> frozenset[str]:
        if term in cache:
            return cache[term]
        cache[term] = frozenset()  # guards against cycles in a malformed ontology
        out: set[str] = set()
        for p in parents.get(term, ()):
            out.add(p)
            out |= ancestors(p)
        cache[term] = frozenset(out)
        return cache[term]

    return ancestors


def organ_systems(parents: Parents | None = None) -> set[str]:
    """The direct is_a children of Phenotypic abnormality (HP:0000118)."""
    parents = parents if parents is not None else hpo()[0]
    return {t for t, ps in parents.items() if PHENOTYPIC_ABNORMALITY in ps}


def hpo_lineages(
    phenotype_ids: Iterable[str],
    parents: Parents | None = None,
    labels: dict[str, str] | None = None,
) -> dict[str, list[dict]]:
    """Ordered HPO is_a chain for each phenotype, organ system first, primary parent last.

    Each element is `{"id": "HP:...", "label": "..."}`. The phenotype itself and HP:0000118 are
    left out, and the full chain is kept (the Atlas tree splices single-child classes itself).

    Primary parent: among a term's is_a parents that lie under HP:0000118, the one with the most
    descendants among `phenotype_ids`; ties go to the smallest id. The same rule is applied at
    every step up, so each phenotype gets one deterministic path.

    Empty lineage: a phenotype that is itself an organ system (a direct child of HP:0000118), and
    also HP:0000118 itself, a term outside the Phenotypic abnormality branch (for example a mode
    of inheritance) and a term missing from the parsed HPO. Every input id gets an entry.
    """
    if parents is None or labels is None:
        p, lab = hpo()
        parents = parents if parents is not None else p
        labels = labels if labels is not None else lab
    ancestors = ancestor_fn(parents)
    in_graph = sorted(set(phenotype_ids))
    descendants: Counter[str] = Counter()
    for term in in_graph:
        descendants.update(ancestors(term))

    def under_root(term: str) -> bool:
        return term == PHENOTYPIC_ABNORMALITY or PHENOTYPIC_ABNORMALITY in ancestors(term)

    def primary(term: str) -> str | None:
        candidates = [p for p in parents.get(term, ()) if under_root(p)]
        if not candidates:
            return None
        return min(candidates, key=lambda p: (-descendants[p], p))

    out: dict[str, list[dict]] = {}
    for term in in_graph:
        chain: list[str] = []
        cur = term
        while True:
            p = primary(cur)
            if p is None:  # outside HP:0000118, or HP:0000118 itself
                chain = []
                break
            if p == PHENOTYPIC_ABNORMALITY:
                break
            if p in chain or p == term:  # cycle in a malformed ontology: stop climbing
                chain = []
                break
            chain.append(p)
            cur = p
        out[term] = [{"id": t, "label": labels.get(t, t)} for t in reversed(chain)]
    return out


def lineage_problems(
    lineages: dict[str, object], parents: Parents | None = None
) -> dict[str, list[str]]:
    """Phenotype ids whose lineage is missing, malformed, not rooted at an organ system, or not
    an is_a path down to the term. Empty lineages are fine (organ systems, terms outside
    HP:0000118) and are listed under "empty"."""
    parents = parents if parents is not None else hpo()[0]
    systems = organ_systems(parents)
    out: dict[str, list[str]] = {"missing": [], "bad_root": [], "broken_path": [], "empty": []}
    for nid, lin in sorted(lineages.items()):
        if not isinstance(lin, list) or not all(
            isinstance(x, dict) and isinstance(x.get("id"), str) for x in lin
        ):
            out["missing"].append(nid)
            continue
        if not lin:
            out["empty"].append(nid)
            continue
        ids = [x["id"] for x in lin]
        if ids[0] not in systems:
            out["bad_root"].append(nid)
        chain = [*ids, nid]
        if any(chain[i] not in parents.get(chain[i + 1], ()) for i in range(len(chain) - 1)):
            out["broken_path"].append(nid)
    return out
