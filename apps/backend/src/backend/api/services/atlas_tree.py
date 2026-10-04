"""Atlas tree: the logo hub (``T:root``) with one radial tree per category.

The tree is a navigation structure only; it never changes how nodes are connected. Every
store node (contribution overlay included) appears exactly once as an entity node, and every
level below a category derives from stored data (attributes, edges, cluster membership).

Layout: each category owns an angular sector (clockwise from 12 o'clock, so angles decrease
from pi/2; standard polar angles, counter-clockwise from +x, y up). Inside a sector the tree
grows outward: every node gets a wedge of its parent's wedge (by subtree size), is placed at
an irregular distance and angle inside it, and its leaf children spread in a small fan in
front of it. A node and its fan are only placed where they do not touch anything placed
before (searched outward), so crowded branches grow longer instead of overlapping.
Everything is deterministic: jitter is hashed from ids, inputs are sorted.
"""

import hashlib
import math
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from backend.api.services import graph
from backend.schemas.atlas import (
    AtlasCategory,
    AtlasCategorySummary,
    AtlasTree,
    AtlasTreeNode,
    GroupBasis,
    TreeNodeKind,
)
from backend.schemas.enums import NodeType, Relation
from backend.schemas.graph import Node

LAYOUT_VERSION = 4
ROOT_ID = "T:root"
MAX_LEAVES = 30

CATEGORY_ORDER: tuple[AtlasCategory, ...] = (
    AtlasCategory.researchers,
    AtlasCategory.institutions,
    AtlasCategory.literature,
    AtlasCategory.community,
    AtlasCategory.pathways,
    AtlasCategory.genes,
    AtlasCategory.diseases,
    AtlasCategory.symptoms,
    AtlasCategory.doctors,
)

CATEGORY_LABELS: dict[AtlasCategory, str] = {
    AtlasCategory.researchers: "Researchers",
    AtlasCategory.institutions: "Hospitals & universities",
    AtlasCategory.literature: "Literature",
    AtlasCategory.community: "Community",
    AtlasCategory.pathways: "Pathways",
    AtlasCategory.genes: "Genes",
    AtlasCategory.diseases: "Diseases",
    AtlasCategory.symptoms: "Symptoms",
    AtlasCategory.doctors: "Doctors",
}

TYPE_CATEGORY: dict[NodeType, AtlasCategory] = {
    NodeType.researcher: AtlasCategory.researchers,
    NodeType.institution: AtlasCategory.institutions,
    NodeType.paper: AtlasCategory.literature,
    NodeType.trial: AtlasCategory.literature,
    NodeType.grant: AtlasCategory.literature,
    NodeType.claim: AtlasCategory.literature,
    NodeType.patient_org: AtlasCategory.community,
    NodeType.registry: AtlasCategory.community,
    NodeType.network: AtlasCategory.community,
    NodeType.pathway: AtlasCategory.pathways,
    NodeType.gene: AtlasCategory.genes,
    NodeType.variant: AtlasCategory.genes,
    NodeType.mechanism: AtlasCategory.genes,
    NodeType.disease: AtlasCategory.diseases,
    NodeType.cluster: AtlasCategory.diseases,
    NodeType.phenotype: AtlasCategory.symptoms,
    NodeType.doctor: AtlasCategory.doctors,
}


# --- tree drafts ----------------------------------------------------------------------------


@dataclass
class _Draft:
    id: str
    kind: TreeNodeKind
    label: str
    category: AtlasCategory | None
    basis: GroupBasis | None = None
    ref_id: str | None = None
    entity: Node | None = None
    cluster_id: str | None = None
    children: list["_Draft"] = field(default_factory=list)
    ordered: bool = False  # children keep their given order (ranges, years, chromosomes)
    count: int = 0  # entities in subtree, filled by _count
    need: float | None = None  # layout: estimated area of the subtree, see _need


def _sort_key(node: Node) -> tuple[str, str]:
    return (node.label.casefold(), node.id)


def _entity(node: Node, category: AtlasCategory, label: str | None = None) -> _Draft:
    return _Draft(
        id=node.id,
        kind=TreeNodeKind.entity,
        label=label or node.label,
        category=category,
        entity=node,
        cluster_id=node.cluster_id,
    )


def _group(
    gid: str,
    label: str,
    category: AtlasCategory,
    basis: GroupBasis,
    children: list[_Draft],
    ref_id: str | None = None,
    cluster_id: str | None = None,
    ordered: bool = False,
) -> _Draft:
    return _Draft(
        id=gid,
        kind=TreeNodeKind.group,
        label=label,
        category=category,
        basis=basis,
        ref_id=ref_id,
        cluster_id=cluster_id,
        children=children,
        ordered=ordered,
    )


def _range_label(first: str, last: str) -> str:
    a, b = first.strip()[:2] or "?", last.strip()[:2] or "?"
    return f"{a.capitalize()}–{b.capitalize()}"


def _ranges(base_id: str, leaves: list[_Draft], category: AtlasCategory) -> list[_Draft]:
    """Leaves as they are when there are at most MAX_LEAVES, else alphabetical ranges."""
    leaves = sorted(leaves, key=lambda d: (d.label.casefold(), d.id))
    if len(leaves) <= MAX_LEAVES:
        return leaves
    n_chunks = math.ceil(len(leaves) / MAX_LEAVES)
    size = math.ceil(len(leaves) / n_chunks)  # even chunks: 31 -> 16 + 15, not 30 + 1
    out = []
    for i in range(n_chunks):
        chunk = leaves[i * size : (i + 1) * size]
        out.append(
            _group(
                f"{base_id}/r{i + 1}",
                _range_label(chunk[0].label, chunk[-1].label),
                category,
                GroupBasis.alpha_range,
                chunk,
            )
        )
    return out


def _bucket(base_id: str, nodes: Iterable[Node], category: AtlasCategory) -> list[_Draft]:
    return _ranges(base_id, [_entity(n, category) for n in nodes], category)


def _count(d: _Draft) -> int:
    d.count = (1 if d.kind == TreeNodeKind.entity else 0) + sum(_count(c) for c in d.children)
    return d.count


def _order(d: _Draft) -> None:
    """Child order: intrinsic where given; else branches by size desc, then leaves by label."""
    if not d.ordered:
        d.children.sort(
            key=lambda c: (
                0 if c.children else 1,
                -c.count if c.children else 0,
                c.label.casefold(),
                c.id,
            )
        )
    for c in d.children:
        _order(c)


def _split_leaves(d: _Draft) -> None:
    """Apply the 30-leaf rule everywhere: too many leaf children become alphabetical ranges."""
    for c in d.children:
        _split_leaves(c)
    leaves = [c for c in d.children if not c.children and c.kind == TreeNodeKind.entity]
    if len(leaves) > MAX_LEAVES and d.category is not None:
        base = d.id if d.id.startswith("T:") else f"T:{d.category.value}/{d.id}"
        d.children = [c for c in d.children if c not in leaves] + _ranges(base, leaves, d.category)


