"""Search: trigram on node_synonyms + vector on nodes.embedding + type/centrality boost.

Queries may contain health terms: they are never logged and never echoed in errors.
"""

import asyncio
import logging
import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.services.graph import GraphStore, get_graph, normalize_name
from backend.schemas.enums import (
    EdgeStatus,
    MatchKind,
    NodeType,
    Relation,
    confidence_level,
)
from backend.schemas.search import RankedCluster, SearchResponse, SearchResult

log = logging.getLogger(__name__)

EXACT_ID_SCORE = 3.0
EXACT_NAME_SCORE = 2.5
EXACT_SYNONYM_SCORE = 2.2
PHRASE_SCORE = 1.2  # a known name appears inside a longer query
TRIGRAM_BASE = 0.5  # + similarity (0.3..1)
VECTOR_MIN_SIM = 0.58
VECTOR_WINDOW = 0.08  # keep vector hits within this distance of the best vector hit
VECTOR_SCALE = 2.5  # (sim - 0.5) * scale
VECTOR_TIMEOUT_S = 5.0
CANDIDATES = 200
TYPE_BOOST: dict[NodeType, float] = {
    NodeType.disease: 0.15,
    NodeType.gene: 0.12,
    NodeType.phenotype: 0.10,
    NodeType.patient_org: 0.08,
    NodeType.mechanism: 0.08,
    NodeType.cluster: 0.06,
    NodeType.pathway: 0.05,
    NodeType.registry: 0.05,
    NodeType.trial: 0.03,
}
CENTRALITY_BOOST = 0.15
MECHANISM_TYPES = frozenset({NodeType.mechanism, NodeType.pathway, NodeType.gene, NodeType.cluster})

_warm_lock = threading.Lock()
_warm_thread: threading.Thread | None = None


def warm_up() -> None:
    """Load the embedding model in a background thread (first load is slow)."""
    global _warm_thread
    with _warm_lock:
        if _warm_thread is not None:
            return

        def _load() -> None:
            try:
                from backend.embeddings import embed_query

                embed_query("warm up")
            except Exception as exc:  # noqa: BLE001 - vector search degrades to trigram only
                log.warning("embedding warm-up failed (%s)", type(exc).__name__)

        _warm_thread = threading.Thread(target=_load, name="embedding-warmup", daemon=True)
        _warm_thread.start()


@dataclass
class _Hit:
    node_id: str
    type: NodeType
    label: str
    cluster_id: str | None
    centrality: float | None
    base: float
    kind: MatchKind
    synonym: str | None = None
    lexical: bool = False
    vector: float = 0.0


def _better(old: _Hit | None, new: _Hit) -> _Hit:
    if old is None:
        return new
    best = new if new.base > old.base else old
    best.lexical = old.lexical or new.lexical
    best.vector = max(old.vector, new.vector)
    return best


def _store_hit(
    store: GraphStore, node_id: str, base: float, kind: MatchKind, synonym: str | None
) -> _Hit | None:
    node = store.nodes.get(node_id)
    if node is None:
        return None
    return _Hit(
        node_id,
        node.type,
        node.label,
        node.cluster_id,
        node.centrality,
        base,
        kind,
        synonym,
        lexical=True,
    )


_CURIE = re.compile(r"^([A-Z]+)[:_ ]+0*(\d+)$")
PADDED_PREFIXES = {"MONDO": 7, "HP": 7}  # "MONDO:7606" -> "MONDO:0007606"


def _id_candidates(raw: str) -> list[str]:
    out = [raw, raw.replace("_", ":", 1)]
    if m := _CURIE.match(raw):
        prefix, number = m.groups()
        out.append(f"{prefix}:{number.zfill(PADDED_PREFIXES.get(prefix, 0))}")
    return list(dict.fromkeys(out))


_ID_QUERY = re.compile(r"^[A-Z][A-Z0-9.-]*[:_]\s*[A-Z0-9][A-Z0-9._-]*$")


