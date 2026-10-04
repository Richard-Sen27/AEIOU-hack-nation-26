"""Atlas tree: the logo hub (``T:root``) with one radial tree per category.

The tree is a navigation structure only; it never changes how nodes are connected. Every
store node (contribution overlay included) appears exactly once as an entity leaf.

Minimal version: root -> 9 categories -> alphabetical ranges of at most 30 -> entities, laid
out on an even polar grid. Angles are standard polar angles (counter-clockwise from +x, y
up); categories run clockwise from 12 o'clock.
"""

import hashlib
import math
from dataclasses import dataclass

from backend.api.services import graph
from backend.schemas.atlas import (
    AtlasCategory,
    AtlasCategorySummary,
    AtlasTree,
    AtlasTreeNode,
    GroupBasis,
    TreeNodeKind,
)
from backend.schemas.enums import NodeType
from backend.schemas.graph import Node

LAYOUT_VERSION = 1
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

R_CATEGORY = 180.0
R_STEP = 140.0
GAP = math.radians(3)
LABEL_OFFSET = 120.0


@dataclass
class _Draft:
    id: str
    kind: TreeNodeKind
    label: str
    category: AtlasCategory | None
    basis: GroupBasis | None = None
    entity: Node | None = None
    children: list["_Draft"] | None = None

    @property
    def entity_count(self) -> int:
        own = 1 if self.kind == TreeNodeKind.entity else 0
        return own + sum(c.entity_count for c in self.children or ())


def _sort_key(node: Node) -> tuple[str, str]:
    return (node.label.casefold(), node.id)


def _range_label(first: str, last: str) -> str:
    a, b = first.strip()[:2] or "?", last.strip()[:2] or "?"
    return f"{a.capitalize()}–{b.capitalize()}"


def _entity(node: Node, category: AtlasCategory) -> _Draft:
    return _Draft(
        id=node.id, kind=TreeNodeKind.entity, label=node.label, category=category, entity=node
    )


def _category_draft(category: AtlasCategory, members: list[Node]) -> _Draft:
    members = sorted(members, key=_sort_key)
    if len(members) <= MAX_LEAVES:
        children = [_entity(n, category) for n in members]
    else:
        children = []
        for i in range(0, len(members), MAX_LEAVES):
            chunk = members[i : i + MAX_LEAVES]
            children.append(
                _Draft(
                    id=f"T:{category.value}/range-{i // MAX_LEAVES + 1:03d}",
                    kind=TreeNodeKind.group,
                    label=_range_label(chunk[0].label, chunk[-1].label),
                    category=category,
                    basis=GroupBasis.alpha_range,
                    children=[_entity(n, category) for n in chunk],
                )
            )
    return _Draft(
        id=f"T:{category.value}",
        kind=TreeNodeKind.category,
        label=CATEGORY_LABELS[category],
        category=category,
        children=children,
    )


def build_tree(store: graph.GraphStore) -> AtlasTree:
    """Pure, deterministic tree and layout from the in-memory store."""
    by_category: dict[AtlasCategory, list[Node]] = {c: [] for c in CATEGORY_ORDER}
    for node in list(store.nodes.values()) + list(store.contrib_nodes.values()):
        by_category[TYPE_CATEGORY.get(node.type, AtlasCategory.community)].append(node)
    drafts = [_category_draft(c, by_category[c]) for c in CATEGORY_ORDER]

    out: list[AtlasTreeNode] = []
    max_radius: dict[AtlasCategory, float] = {}

    def emit(d: _Draft, parent: str | None, depth: int, a0: float, a1: float) -> None:
        span = a1 - a0
        angle = (a0 + a1) / 2
        radius = 0.0 if depth == 0 else R_CATEGORY + R_STEP * (depth - 1)
        if d.kind == TreeNodeKind.entity:
            radius += 40.0 * (len(out) % 3)  # stagger leaves over 3 rows
        x, y = radius * math.cos(angle), radius * math.sin(angle)
        if d.category is not None:
            max_radius[d.category] = max(max_radius.get(d.category, 0.0), radius)
        entity = d.entity
        children = d.children or []
        out.append(
            AtlasTreeNode(
                id=d.id,
                kind=d.kind,
                label=d.label,
                parent_id=parent,
                category=d.category,
                depth=depth,
                x=round(x, 2),
                y=round(y, 2),
                angle=round(angle, 5),
                entity_type=entity.type if entity else None,
                group_basis=d.basis,
                ref_id=None,
                entity_count=d.entity_count,
                child_count=len(children),
                cluster_id=entity.cluster_id if entity else None,
                centrality=entity.centrality if entity else None,
                contributed=bool(entity and entity.id.startswith(graph.CONTRIB_NODE_PREFIX)),
            )
        )
        total = sum(c.entity_count for c in children) or 1
        start = a0
        for child in children:
            width = span * child.entity_count / total
            emit(child, d.id, depth + 1, start, start + width)
            start += width

    sector = (2 * math.pi - GAP * len(drafts)) / len(drafts)
    out.append(
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
            entity_count=sum(d.entity_count for d in drafts),
            child_count=len(drafts),
            cluster_id=None,
            centrality=None,
        )
    )
    categories: list[AtlasCategorySummary] = []
    for i, d in enumerate(drafts):
        # clockwise from 12 o'clock: angles decrease
        start = math.pi / 2 - GAP / 2 - i * (sector + GAP)
        end = start - sector
        emit(d, ROOT_ID, 1, end, start)
        assert d.category is not None
        mid = (start + end) / 2
        r = max_radius.get(d.category, R_CATEGORY) + LABEL_OFFSET
        categories.append(
            AtlasCategorySummary(
                id=d.category,
                node_id=d.id,
                label=d.label,
                entity_count=d.entity_count,
                angle_start=round(start, 5),
                angle_end=round(end, 5),
                label_x=round(r * math.cos(mid), 2),
                label_y=round(r * math.sin(mid), 2),
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


# --- cache (in-module for now; reset whenever the store or an overlay is replaced) ----------


@dataclass
class _Cached:
    key: tuple[object, ...]
    tree: AtlasTree
    by_id: dict[str, AtlasTreeNode]
    payload: tuple[bytes, str] | None = None


_cache: _Cached | None = None


def _key(store: graph.GraphStore) -> tuple[object, ...]:
    return (store, store.flag_counts, store.contrib_nodes, store.contrib_edges)


def _cached() -> _Cached:
    global _cache
    store = graph.get_graph()
    key = _key(store)
    if (
        _cache is None
        or len(_cache.key) != len(key)
        or any(a is not b for a, b in zip(_cache.key, key, strict=True))
    ):
        tree = build_tree(store)
        _cache = _Cached(key=key, tree=tree, by_id={n.id: n for n in tree.nodes})
    return _cache


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