# --- store index ----------------------------------------------------------------------------


class _Index:
    """Outgoing neighbours per (source, relation), sorted, from the pipeline edges."""

    def __init__(self, store: graph.GraphStore) -> None:
        out: dict[tuple[str, Relation], list[str]] = defaultdict(list)
        for edge in store.edges.values():
            out[(edge.source_id, edge.relation)].append(edge.target_id)
        self.out = {k: sorted(v) for k, v in out.items()}
        self.nodes = store.nodes

    def targets(self, source: str, relation: Relation) -> list[str]:
        return self.out.get((source, relation), [])


def _dominant(counts: Counter[str]) -> str | None:
    """Most frequent key, ties by id."""
    if not counts:
        return None
    return min(counts, key=lambda k: (-counts[k], k))


def _cluster_short(store: graph.GraphStore, cluster_id: str) -> str:
    """Cluster label up to its mechanism suffix ("SCN2A, SCN1A, HCN1 disorders · ...")."""
    node = store.nodes.get(cluster_id)
    summary = store.clusters.get(cluster_id)
    label = node.label if node else summary.label if summary else cluster_id
    return label.split(" · ")[0].strip() or label


def _fields(
    ix: _Index, nodes: list[Node], relation: Relation
) -> tuple[dict[str, str | None], dict[str, list[str]]]:
    """Per node: the dominant cluster among the subjects reached via `relation` -> about /
    studies, and the subject ids themselves (for focus genes)."""
    field_of: dict[str, str | None] = {}
    subjects_of: dict[str, list[str]] = {}
    for node in nodes:
        subjects: list[str] = []
        for mid in ix.targets(node.id, relation):
            subjects += ix.targets(mid, Relation.about) + ix.targets(mid, Relation.studies)
        clusters = Counter(c for s in subjects if s in ix.nodes and (c := ix.nodes[s].cluster_id))
        field_of[node.id] = _dominant(clusters)
        subjects_of[node.id] = subjects
    return field_of, subjects_of


def _subject_field(ix: _Index, node: Node, relations: tuple[Relation, ...]) -> str | None:
    clusters = Counter(
        c
        for r in relations
        for s in ix.targets(node.id, r)
        if s in ix.nodes and (c := ix.nodes[s].cluster_id)
    )
    return _dominant(clusters)


def _by_field(
    store: graph.GraphStore,
    base: str,
    category: AtlasCategory,
    nodes: list[Node],
    field_of: Callable[[Node], str | None],
    inner: Callable[[str, str | None, list[Node]], list[_Draft]],
    missing_label: str = "Field not recorded",
) -> list[_Draft]:
    groups: dict[str | None, list[Node]] = defaultdict(list)
    for node in nodes:
        groups[field_of(node)].append(node)
    out = []
    for cid, members in groups.items():
        if cid is None:
            gid = f"{base}/none"
            out.append(
                _group(
                    gid, missing_label, category, GroupBasis.not_recorded, inner(gid, None, members)
                )
            )
        else:
            gid = f"{base}/{cid}"
            out.append(
                _group(
                    gid,
                    _cluster_short(store, cid),
                    category,
                    GroupBasis.research_field,
                    inner(gid, cid, members),
                    ref_id=cid,
                    cluster_id=cid,
                )
            )
    return out


# --- institutions -----------------------------------------------------------------------------

_CLINICAL = re.compile(
    r"hospita|hôpital|hopital|ospedal|spital|klinik|clinic|clínic|clinique|policlinic|"
    r"\bchu\b|\bchru\b|\bnhs\b|\birccs\b|medical cent|medical complex|health system|"
    r"healthcare|health care|ap-hp|assistance publique|children's health|"
    r"kinderspital|universitätsmedizin|klinikum|krankenhaus|\bhosp\b|\bumc\b|health service|"
    r"children's|(epilep\w*|headache|autism) cent|reference cent|centre (de )?référence|"
    r"centre référence|centre de compétence|consultants|specialists|\bhealth$",
    re.IGNORECASE,
)
_ACADEMIC = re.compile(
    r"universit|\buniv\b|\bcoll\b|med sch|medicine$|college|school|faculty|institut|"
    r"istituto|instituto|academ|research|recherche|laborat|\blabs?\b|genetic|genom|"
    r"génétique|génomique|\binserm\b|\bcnrs\b|\bnih\b|national institutes|centre for|"
    r"center for|centro de|consortium|max-planck|riken|broad",
    re.IGNORECASE,
)

INSTITUTION_KIND_LABELS = {
    "clinical": "Hospitals & clinics",
    "academic": "Universities & research institutes",
    "other": "Other organisations",
}


def institution_kind(name: str) -> str:
    """'clinical' when the name mentions a hospital, clinic, medical or reference centre, an
    epilepsy centre, a health service or a children's hospital (checked first: "University
    Hospital X" is clinical), else 'academic' for a university, college, school, institute,
    laboratory, research or genetics centre, else 'other' (companies, foundations, ...)."""
    if _CLINICAL.search(name):
        return "clinical"
    if _ACADEMIC.search(name):
        return "academic"
    return "other"


_COUNTRY_ALIASES = {
    "usa": "United States",
    "u.s.a": "United States",
    "u.s.a.": "United States",
    "us": "United States",
    "u.s.": "United States",
    "united states of america": "United States",
    "uk": "United Kingdom",
    "u.k": "United Kingdom",
    "u.k.": "United Kingdom",
    "england": "United Kingdom",
    "scotland": "United Kingdom",
    "wales": "United Kingdom",
    "great britain": "United Kingdom",
    "london": "United Kingdom",
    "the netherlands": "Netherlands",
    "holland": "Netherlands",
    "rotterdam": "Netherlands",
    "south korea": "South Korea",
    "republic of korea": "South Korea",
    "korea": "South Korea",
    "korea, republic of": "South Korea",
    "p. r. china": "China",
    "p.r.china": "China",
    "p.r. china": "China",
    "pr china": "China",
    "people's republic of china": "China",
    "chengdu": "China",
    "luxemburg": "Luxembourg",
    "québec": "Canada",
    "quebec": "Canada",
    "russian federation": "Russia",
    "czechia": "Czech Republic",
    "türkiye": "Turkey",
    "dianalund": "Denmark",
    "bron": "France",
    "sakyo-ku": "Japan",
}

# US states (names and two-letter codes) that the source stored as the "country".
_US_STATES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "florida", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas",
    "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota", "tennessee", "texas",
    "utah", "vermont", "virginia", "washington", "west virginia", "wisconsin", "wyoming",
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id", "il", "in", "ia",
    "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt",
    "va", "wa", "wv", "wi", "wy",
}  # fmt: skip