def _is_id_query(q: str) -> bool:
    """A prefixed identifier ("MONDO:0007606", "HP_0001263", "ORPHA:337", "PMID:2317429")."""
    return bool(_ID_QUERY.match(q.strip().upper()))


def _exact_hits(store: GraphStore, q: str) -> list[_Hit]:
    hits: list[_Hit] = []
    raw = q.strip().upper()
    for candidate in _id_candidates(raw):
        if (nid := store.id_index.get(candidate)) and (
            hit := _store_hit(store, nid, EXACT_ID_SCORE, MatchKind.exact, None)
        ):
            hits.append(hit)
            break
    key = normalize_name(q)
    for nid, synonym in store.name_index.get(key, ()):
        base = EXACT_SYNONYM_SCORE if synonym else EXACT_NAME_SCORE
        if synonym is None and store.nodes[nid].type == NodeType.gene:
            base += 0.2  # gene symbols beat diseases that merely mention them
        if hit := _store_hit(store, nid, base, MatchKind.exact, synonym):
            hits.append(hit)
    return hits


def _phrase_hits(store: GraphStore, q: str) -> list[_Hit]:
    """Known names (2+ words or 4+ chars) appearing inside a longer query."""
    words = normalize_name(q).split()
    if len(words) < 2:
        return []
    hits: list[_Hit] = []
    for size in range(min(6, len(words) - 1), 0, -1):
        for start in range(len(words) - size + 1):
            phrase = " ".join(words[start : start + size])
            if len(phrase) < 4:
                continue
            for nid, synonym in store.name_index.get(phrase, ()):
                coverage = size / len(words)
                hit = _store_hit(
                    store, nid, PHRASE_SCORE + 0.5 * coverage, MatchKind.trigram, synonym
                )
                if hit:
                    hits.append(hit)
    return hits


def _type_clause(types: Sequence[NodeType] | None, column: str) -> str:
    return f" AND {column} = ANY(:types)" if types else ""


_UNACCENT_Q = "public.f_unaccent(lower(:q))"


def _trigram_sql(types: Sequence[NodeType] | None) -> str:
    syn = "public.f_unaccent(lower(s.synonym))"
    lab = "public.f_unaccent(lower(n.label))"
    return (
        "SELECT m.node_id, m.synonym, max(m.sim) AS sim, n.type, n.label, n.cluster_id,"
        " n.centrality FROM ("
        f" SELECT s.node_id, s.synonym, greatest(similarity({syn}, {_UNACCENT_Q}),"
        f" word_similarity({_UNACCENT_Q}, {syn})) AS sim FROM node_synonyms s"
        f" WHERE {syn} % {_UNACCENT_Q} OR {_UNACCENT_Q} <% {syn}"
        " UNION ALL"
        f" SELECT n.id, NULL, greatest(similarity({lab}, {_UNACCENT_Q}),"
        f" word_similarity({_UNACCENT_Q}, {lab})) FROM nodes n"
        f" WHERE {lab} % {_UNACCENT_Q} OR {_UNACCENT_Q} <% {lab}"
        ") m JOIN nodes n ON n.id = m.node_id WHERE true"
        + _type_clause(types, "n.type")
        + " GROUP BY m.node_id, m.synonym, n.type, n.label, n.cluster_id, n.centrality"
        " ORDER BY sim DESC LIMIT :limit"
    )


def _vector_sql(types: Sequence[NodeType] | None) -> str:
    return (
        "SELECT id, type, label, cluster_id, centrality,"
        " 1 - (embedding <=> CAST(:v AS vector)) AS sim FROM nodes"
        " WHERE embedding IS NOT NULL"
        + _type_clause(types, "type")
        + " ORDER BY embedding <=> CAST(:v AS vector) LIMIT :limit"
    )


