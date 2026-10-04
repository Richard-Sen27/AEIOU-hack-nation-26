"""Headline counts for the landing page, computed once per loaded store and kept."""

import hashlib
import weakref
from collections import Counter

from backend.api.services import graph as graph_service
from backend.schemas.enums import NodeType, Origin
from backend.schemas.stats import AtlasStats

# (store, payload, etag) for the store the counts were computed from. A weak reference, so a
# replaced store is not kept alive; a new store (a reload) means a recount.
_cache: tuple[weakref.ref, bytes, str] | None = None


def compute_stats(store: graph_service.GraphStore) -> AtlasStats:
    types = Counter(n.type for n in store.nodes.values())
    origins = Counter(e.origin for e in store.edges.values())
    return AtlasStats(
        data_version=store.data_version,
        diseases=types[NodeType.disease],
        genes=types[NodeType.gene],
        symptoms=types[NodeType.phenotype],
        links_cited=origins[Origin.observed],
        links_computed=origins[Origin.inferred],
    )


def stats_payload() -> tuple[bytes, str]:
    """Serialized counts and their ETag ("<data_version>.<sha1[:16]>"), cached per store."""
    global _cache
    store = graph_service.get_graph()
    if _cache is not None and _cache[0]() is store:
        return _cache[1], _cache[2]
    body = compute_stats(store).model_dump_json().encode()
    digest = hashlib.sha1(body).hexdigest()[:16]
    etag = f'"{store.data_version or "empty"}.{digest}"'
    _cache = (weakref.ref(store), body, etag)
    return body, etag