_KNOWN_COUNTRIES = {
    "Argentina", "Australia", "Austria", "Bahrain", "Belgium", "Brazil", "Canada", "China",
    "Czech Republic", "Denmark", "Estonia", "Finland", "France", "Georgia", "Germany",
    "Greece", "Hungary", "India", "Ireland", "Israel", "Italy", "Japan", "Kenya",
    "Luxembourg", "Malaysia", "Netherlands", "New Zealand", "Norway", "Oman", "Pakistan",
    "Poland", "Portugal", "Romania", "Russia", "Saudi Arabia", "Singapore", "Slovenia",
    "South Africa", "South Korea", "Spain", "Sweden", "Switzerland", "Taiwan", "Tanzania",
    "Thailand", "Turkey", "United Arab Emirates", "United Kingdom", "United States",
}  # fmt: skip


def normalize_country(value: object) -> str | None:
    """One spelling per country ("USA"/"Texas"/"NY" -> "United States", "UK" -> "United
    Kingdom", "The Netherlands" -> "Netherlands"); a trailing known country in a longer
    string wins ("Leuven Belgium"); unusable values ("and", "Sakyo-ku -") -> None."""
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize("NFC", value).strip().strip("().,;- ").strip()
    text = re.sub(r"\s+", " ", text)
    if not text:
        return None
    key = text.casefold()
    if key in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[key]
    if key in _US_STATES:
        return "United States"
    known = {c.casefold(): c for c in _KNOWN_COUNTRIES}
    if key in known:
        return known[key]
    for name_key, name in known.items():  # "Leuven Belgium", "Canada MG X", "China)"
        if re.search(rf"\b{re.escape(name_key)}\b", key):
            return name
    if len(text) < 4 or not text[0].isupper() or not re.fullmatch(r"[^\W\d_][\w .'-]*", text):
        return None
    return text


# --- category builders -------------------------------------------------------------------------


def _attr(node: Node, key: str) -> Any:
    return (node.attrs or {}).get(key)


def _build_diseases(store: graph.GraphStore, nodes: list[Node]) -> list[_Draft]:
    cat = AtlasCategory.diseases
    clusters = {n.id: n for n in nodes if n.type == NodeType.cluster}
    members: dict[str | None, list[Node]] = defaultdict(list)
    for node in nodes:
        if node.type != NodeType.cluster:
            cid = node.cluster_id
            members[cid if cid and cid != node.id else None].append(node)
    out = []
    for cid in sorted(set(clusters) | {c for c in members if c}):
        kids = _bucket(f"T:diseases/{cid}", members.get(cid, []), cat)
        if cid in clusters:
            d = _entity(clusters[cid], cat)
            d.children = kids
        else:
            d = _group(
                f"T:diseases/{cid}",
                _cluster_short(store, cid),
                cat,
                GroupBasis.mechanism_cluster,
                kids,
                ref_id=cid,
                cluster_id=cid,
            )
        out.append(d)
    if members.get(None):
        gid = "T:diseases/none"
        out.append(
            _group(
                gid,
                "Cluster not recorded",
                cat,
                GroupBasis.not_recorded,
                _bucket(gid, members[None], cat),
            )
        )
    return out


def _lineage(node: Node) -> list[tuple[str, str]] | None:
    raw = _attr(node, "hpo_lineage")
    if not isinstance(raw, list):
        return None
    out = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            return None
        out.append((item["id"], str(item.get("label") or item["id"])))
    return out


def _build_symptoms(store: graph.GraphStore, nodes: list[Node]) -> list[_Draft]:
    """Compressed HPO is_a tree from attrs.hpo_lineage (organ system .. primary parent)."""
    cat = AtlasCategory.symptoms
    by_id = {n.id: n for n in nodes}
    parent: dict[str, str | None] = {}
    labels: dict[str, str] = {}
    own: set[str] = set()
    for node in nodes:  # sorted by id
        chain = _lineage(node)
        if chain is None:
            continue
        prev: str | None = None
        for hid, label in chain:
            if hid == node.id:
                break
            if hid not in own:
                parent.setdefault(hid, prev)
            labels.setdefault(hid, label)
            prev = hid
        parent[node.id] = prev  # a term's own lineage decides its own parent
        own.add(node.id)
    # break cycles (inconsistent lineages) by lifting the offending node to the top
    for start in sorted(parent):
        seen, cur = set(), start
        while cur is not None and cur not in seen:
            seen.add(cur)
            cur = parent.get(cur)
        if cur is not None:
            parent[cur] = None
    kids: dict[str | None, list[str]] = defaultdict(list)
    for hid in sorted(parent):
        kids[parent[hid]].append(hid)

    def build(hid: str) -> list[_Draft]:
        children = [d for c in kids.get(hid, []) for d in build(c)]
        if hid in by_id:
            d = _entity(by_id[hid], cat)
            d.children = children
            return [d]
        if parent.get(hid) is None or len(children) >= 2:
            return [
                _group(
                    f"T:symptoms/{hid}",
                    labels.get(hid, hid),
                    cat,
                    GroupBasis.hpo_class,
                    children,
                    ref_id=hid,
                )
            ]
        return children  # single-child chain: spliced out

    out = [d for top in kids.get(None, []) for d in build(top)]
    unplaced = [n for n in nodes if n.id not in parent]
    if unplaced:
        gid = "T:symptoms/none"
        out.append(
            _group(
                gid,
                "Classification not loaded",
                cat,
                GroupBasis.not_recorded,
                _bucket(gid, unplaced, cat),
            )
        )
    return out


_CHROMOSOME = re.compile(r"^\s*(\d{1,2}|X|Y)(?=[pq\s]|cen|$)", re.IGNORECASE)


def _chromosome(location: object) -> str | None:
    if not isinstance(location, str):
        return None
    if location.strip().lower().startswith("mito"):
        return "MT"
    m = _CHROMOSOME.match(location)
    return m.group(1).upper() if m else None


def _chromosome_order(key: str) -> tuple[int, str]:
    return (int(key), "") if key.isdigit() else ({"X": 23, "Y": 24, "MT": 25}.get(key, 99), key)