async def _trigram_hits(db: AsyncSession, q: str, types: Sequence[NodeType] | None) -> list[_Hit]:
    params: dict = {"q": q, "limit": CANDIDATES}
    if types:
        params["types"] = [t.value for t in types]
    rows = (await db.execute(text(_trigram_sql(types)), params)).mappings()
    hits = []
    for r in rows:
        try:
            ntype = NodeType(r["type"])
        except ValueError:
            continue
        hits.append(
            _Hit(
                r["node_id"],
                ntype,
                r["label"],
                r["cluster_id"],
                r["centrality"],
                TRIGRAM_BASE + float(r["sim"]),
                MatchKind.trigram,
                r["synonym"],
                lexical=True,
            )
        )
    return hits


async def _embed(q: str) -> list[float] | None:
    try:
        from backend.embeddings import embed_query

        return await asyncio.wait_for(asyncio.to_thread(embed_query, q), VECTOR_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - degrade to lexical search
        log.warning("query embedding unavailable (%s)", type(exc).__name__)
        return None


async def _vector_hits(db: AsyncSession, q: str, types: Sequence[NodeType] | None) -> list[_Hit]:
    vector = await _embed(q)
    if vector is None:
        return []
    params: dict = {"v": "[" + ",".join(f"{x:.6f}" for x in vector) + "]", "limit": 30}
    if types:
        params["types"] = [t.value for t in types]
    rows = list((await db.execute(text(_vector_sql(types)), params)).mappings())
    if not rows:
        return []
    top = float(rows[0]["sim"])
    hits = []
    for r in rows:
        sim = float(r["sim"])
        if sim < VECTOR_MIN_SIM or sim < top - VECTOR_WINDOW:
            break
        try:
            ntype = NodeType(r["type"])
        except ValueError:
            continue
        hits.append(
            _Hit(
                r["id"],
                ntype,
                r["label"],
                r["cluster_id"],
                r["centrality"],
                (sim - 0.5) * VECTOR_SCALE,
                MatchKind.vector,
                vector=sim,
            )
        )
    return hits


def _final_score(hit: _Hit) -> float:
    score = hit.base + TYPE_BOOST.get(hit.type, 0.0) + CENTRALITY_BOOST * (hit.centrality or 0.0)
    if hit.lexical and hit.vector:
        score += 0.1
    return round(score, 6)


async def search(
    db: AsyncSession,
    q: str,
    *,
    types: Sequence[NodeType] | None = None,
    limit: int = 10,
    expert: bool = False,
) -> SearchResponse:
    """Typed matches with the matched synonym; expert mechanism queries add ranked clusters."""
    store = get_graph()
    query = q.strip()
    if not query:
        return SearchResponse(results=[], data_version=store.data_version)
    types = list(types) if types else None

    merged: dict[str, _Hit] = {}
    exact = _exact_hits(store, query)
    if _is_id_query(query):
        # An identifier is looked up, not matched: no trigram or vector look-alikes.
        lexical, vector = exact, []
    else:
        lexical = exact + _phrase_hits(store, query)
        lexical += await _trigram_hits(db, query, None if expert else types)
        vector = await _vector_hits(db, query, None if expert else types)
    for hit in lexical + vector:
        merged[hit.node_id] = _better(merged.get(hit.node_id), hit)

    ranked = sorted(merged.values(), key=lambda h: (-_final_score(h), h.node_id))
    allowed = set(types) if types else None
    results = [
        SearchResult(
            id=h.node_id,
            type=h.type,
            label=h.label,
            matched_synonym=h.synonym,
            score=_final_score(h),
            match_kind=h.kind,
            cluster_id=h.cluster_id,
        )
        for h in ranked
        if allowed is None or h.type in allowed
    ][:limit]
    clusters = rank_clusters(store, query, ranked) if expert else []
    return SearchResponse(
        results=results, ranked_clusters=clusters, data_version=store.data_version
    )


# --- expert mode: rank clusters for a mechanism query ----------------------------------------


def _disease_support(
    store: GraphStore, disease_id: str, matched_id: str
) -> tuple[float, list[str]]:
    """Strongest active chain disease -> gene [-> mechanism/pathway] to a matched node."""
    matched = store.nodes[matched_id]
    best: tuple[float, list[str]] = (0.0, [])
    for eid in store.incident.get(disease_id, ()):
        cause = store.edges[eid]
        if (
            cause.relation != Relation.caused_by_variant_in
            or cause.source_id != disease_id
            or cause.status != EdgeStatus.active
            or store.flag_counts.get(eid)
        ):
            continue
        gene = cause.target_id
        if matched.type == NodeType.gene:
            if gene == matched_id and cause.confidence > best[0]:
                best = (cause.confidence, [eid])
            continue
        relation = (
            Relation.acts_via if matched.type == NodeType.mechanism else Relation.participates_in
        )
        for gid in store.incident.get(gene, ()):
            link = store.edges[gid]
            if (
                link.relation == relation
                and link.source_id == gene
                and link.target_id == matched_id
                and link.status == EdgeStatus.active
                and not store.flag_counts.get(gid)
            ):
                strength = cause.confidence * link.confidence
                if strength > best[0]:
                    best = (strength, [eid, gid])
    return best


def rank_clusters(store: GraphStore, query: str, hits: Sequence[_Hit]) -> list[RankedCluster]:
    """Clusters ranked by how well their members connect to the matched mechanism nodes.

    score = 0.5 * coverage * mean chain strength (members reaching a matched node via
    caused_by_variant_in -> acts_via / participates_in) + 0.3 if the cluster label or
    mechanism summary names a matched mechanism/pathway + 0.2 * the cluster's own match.
    """
    matched = {h.node_id: h for h in hits if h.type in MECHANISM_TYPES and h.base >= 0.2}
    if not matched or not store.clusters:
        return []
    names = [
        normalize_name(store.nodes[m].label)
        for m, h in matched.items()
        if h.type in (NodeType.mechanism, NodeType.pathway)
    ]
    targets = [m for m, h in matched.items() if h.type != NodeType.cluster]
    out: list[RankedCluster] = []
    for cid, cluster in store.clusters.items():
        diseases = [
            m for m in store.members.get(cid, ()) if store.nodes[m].type == NodeType.disease
        ]
        strengths: list[float] = []
        edge_ids: set[str] = set()
        reached: set[str] = set()
        for disease in diseases:
            best = (0.0, [], "")
            for target in targets:
                strength, chain = _disease_support(store, disease, target)
                if strength > best[0]:
                    best = (strength, chain, target)
            if best[0] > 0:
                strengths.append(best[0])
                edge_ids.update(best[1])
                reached.add(best[2])
        coverage = len(strengths) / len(diseases) if diseases else 0.0
        mean_strength = sum(strengths) / len(strengths) if strengths else 0.0
        text_blob = normalize_name(f"{cluster.label} {cluster.mechanism_summary or ''}")
        text_match = any(n and f" {n} " in f" {text_blob} " for n in names)
        own = matched.get(cid)
        own_score = min(1.0, own.base / 1.5) if own else 0.0
        score = 0.5 * coverage * mean_strength + (0.3 if text_match else 0.0) + 0.2 * own_score
        if score <= 0:
            continue
        trials = {
            store.edges[eid].source_id
            for d in diseases
            for eid in store.incident.get(d, ())
            if store.edges[eid].relation == Relation.studies and store.edges[eid].target_id == d
        }
        confidences = [store.edges[e].confidence for e in edge_ids]
        strength = round(sum(confidences) / len(confidences), 6) if confidences else 0.0
        if own:
            reached.add(cid)
        out.append(
            RankedCluster(
                cluster=cluster,
                score=round(score, 6),
                member_count=len(diseases) or cluster.member_count,
                trial_count=len(trials),
                evidence_strength=strength,
                evidence_level=confidence_level(strength),
                matched_node_ids=sorted(reached),
                edge_ids=sorted(edge_ids),
            )
        )
    out.sort(key=lambda r: (-r.score, r.cluster.id))
    return out[:10]