def _build_genes(store: graph.GraphStore, nodes: list[Node], ix: _Index) -> list[_Draft]:
    cat = AtlasCategory.genes
    genes = [n for n in nodes if n.type == NodeType.gene]
    gene_ids = {n.id for n in genes}
    variants: dict[str | None, list[Node]] = defaultdict(list)
    for node in nodes:
        if node.type == NodeType.variant:
            owner = next(
                (g for g in ix.targets(node.id, Relation.variant_of) if g in gene_ids), None
            )
            variants[owner].append(node)
    by_chr: dict[str | None, list[_Draft]] = defaultdict(list)
    for gene in genes:
        location = _attr(gene, "location")
        label = f"{gene.label} · {location}" if isinstance(location, str) and location else None
        d = _entity(gene, cat, label)
        d.children = _bucket(f"T:genes/{gene.id}", variants.get(gene.id, []), cat)
        by_chr[_chromosome(location)].append(d)
    out = []
    for key in sorted((k for k in by_chr if k), key=_chromosome_order):
        label = "Mitochondrial DNA" if key == "MT" else f"Chromosome {key}"
        out.append(
            _group(f"T:genes/chr{key}", label, cat, GroupBasis.chromosome, by_chr[key], ref_id=key)
        )
    if by_chr.get(None):
        out.append(
            _group(
                "T:genes/chr-none",
                "Chromosome not recorded",
                cat,
                GroupBasis.not_recorded,
                by_chr[None],
            )
        )
    mechanisms = [n for n in nodes if n.type == NodeType.mechanism]
    if mechanisms:
        out.append(
            _group(
                "T:genes/mechanisms",
                "Mechanisms",
                cat,
                GroupBasis.subcategory,
                _bucket("T:genes/mechanisms", mechanisms, cat),
                ref_id=NodeType.mechanism.value,
            )
        )
    if variants.get(None):
        gid = "T:genes/variants-none"
        out.append(
            _group(
                gid,
                "Gene not recorded",
                cat,
                GroupBasis.not_recorded,
                _bucket(gid, variants[None], cat),
            )
        )
    return out


def _build_pathways(store: graph.GraphStore, nodes: list[Node]) -> list[_Draft]:
    cat = AtlasCategory.pathways
    names = {"go": "Gene Ontology", "reactome": "Reactome"}
    by_source: dict[str | None, list[Node]] = defaultdict(list)
    for node in nodes:
        source = _attr(node, "source")
        by_source[source.lower() if isinstance(source, str) and source else None].append(node)
    out = []
    for source, members in by_source.items():
        base = f"T:pathways/{source or 'none'}"
        kids = []
        by_cluster: dict[str | None, list[Node]] = defaultdict(list)
        for node in members:
            by_cluster[node.cluster_id].append(node)
        for cid, group in by_cluster.items():
            gid = f"{base}/{cid or 'none'}"
            if cid:
                kids.append(
                    _group(
                        gid,
                        _cluster_short(store, cid),
                        cat,
                        GroupBasis.mechanism_cluster,
                        _bucket(gid, group, cat),
                        ref_id=cid,
                        cluster_id=cid,
                    )
                )
            else:
                kids.append(
                    _group(
                        gid,
                        "Cluster not recorded",
                        cat,
                        GroupBasis.not_recorded,
                        _bucket(gid, group, cat),
                    )
                )
        if source:
            out.append(
                _group(
                    base,
                    names.get(source, source.capitalize()),
                    cat,
                    GroupBasis.pathway_source,
                    kids,
                    ref_id=source,
                )
            )
        else:
            out.append(_group(base, "Source not recorded", cat, GroupBasis.not_recorded, kids))
    return out


def _build_researchers(store: graph.GraphStore, nodes: list[Node], ix: _Index) -> list[_Draft]:
    cat = AtlasCategory.researchers
    field_of, subjects_of = _fields(ix, nodes, Relation.authored)

    def inner(gid: str, cid: str | None, members: list[Node]) -> list[_Draft]:
        if cid is None:
            return _bucket(gid, members, cat)
        by_gene: dict[str | None, list[Node]] = defaultdict(list)
        for node in members:
            genes = Counter(
                s
                for s in subjects_of[node.id]
                if s in ix.nodes
                and ix.nodes[s].type == NodeType.gene
                and ix.nodes[s].cluster_id == cid
            )
            by_gene[_dominant(genes)].append(node)
        out = []
        for gene, group in by_gene.items():
            if gene is None:
                sub = f"{gid}/disease-level"
                out.append(
                    _group(
                        sub,
                        "Disease-level papers",
                        cat,
                        GroupBasis.not_recorded,
                        _bucket(sub, group, cat),
                    )
                )
            else:
                sub = f"{gid}/{gene}"
                out.append(
                    _group(
                        sub,
                        ix.nodes[gene].label,
                        cat,
                        GroupBasis.focus_gene,
                        _bucket(sub, group, cat),
                        ref_id=gene,
                    )
                )
        return out

    return _by_field(store, "T:researchers", cat, nodes, lambda n: field_of[n.id], inner)


def _build_doctors(store: graph.GraphStore, nodes: list[Node], ix: _Index) -> list[_Draft]:
    cat = AtlasCategory.doctors
    field_of, _ = _fields(ix, nodes, Relation.investigator_of)
    return _by_field(
        store,
        "T:doctors",
        cat,
        nodes,
        lambda n: field_of[n.id],
        lambda gid, _cid, members: _bucket(gid, members, cat),
    )


def _build_institutions(store: graph.GraphStore, nodes: list[Node]) -> list[_Draft]:
    cat = AtlasCategory.institutions
    by_kind: dict[str, list[Node]] = defaultdict(list)
    for node in nodes:
        by_kind[institution_kind(node.label)].append(node)
    out = []
    for kind in ("clinical", "academic", "other"):
        if not by_kind.get(kind):
            continue
        base = f"T:institutions/{kind}"
        by_country: dict[str | None, list[Node]] = defaultdict(list)
        for node in by_kind[kind]:
            by_country[normalize_country(_attr(node, "country"))].append(node)
        kids = []
        for country, group in by_country.items():
            if country:
                gid = f"{base}/{country}"
                kids.append(
                    _group(
                        gid,
                        country,
                        cat,
                        GroupBasis.country,
                        _bucket(gid, group, cat),
                        ref_id=country,
                    )
                )
            else:
                gid = f"{base}/none"
                kids.append(
                    _group(
                        gid,
                        "Country not recorded",
                        cat,
                        GroupBasis.not_recorded,
                        _bucket(gid, group, cat),
                    )
                )
        out.append(
            _group(
                base,
                INSTITUTION_KIND_LABELS[kind],
                cat,
                GroupBasis.institution_kind,
                kids,
                ref_id=kind,
            )
        )
    return out


YEAR_BANDS: tuple[tuple[str, int, int], ...] = (
    ("Before 2010", -10_000, 2009),
    ("2010–2014", 2010, 2014),
    ("2015–2019", 2015, 2019),
    ("2020–2023", 2020, 2023),
    ("2024 and later", 2024, 10_000),
)

TRIAL_STATUS: dict[str, str] = {
    **dict.fromkeys(
        (
            "RECRUITING",
            "NOT_YET_RECRUITING",
            "ACTIVE_NOT_RECRUITING",
            "ENROLLING_BY_INVITATION",
            "AVAILABLE",
        ),
        "open",
    ),
    **dict.fromkeys(("COMPLETED", "APPROVED_FOR_MARKETING"), "completed"),
    **dict.fromkeys(("TERMINATED", "WITHDRAWN", "SUSPENDED", "NO_LONGER_AVAILABLE"), "stopped"),
}
TRIAL_STATUS_LABELS = {
    "open": "Open",
    "completed": "Completed",
    "stopped": "Stopped",
    "unknown": "Status unknown",
}


def _year(node: Node) -> int | None:
    value = _attr(node, "year")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _build_literature(store: graph.GraphStore, nodes: list[Node], ix: _Index) -> list[_Draft]:
    cat = AtlasCategory.literature
    by_type: dict[NodeType, list[Node]] = defaultdict(list)
    for node in nodes:
        by_type[node.type].append(node)
    out = []

    def years(gid: str, _cid: str | None, members: list[Node]) -> list[_Draft]:
        bands: dict[str | None, list[Node]] = defaultdict(list)
        for node in members:
            y = _year(node)
            band = None if y is None else next(b for b, lo, hi in YEAR_BANDS if lo <= y <= hi)
            bands[band].append(node)
        kids = []
        for band, lo, _hi in YEAR_BANDS:
            if bands.get(band):
                sub = f"{gid}/{lo if lo > 0 else 'pre2010'}"
                kids.append(
                    _group(
                        sub,
                        band,
                        cat,
                        GroupBasis.year_band,
                        _bucket(sub, bands[band], cat),
                        ref_id=band,
                    )
                )
        if bands.get(None):
            sub = f"{gid}/none"
            kids.append(
                _group(
                    sub,
                    "Year not recorded",
                    cat,
                    GroupBasis.not_recorded,
                    _bucket(sub, bands[None], cat),
                )
            )
        return kids

    if by_type.get(NodeType.paper):
        base = "T:literature/papers"
        kids = _by_field(
            store,
            base,
            cat,
            by_type[NodeType.paper],
            lambda n: _subject_field(ix, n, (Relation.about,)),
            years,
        )
        for k in kids:
            k.ordered = True
        out.append(
            _group(base, "Papers", cat, GroupBasis.subcategory, kids, ref_id=NodeType.paper.value)
        )

    if by_type.get(NodeType.trial):
        base = "T:literature/trials"
        by_status: dict[str, list[Node]] = defaultdict(list)
        for node in by_type[NodeType.trial]:
            by_status[TRIAL_STATUS.get(str(_attr(node, "status") or "").upper(), "unknown")].append(
                node
            )
        kids = []
        for status in ("open", "completed", "stopped", "unknown"):
            if by_status.get(status):
                gid = f"{base}/{status}"
                inner = _by_field(
                    store,
                    gid,
                    cat,
                    by_status[status],
                    lambda n: _subject_field(ix, n, (Relation.studies,)),
                    lambda sub, _cid, members: _bucket(sub, members, cat),
                )
                kids.append(
                    _group(
                        gid,
                        TRIAL_STATUS_LABELS[status],
                        cat,
                        GroupBasis.trial_status,
                        inner,
                        ref_id=status,
                    )
                )
        out.append(
            _group(
                base,
                "Trials",
                cat,
                GroupBasis.subcategory,
                kids,
                ref_id=NodeType.trial.value,
                ordered=True,
            )
        )

    if by_type.get(NodeType.grant):
        base = "T:literature/grants"
        by_agency: dict[str | None, list[Node]] = defaultdict(list)
        for node in by_type[NodeType.grant]:
            agency = _attr(node, "agency")
            by_agency[agency if isinstance(agency, str) and agency else None].append(node)
        kids = []
        for agency, members in by_agency.items():
            gid = f"{base}/{agency or 'none'}"
            by_code: dict[str | None, list[Node]] = defaultdict(list)
            for node in members:
                code = _attr(node, "activity_code")
                by_code[code if isinstance(code, str) and code else None].append(node)
            codes = []
            for code, group in by_code.items():
                sub = f"{gid}/{code or 'none'}"
                if code:
                    codes.append(
                        _group(
                            sub,
                            code,
                            cat,
                            GroupBasis.activity_code,
                            _bucket(sub, group, cat),
                            ref_id=code,
                        )
                    )
                else:
                    codes.append(
                        _group(
                            sub,
                            "Activity code not recorded",
                            cat,
                            GroupBasis.not_recorded,
                            _bucket(sub, group, cat),
                        )
                    )
            if agency:
                kids.append(_group(gid, agency, cat, GroupBasis.agency, codes, ref_id=agency))
            else:
                kids.append(_group(gid, "Agency not recorded", cat, GroupBasis.not_recorded, codes))
        out.append(
            _group(base, "Grants", cat, GroupBasis.subcategory, kids, ref_id=NodeType.grant.value)
        )

    if by_type.get(NodeType.claim):
        base = "T:literature/claims"
        out.append(
            _group(
                base,
                "Claims",
                cat,
                GroupBasis.subcategory,
                _bucket(base, by_type[NodeType.claim], cat),
                ref_id=NodeType.claim.value,
            )
        )
    return out


REGISTRY_KIND_LABELS = {
    "registry": "Registries",
    "natural_history_study": "Natural history studies",
}


def _build_community(store: graph.GraphStore, nodes: list[Node]) -> list[_Draft]:
    cat = AtlasCategory.community
    contributed = [n for n in nodes if n.id.startswith(graph.CONTRIB_NODE_PREFIX)]
    rest = [n for n in nodes if not n.id.startswith(graph.CONTRIB_NODE_PREFIX)]
    by_type: dict[NodeType, list[Node]] = defaultdict(list)
    for node in rest:
        by_type[node.type].append(node)
    out = []
    if by_type.get(NodeType.patient_org):
        gid = "T:community/patient-orgs"
        out.append(
            _group(
                gid,
                "Patient organisations",
                cat,
                GroupBasis.subcategory,
                _bucket(gid, by_type[NodeType.patient_org], cat),
                ref_id=NodeType.patient_org.value,
            )
        )
    if by_type.get(NodeType.registry):
        base = "T:community/registries"
        by_kind: dict[str | None, list[Node]] = defaultdict(list)
        for node in by_type[NodeType.registry]:
            kind = _attr(node, "kind")
            by_kind[kind if isinstance(kind, str) and kind else None].append(node)
        kids = []
        for kind, members in by_kind.items():
            gid = f"{base}/{kind or 'none'}"
            if kind:
                label = REGISTRY_KIND_LABELS.get(kind, kind.replace("_", " ").capitalize())
                kids.append(
                    _group(
                        gid,
                        label,
                        cat,
                        GroupBasis.registry_kind,
                        _bucket(gid, members, cat),
                        ref_id=kind,
                    )
                )
            else:
                kids.append(
                    _group(
                        gid,
                        "Kind not recorded",
                        cat,
                        GroupBasis.not_recorded,
                        _bucket(gid, members, cat),
                    )
                )
        out.append(
            _group(
                base,
                "Registries & studies",
                cat,
                GroupBasis.subcategory,
                kids,
                ref_id=NodeType.registry.value,
            )
        )
    others = by_type.get(NodeType.network, []) + [
        n for t, ns in by_type.items() if t not in TYPE_CATEGORY for n in ns
    ]
    if others:
        gid = "T:community/networks"
        out.append(
            _group(
                gid,
                "Networks",
                cat,
                GroupBasis.subcategory,
                _bucket(gid, others, cat),
                ref_id=NodeType.network.value,
            )
        )
    if contributed:
        gid = "T:community/contributed"
        out.append(
            _group(
                gid,
                "Contributed, pending review",
                cat,
                GroupBasis.contributed,
                _bucket(gid, contributed, cat),
            )
        )
    return out


def _build_drafts(store: graph.GraphStore) -> list[_Draft]:
    by_category: dict[AtlasCategory, list[Node]] = {c: [] for c in CATEGORY_ORDER}
    for node in sorted([*store.nodes.values(), *store.contrib_nodes.values()], key=lambda n: n.id):
        if node.id.startswith(graph.CONTRIB_NODE_PREFIX):
            by_category[AtlasCategory.community].append(node)
        else:
            by_category[TYPE_CATEGORY.get(node.type, AtlasCategory.community)].append(node)
    ix = _Index(store)
    builders: dict[AtlasCategory, Callable[[list[Node]], list[_Draft]]] = {
        AtlasCategory.researchers: lambda ns: _build_researchers(store, ns, ix),
        AtlasCategory.institutions: lambda ns: _build_institutions(store, ns),
        AtlasCategory.literature: lambda ns: _build_literature(store, ns, ix),
        AtlasCategory.community: lambda ns: _build_community(store, ns),
        AtlasCategory.pathways: lambda ns: _build_pathways(store, ns),
        AtlasCategory.genes: lambda ns: _build_genes(store, ns, ix),
        AtlasCategory.diseases: lambda ns: _build_diseases(store, ns),
        AtlasCategory.symptoms: lambda ns: _build_symptoms(store, ns),
        AtlasCategory.doctors: lambda ns: _build_doctors(store, ns, ix),
    }
    drafts = []
    for category in CATEGORY_ORDER:
        d = _Draft(
            id=f"T:{category.value}",
            kind=TreeNodeKind.category,
            label=CATEGORY_LABELS[category],
            category=category,
            children=builders[category](by_category[category]),
            ordered=category == AtlasCategory.literature,
        )
        _split_leaves(d)
        _count(d)
        _order(d)
        drafts.append(d)
    return drafts


# --- layout ---------------------------------------------------------------------------------

SPACING = 14.0  # minimum distance between two nodes
R_CATEGORY = 260.0  # radius of the category (trunk) nodes
BRANCH_LENGTHS = (0.0, 0.0, 300.0, 210.0, 160.0, 130.0)  # base branch length by depth
FAN_R0 = 3.0 * SPACING  # distance from a node to its first row of leaves
FAN_ROW = SPACING  # distance between rows of leaves
GAP = math.radians(4)  # empty wedge between two sectors
INNER_MARGIN = math.radians(3)  # branches are shared out over the sector minus this per side
MIN_SECTOR = math.radians(16)
SECTOR_EXPONENT = 0.95
WEDGE_EXPONENT = 0.85
LABEL_OFFSET = 120.0
EDGE_MARGIN = math.radians(0.6)  # keep nodes this far off the sector edges
MAX_TRIES_R = 300


def _h(key: str, salt: str = "") -> float:
    """Deterministic uniform number in [0, 1) from an id."""
    return int(hashlib.sha1(f"{salt}:{key}".encode()).hexdigest()[:8], 16) / 0x100000000


def _need(d: _Draft) -> float:
    """Estimated area a subtree takes: its node, its leaf fan's disc, and its branches."""
    if d.need is None:
        n = sum(1 for c in d.children if not c.children)
        fan = _fan_disc(n)
        own = math.pi * (fan.r if fan else SPACING) ** 2
        d.need = own + sum(_need(c) for c in d.children if c.children)
    return d.need


def _sectors(drafts: list[_Draft]) -> list[tuple[float, float]]:
    """(start, end) per category, clockwise from 12 o'clock (start > end)."""
    total = 2 * math.pi - GAP * len(drafts)
    weights = [max(_need(d), 1.0) ** SECTOR_EXPONENT for d in drafts]
    widths = [0.0] * len(drafts)
    fixed: set[int] = set()
    while True:  # give small categories the minimum, share the rest by weight
        free = total - MIN_SECTOR * len(fixed)
        w_free = sum(w for i, w in enumerate(weights) if i not in fixed)
        changed = False
        for i, w in enumerate(weights):
            if i not in fixed:
                widths[i] = free * w / w_free
                if widths[i] < MIN_SECTOR:
                    fixed.add(i)
                    changed = True
        if not changed:
            break
    for i in fixed:
        widths[i] = MIN_SECTOR
    out = []
    start = math.pi / 2 - GAP / 2
    for w in widths:
        out.append((start, start - w))
        start -= w + GAP
    return out


def _fan(n: int) -> list[tuple[float, float]]:
    """Leaf offsets (distance, angle) in front of a node: rows of arcs, staggered, inner first."""
    pts: list[tuple[float, float]] = []
    half = min(1.15, 0.3 + 0.06 * n)  # half spread grows with the number of leaves
    row = 0
    left = n
    while left:
        rho = FAN_R0 + row * FAN_ROW
        cap = max(1, int(2 * half * rho / SPACING) + 1)
        m = min(cap, left)
        step = SPACING / rho if m == cap else min(2 * half / max(m - 1, 1), 1.6 * SPACING / rho)
        shift = (step / 2) if row % 2 and m < cap else 0.0
        for i in range(m):
            pts.append((rho, (i - (m - 1) / 2) * step + shift))
        left -= m
        row += 1
    return pts


class _Discs:
    """Occupied discs on a uniform grid."""

    def __init__(self, cell: float = 64.0) -> None:
        self.cell = cell
        self.grid: dict[tuple[int, int], list[tuple[float, float, float]]] = defaultdict(list)

    def _cells(self, x: float, y: float, r: float) -> Iterable[tuple[int, int]]:
        c = self.cell
        for i in range(math.floor((x - r) / c), math.floor((x + r) / c) + 1):
            for j in range(math.floor((y - r) / c), math.floor((y + r) / c) + 1):
                yield (i, j)

    def hits(self, x: float, y: float, r: float) -> bool:
        for cell in self._cells(x, y, r):
            for cx, cy, cr in self.grid.get(cell, ()):
                if (cx - x) ** 2 + (cy - y) ** 2 < (cr + r) ** 2:
                    return True
        return False

    def add(self, x: float, y: float, r: float) -> None:
        for cell in self._cells(x, y, r):
            self.grid[cell].append((x, y, r))


def _arrange(children: list[_Draft], ordered: bool) -> list[_Draft]:
    """Angular order of branches: intrinsic order kept; else the largest in the middle."""
    if ordered or len(children) < 3:
        return children
    left: list[_Draft] = []
    right: list[_Draft] = []
    for i, c in enumerate(children):  # children are sorted by size desc
        (right if i % 2 else left).append(c)
    return left[::-1] + right


_OFFSETS = (0, *(s * i for i in range(1, 13) for s in (1, -1)))


def _middle_out(n: int) -> list[int]:
    """Sibling indices from the middle outwards, so the inner space goes to a fork's centre."""
    return sorted(range(n), key=lambda i: (abs(i - (n - 1) / 2), i))


@dataclass
class _Placed:
    x: float
    y: float


@dataclass
class _Fan:
    offsets: list[tuple[float, float]]  # (distance, angle) per leaf
    u: float  # bounding disc centre, along the node's direction
    v: float  # ... and across it
    r: float  # bounding disc radius


def _fan_disc(n: int) -> _Fan | None:
    if not n:
        return None
    offsets = _fan(n)
    us = [rho * math.cos(off) for rho, off in offsets]
    vs = [rho * math.sin(off) for rho, off in offsets]
    fu = (min(min(us), 0.0) + max(us)) / 2
    fv = (min(vs) + max(vs)) / 2
    fr = max(math.hypot(u - fu, v - fv) for u, v in zip(us, vs, strict=True))
    return _Fan(offsets, fu, fv, max(fr, math.hypot(fu, fv)) + SPACING / 2)


class _Grower:
    """Places one category's tree inside its sector."""

    def __init__(self, discs: _Discs, lo: float, hi: float, pos: dict[str, _Placed]) -> None:
        self.discs, self.lo, self.hi, self.pos = discs, lo, hi, pos
        self.reach = 0.0

    def inside(self, x: float, y: float, r: float) -> bool:
        dist = math.hypot(x, y)
        if dist <= r + 1:
            return False
        a = math.atan2(y, x)
        while a > self.hi:
            a -= 2 * math.pi
        while a < self.lo:
            a += 2 * math.pi
        margin = math.asin(min(1.0, r / dist)) + EDGE_MARGIN
        return self.lo + margin <= a <= self.hi - margin

    def place(self, d: _Draft, lo: float, hi: float, parent_r: float, depth: int) -> float:
        """Place a node and its leaf fan at the first free spot, searched outward from an
        irregular distance and angle inside its wedge; returns its radius."""
        leaves = [c for c in d.children if not c.children]
        fan = _fan_disc(len(leaves))
        span = hi - lo
        if depth == 1:
            theta0, r = (lo + hi) / 2, R_CATEGORY - SPACING / 2
        else:
            theta0 = (lo + hi) / 2 + (_h(d.id, "a") - 0.5) * 0.3 * span
            base = BRANCH_LENGTHS[min(depth, len(BRANCH_LENGTHS) - 1)]
            r = parent_r + base * (0.7 + 0.6 * _h(d.id, "r"))
        extent = (fan.r + abs(fan.v)) if fan else SPACING
        chosen = None
        for k in range(MAX_TRIES_R):
            r += SPACING * (0.5 + k / 40)
            pad = max(0.15 * span, 2 * SPACING / r) * (1 + k / 10)
            edge = EDGE_MARGIN + math.asin(min(1.0, extent / r))  # pull inward off the edges
            a_lo, a_hi = max(lo - pad, self.lo + edge), min(hi + pad, self.hi - edge)
            if a_lo > a_hi:
                continue
            step = max(span * 0.12, 0.7 * SPACING / r)
            for j in _OFFSETS:
                theta = min(max(theta0 + j * step, a_lo), a_hi)
                x, y = r * math.cos(theta), r * math.sin(theta)
                if not self.inside(x, y, SPACING / 2) or self.discs.hits(x, y, SPACING / 2):
                    continue
                if fan:
                    cx = x + fan.u * math.cos(theta) - fan.v * math.sin(theta)
                    cy = y + fan.u * math.sin(theta) + fan.v * math.cos(theta)
                    if not self.inside(cx, cy, fan.r) or self.discs.hits(cx, cy, fan.r):
                        continue
                chosen = (x, y, theta)
                break
            if chosen:
                break
        if chosen is None:  # give up on spacing rather than leave the sector
            theta = min(max(theta0, lo), hi)
            chosen = (r * math.cos(theta), r * math.sin(theta), theta)
        x, y, theta = chosen
        self.pos[d.id] = _Placed(x, y)
        self.discs.add(x, y, SPACING / 2)
        self.reach = max(self.reach, r)
        if fan:
            cx = x + fan.u * math.cos(theta) - fan.v * math.sin(theta)
            cy = y + fan.u * math.sin(theta) + fan.v * math.cos(theta)
            self.discs.add(cx, cy, fan.r)
            for leaf, (rho, off) in zip(leaves, fan.offsets, strict=True):
                lx, ly = x + rho * math.cos(theta + off), y + rho * math.sin(theta + off)
                self.pos[leaf.id] = _Placed(lx, ly)
                self.reach = max(self.reach, math.hypot(lx, ly))
        return r

    def grow(self, root: _Draft) -> None:
        """Depth-first, but a node's branch children are all placed (next to it) before any
        of their own subtrees, so siblings stay together and subtrees grow behind them."""
        r = self.place(root, self.lo, self.hi, 0.0, 1)
        lo, hi = self.lo + INNER_MARGIN, self.hi - INNER_MARGIN
        if lo >= hi:
            lo = hi = (self.lo + self.hi) / 2
        stack = [(root, lo, hi, r, 1)]
        while stack:
            d, lo, hi, r, depth = stack.pop()
            branches = _arrange([c for c in d.children if c.children], d.ordered)
            if not branches:
                continue
            weights = [_need(c) ** WEDGE_EXPONENT for c in branches]
            total = sum(weights)
            wedges, cursor = [], hi  # clockwise: first child at the high-angle side
            for w in weights:
                width = (hi - lo) * w / total
                wedges.append((cursor - width, cursor))
                cursor -= width
            placed: dict[int, float] = {}
            for i in _middle_out(len(branches)):
                placed[i] = self.place(branches[i], *wedges[i], r, depth + 1)
            for i in reversed(_middle_out(len(branches))):
                stack.append((branches[i], *wedges[i], placed[i], depth + 1))


def _layout(
    drafts: list[_Draft],
) -> tuple[dict[str, _Placed], list[tuple[float, float]], dict[AtlasCategory, float]]:
    pos: dict[str, _Placed] = {}
    sectors = _sectors(drafts)
    discs = _Discs()
    discs.add(0.0, 0.0, R_CATEGORY * 0.5)  # the hub (logo)
    reach: dict[AtlasCategory, float] = {}
    for draft, (start, end) in zip(drafts, sectors, strict=True):
        grower = _Grower(discs, end, start, pos)
        grower.grow(draft)
        assert draft.category is not None
        reach[draft.category] = grower.reach
    _pull_forks(drafts, pos)
    return pos, sectors, reach


def _pull_forks(drafts: list[_Draft], pos: dict[str, _Placed]) -> None:
    """Move branching nodes (with their leaf fans) out towards their branch children, so a
    limb runs out and forks late instead of many long spokes leaving one point."""
    cell = SPACING
    grid: dict[tuple[int, int], set[str]] = defaultdict(set)

    def key(p: _Placed) -> tuple[int, int]:
        return (math.floor(p.x / cell), math.floor(p.y / cell))

    for nid, p in pos.items():
        grid[key(p)].add(nid)

    def free(x: float, y: float, moving: set[str]) -> bool:
        ci, cj = math.floor(x / cell), math.floor(y / cell)
        for i in range(ci - 1, ci + 2):
            for j in range(cj - 1, cj + 2):
                for other in grid.get((i, j), ()):
                    if other in moving:
                        continue
                    q = pos[other]
                    if (q.x - x) ** 2 + (q.y - y) ** 2 < SPACING**2:
                        return False
        return True

    order: list[tuple[_Draft, _Draft]] = []  # (node, parent), parents before children
    stack = [(c, d) for d in drafts for c in reversed(d.children)]
    while stack:
        node, parent = stack.pop()
        order.append((node, parent))
        stack.extend((c, node) for c in reversed(node.children))
    for node, parent in reversed(order):  # deepest first
        branches = [c for c in node.children if c.children]
        if not branches:
            continue
        group = [node.id] + [c.id for c in node.children if not c.children]
        moving = set(group)
        p, me = pos[parent.id], pos[node.id]
        r_parent, r_me = math.hypot(p.x, p.y), math.hypot(me.x, me.y)
        kids = [pos[c.id] for c in branches]
        radii = sorted(math.hypot(k.x, k.y) for k in kids)
        r_kid = radii[len(radii) // 2]  # median child: the limb runs out into its branches
        vx = sum(k.x * c.count for k, c in zip(kids, branches, strict=True)) + me.x * len(group)
        vy = sum(k.y * c.count for k, c in zip(kids, branches, strict=True)) + me.y * len(group)
        theta0 = math.atan2(vy, vx)
        f = 0.5 + 0.25 * _h(node.id, "f")
        done = False
        for _ in range(8):
            r = r_parent + f * (r_kid - r_parent)
            if r <= r_me + SPACING:
                break
            for da in (0.0, 0.5, -0.5, 1.0, -1.0):
                theta = theta0 + da * SPACING * 2 / r
                dx, dy = r * math.cos(theta) - me.x, r * math.sin(theta) - me.y
                if all(free(pos[i].x + dx, pos[i].y + dy, moving) for i in group):
                    for i in group:
                        old = pos[i]
                        grid[key(old)].discard(i)
                        pos[i] = _Placed(old.x + dx, old.y + dy)
                        grid[key(pos[i])].add(i)
                    done = True
                    break
            if done:
                break
            f *= 0.85


# --- assembly -------------------------------------------------------------------------------


def _xy(value: float) -> float:
    return round(value, 1)


def build_tree(store: graph.GraphStore) -> AtlasTree:
    """Pure, deterministic tree and layout from the in-memory store."""
    drafts = _build_drafts(store)
    pos, sectors, reach = _layout(drafts)
    out: list[AtlasTreeNode] = [
        AtlasTreeNode(
            id=ROOT_ID,
            kind=TreeNodeKind.root,
            label="Atlas",
            parent_id=None,
            category=None,
            depth=0,
            x=0.0,
            y=0.0,
            angle=0.0,
            entity_type=None,
            group_basis=None,
            ref_id=None,
            entity_count=sum(d.count for d in drafts),
            child_count=len(drafts),
            cluster_id=None,
            centrality=None,
        )
    ]

    def emit(d: _Draft, parent: str, depth: int) -> None:
        p = pos[d.id]
        entity = d.entity
        out.append(
            AtlasTreeNode(
                id=d.id,
                kind=d.kind,
                label=d.label,
                parent_id=parent,
                category=d.category,
                depth=depth,
                x=_xy(p.x),
                y=_xy(p.y),
                angle=round(math.atan2(p.y, p.x), 4),
                entity_type=entity.type if entity else None,
                group_basis=d.basis,
                ref_id=d.ref_id,
                entity_count=d.count,
                child_count=len(d.children),
                cluster_id=d.cluster_id,
                centrality=round(entity.centrality, 4)
                if entity and entity.centrality is not None
                else None,
                contributed=bool(entity and entity.id.startswith(graph.CONTRIB_NODE_PREFIX)),
            )
        )
        for child in d.children:
            emit(child, d.id, depth + 1)

    categories: list[AtlasCategorySummary] = []
    for d, (start, end) in zip(drafts, sectors, strict=True):
        emit(d, ROOT_ID, 1)
        assert d.category is not None
        mid = (start + end) / 2
        r = reach.get(d.category, R_CATEGORY) + LABEL_OFFSET
        categories.append(
            AtlasCategorySummary(
                id=d.category,
                node_id=d.id,
                label=d.label,
                entity_count=d.count,
                angle_start=round(start, 4),
                angle_end=round(end, 4),
                label_x=_xy(r * math.cos(mid)),
                label_y=_xy(r * math.sin(mid)),
            )
        )

    layout = graph.atlas_layout()
    return AtlasTree(
        data_version=store.data_version,
        layout_version=LAYOUT_VERSION,
        root_id=ROOT_ID,
        categories=categories,
        nodes=out,
        edges=layout.edges,
        clusters=layout.clusters,
    )


# --- cache (on the store; reset with atlas_cache whenever an overlay is refreshed) ----------


@dataclass
class TreeCache:
    tree: AtlasTree
    by_id: dict[str, AtlasTreeNode]
    payload: tuple[bytes, str] | None = None


def _cached() -> TreeCache:
    store = graph.get_graph()
    cached = store.tree_cache
    if not isinstance(cached, TreeCache):
        tree = build_tree(store)
        cached = TreeCache(tree=tree, by_id={n.id: n for n in tree.nodes})
        store.tree_cache = cached
    return cached


def get_tree() -> AtlasTree:
    """The tree of the current store (cached)."""
    return _cached().tree


def ancestors(node_id: str) -> list[AtlasTreeNode]:
    """Tree ancestors of a node, root first, parent last; [] when the id is not in the tree."""
    by_id = _cached().by_id
    node = by_id.get(node_id)
    chain: list[AtlasTreeNode] = []
    while node is not None and node.parent_id is not None:
        node = by_id.get(node.parent_id)
        if node is not None:
            chain.append(node)
    return chain[::-1]


def tree_payload() -> tuple[bytes, str]:
    """Serialized tree JSON and its ETag ("<data_version>.<layout_version>.<sha1[:16]>")."""
    cached = _cached()
    if cached.payload is None:
        body = cached.tree.model_dump_json().encode()
        digest = hashlib.sha1(body).hexdigest()[:16]
        version = cached.tree.data_version or "empty"
        cached.payload = (body, f'"{version}.{LAYOUT_VERSION}.{digest}"')
    return cached.payload
