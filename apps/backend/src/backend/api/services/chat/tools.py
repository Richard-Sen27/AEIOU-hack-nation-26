"""The orchestrator's tools as typed Pydantic tools over the backend services.

`extract_entities` and the first `resolve_to_ids` run in code before the first model round
(`extract` + `resolve`), so the model starts with resolved chips; the model is offered the
other five tools. Every tool output the model sees is recorded in TurnState; the post-checks
only accept edge and node IDs that a tool returned in this turn."""

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from backend.api.errors import ApiError
from backend.api.services import graph as graph_service
from backend.api.services import path as path_service
from backend.api.services import search as search_service
from backend.api.services.explanation.common import base_language, pick
from backend.db.session import user_transaction
from backend.llm import LLMClient, Tool
from backend.schemas.chat import Chip, FollowUp
from backend.schemas.common import Lens
from backend.schemas.enums import (
    AgeRange,
    ChipType,
    NodeType,
    PathFamily,
    PathStatus,
    Relation,
)
from backend.schemas.graph import Edge, Node
from backend.schemas.path import Path, PathResponse
from backend.schemas.profile import PatientProfile

MAX_NEIGHBORHOOD_EDGES = 60
CHIP_NODE_TYPES: dict[ChipType, NodeType] = {
    ChipType.disease: NodeType.disease,
    ChipType.gene: NodeType.gene,
    ChipType.variant: NodeType.variant,
    ChipType.symptom: NodeType.phenotype,
}
_RELATION_PRIORITY = {
    Relation.same_gene_same_mechanism: 0,
    Relation.same_gene_different_mechanism: 0,
    Relation.shared_pathway: 0,
    Relation.similar_symptoms: 0,
    Relation.shared_gene: 0,
    Relation.shared_researcher: 1,
    Relation.suggested_by_neighbour: 1,
    Relation.serves: 1,
    Relation.runs: 1,
    Relation.studies: 1,
    Relation.funds_research_on: 2,
    Relation.caused_by_variant_in: 2,
    Relation.acts_via: 2,
    Relation.candidate_phenotype: 2,
    Relation.investigator_of: 3,
    Relation.pi_of: 3,
    Relation.near_on_chromosome: 3,
}

STATUS_TEXT = {
    "start": {"en": "Checking your message", "de": "Nachricht wird geprüft"},
    "extract_entities": {"en": "Reading your message", "de": "Nachricht wird gelesen"},
    "resolve_to_ids": {"en": "Matching terms to the atlas", "de": "Begriffe werden zugeordnet"},
    "search_graph": {"en": "Searching the atlas", "de": "Atlas wird durchsucht"},
    "get_neighborhood": {
        "en": "Looking at connected diseases",
        "de": "Verbundene Erkrankungen werden angesehen",
    },
    "find_path": {
        "en": "Finding the most trustworthy route",
        "de": "Verlässlichste Verbindung wird gesucht",
    },
    "ask_followup": {"en": "Choosing one question", "de": "Eine Rückfrage wird gewählt"},
    "answer": {"en": "Writing the answer", "de": "Antwort wird geschrieben"},
    "checks": {
        "en": "Checking citations and safety",
        "de": "Quellen und Sicherheit werden geprüft",
    },
}

FOLLOWUP_TEXT = {
    "question": {
        "en": "Have you noticed signs of {label}?",
        "de": "Haben Sie Anzeichen von „{label}“ bemerkt?",
    },
    "replies": {"en": "Yes|No|Not sure", "de": "Ja|Nein|Weiß nicht"},
}


# ---- tool inputs and outputs --------------------------------------------------------------


class Mention(BaseModel):
    text: str = Field(description="The mention as written by the user.")
    english: str | None = Field(
        None, description="English term for search (HPO-style for symptoms)."
    )
    negated: bool = Field(description="True when the user says it is absent.")


class Extraction(BaseModel):
    diseases: list[Mention]
    genes: list[Mention]
    variants: list[Mention] = Field(description="Variants in HGVS notation where possible.")
    symptoms: list[Mention]
    age_years: int | None = Field(description="Age in years, if stated.")
    age_range: AgeRange | None = Field(
        None, description="Age range when no exact age is stated ('my toddler' = 1-5)."
    )
    about_child: bool = Field(
        False,
        description="True when the text describes the user's child or another minor they care "
        "for ('my son', 'our daughter', 'my baby').",
    )
    onset: str | None = Field(description="Disease onset, if stated (e.g. 'neonatal').")
    country: str | None = Field(description="ISO 3166-1 alpha-2 country, if stated.")


class MentionIn(BaseModel):
    text: str = Field(description="Mention (prefer the English term).")
    type: ChipType
    negated: bool


class ResolveIn(BaseModel):
    mentions: list[MentionIn] = Field(
        description="Mentions to resolve; empty = everything the extraction found."
    )


class SearchIn(BaseModel):
    query: str
    node_types: list[NodeType] | None = Field(None, description="Restrict to these node types.")
    limit: int | None = Field(None, description="Max results (default 8, max 20).")
    expert: bool | None = Field(
        None, description="Mechanism query returning ranked clusters (defaults to expert mode)."
    )


class NeighborhoodIn(BaseModel):
    node_id: str


class PathIn(BaseModel):
    from_id: str
    to_id: str
    family: PathFamily | None = Field(None, description="dna, symptoms, research or all (default).")
    include_vus: bool | None = Field(
        None,
        description="Route through variants of uncertain significance (VUS). Leave null/false; "
        "set true only when the user explicitly asks to include uncertain variants.",
    )


class FollowupIn(BaseModel):
    candidate_cluster_ids: list[str] = Field(
        description="Remaining candidate clusters (CLUSTER:... ids) the answer should separate."
    )


# ---- turn state ---------------------------------------------------------------------------


@dataclass
class TurnState:
    lens: Lens
    message: str
    profile: PatientProfile
    reply_language: str = "en"
    edges: dict[str, Edge] = field(default_factory=dict)
    edge_ids: set[str] = field(default_factory=set)
    nodes: dict[str, Node] = field(default_factory=dict)
    node_ids: set[str] = field(default_factory=set)
    chips: dict[tuple[str, str], Chip] = field(default_factory=dict)
    extraction: Extraction | None = None
    paths: list[PathResponse] = field(default_factory=list)
    follow_up: FollowUp | None = None
    vus_in_paths: bool = False  # a find_path with include_vus returned a route through a VUS
    tool_errors: Counter = field(default_factory=Counter)

    def see_edge(self, edge: Edge) -> None:
        self.edges[edge.id] = edge
        self.edge_ids.add(edge.id)
        self.node_ids.update((edge.source_id, edge.target_id))

    def see_node(self, node: Node) -> None:
        self.nodes[node.id] = node
        self.node_ids.add(node.id)

    def profile_ids(self) -> set[str]:
        p = self.profile
        ids = {d.id for d in p.diseases} | {g.id for g in p.genes} | {x.id for x in p.phenotypes}
        ids |= {v.clinvar_id for v in p.variants if v.clinvar_id}
        return ids

    def add_chip(self, chip: Chip) -> None:
        key = (chip.type.value, chip.id or chip.label.lower())
        if key not in self.chips:
            self.chips[key] = chip

    def status_text(self, key: str) -> str:
        return pick(STATUS_TEXT.get(key, STATUS_TEXT["start"]), self.reply_language)


# ---- compact views for the model ----------------------------------------------------------


def _edge_view(edge: Edge) -> dict[str, Any]:
    view = {
        "id": edge.id,
        "source": edge.source_id,
        "relation": edge.relation.value,
        "target": edge.target_id,
        "confidence": round(edge.confidence, 2),
        "origin": edge.origin.value,
        "status": edge.status.value,
    }
    if edge.contradiction_count:
        view["contradicting_evidence"] = edge.contradiction_count
    if edge.explanation:
        view["explanation"] = edge.explanation  # why a computed link exists (a hypothesis)
    return view


def _node_view(node: Node) -> dict[str, Any]:
    view: dict[str, Any] = {"id": node.id, "type": node.type.value, "label": node.label}
    if node.cluster_id:
        view["cluster_id"] = node.cluster_id
    if node.type == NodeType.variant and node.attrs.get("classification"):
        view["classification"] = node.attrs["classification"]
    return view


def _path_view(state: TurnState, path: Path) -> dict[str, Any]:
    steps = []
    for step in path.steps:
        state.see_edge(step.edge)
        state.see_node(step.from_node)
        state.see_node(step.to_node)
        steps.append(
            {
                "edge_id": step.edge.id,
                "from": step.from_node.label,
                "relation": step.edge.relation.value,
                "to": step.to_node.label,
                "confidence": round(step.edge.confidence, 2),
                "origin": step.edge.origin.value,
                "status": step.edge.status.value,
                "contradicting_evidence": step.edge.contradiction_count,
            }
        )
    return {
        "path_id": path.path_id,
        "edge_ids": path.edge_ids,
        "supported": path.supported,
        "min_confidence": round(path.min_confidence, 2),
        "all_observed": path.all_observed,
        "all_active": path.all_active,
        "steps": steps,
    }


def _paths_touch_vus(resp: PathResponse) -> bool:
    paths = list(resp.paths)
    if resp.coverage is not None and resp.coverage.closest_partial_path is not None:
        paths.append(resp.coverage.closest_partial_path)
    return any(
        graph_service.is_vus(node)
        for p in paths
        for step in p.steps
        for node in (step.from_node, step.to_node)
    )


# ---- tools --------------------------------------------------------------------------------

EXTRACT_INSTRUCTIONS = (
    "Extract medical mentions from the user's text for a rare-disease atlas. The text is "
    "redacted: placeholders like <PERSON> replace personal data; never try to recover them. "
    "Return diseases, genes (symbols), variants (HGVS where given), symptoms, age in years "
    "(or an age range when only that is clear), onset and country (ISO alpha-2), and set "
    "about_child=true when the text is about the user's child or another minor they care for "
    "('my son', 'our daughter'). Keep each mention as written in `text` and give the "
    "English medical term in `english` (HPO-style for symptoms). Set negated=true for things "
    "the user says are absent ('no problems with eating' = feeding difficulties, negated). "
    "Only extract what the text states; never guess."
)


async def extract(state: TurnState, llm: LLMClient, text: str | None = None) -> Extraction:
    """extract_entities: candidate chips, negation, age, onset and country from the redacted
    message, on the small model at a low reasoning effort when the model offers one."""
    source = text.strip() if text and text.strip() else state.message
    extraction = await llm.structured(
        Extraction, instructions=EXTRACT_INSTRUCTIONS, input=source, kind="small", effort="low"
    )
    state.extraction = extraction
    return extraction


def extraction_mentions(ex: Extraction) -> list[MentionIn]:
    mentions: list[MentionIn] = []
    for chip_type, items in (
        (ChipType.disease, ex.diseases),
        (ChipType.gene, ex.genes),
        (ChipType.variant, ex.variants),
        (ChipType.symptom, ex.symptoms),
    ):
        mentions += [
            MentionIn(text=m.english or m.text, type=chip_type, negated=m.negated) for m in items
        ]
    return mentions


async def resolve(state: TurnState, mentions: list[MentionIn]) -> dict:
    """resolve_to_ids: mentions to stable IDs; every result becomes an unconfirmed chip."""
    confirmed = state.profile_ids()
    resolved, unresolved = [], []
    async with user_transaction(None) as db:
        for m in mentions[:20]:
            resp = await search_service.search(db, m.text, types=[CHIP_NODE_TYPES[m.type]], limit=3)
            if not resp.results:
                unresolved.append({"text": m.text, "type": m.type.value})
                state.add_chip(
                    Chip(
                        type=m.type,
                        id=None,
                        label=m.text[:80],
                        negated=m.negated,
                        confirmed=False,
                    )
                )
                continue
            top = resp.results[0]
            for r in resp.results:
                state.node_ids.add(r.id)
            state.add_chip(
                Chip(
                    type=m.type,
                    id=top.id,
                    label=top.label,
                    negated=m.negated,
                    confirmed=top.id in confirmed,
                )
            )
            resolved.append(
                {
                    "mention": m.text,
                    "type": m.type.value,
                    "id": top.id,
                    "label": top.label,
                    "matched_synonym": top.matched_synonym,
                    "score": round(top.score, 3),
                    "negated": m.negated,
                    "cluster_id": top.cluster_id,
                    "alternatives": [
                        {"id": r.id, "label": r.label, "score": round(r.score, 3)}
                        for r in resp.results[1:]
                    ],
                }
            )
    return {"resolved": resolved, "unresolved": unresolved, "chips_are_unconfirmed": True}


def build_tools(state: TurnState, llm: LLMClient) -> list[Tool]:
    """The tools offered to the model (extract_entities runs before the loop, see `extract`)."""
    lens = state.lens

    async def resolve_to_ids(params: ResolveIn) -> dict:
        mentions = list(params.mentions)
        if not mentions and state.extraction is not None:
            mentions = extraction_mentions(state.extraction)
        return await resolve(state, mentions)

    async def search_graph(params: SearchIn) -> dict:
        expert = lens.expert_mode if params.expert is None else (params.expert or lens.expert_mode)
        limit = max(1, min(params.limit or 8, 20))
        async with user_transaction(None) as db:
            resp = await search_service.search(
                db, params.query, types=params.node_types or None, limit=limit, expert=expert
            )
        results = []
        for r in resp.results:
            state.node_ids.add(r.id)
            results.append(
                {
                    "id": r.id,
                    "type": r.type.value,
                    "label": r.label,
                    "matched_synonym": r.matched_synonym,
                    "score": round(r.score, 3),
                    "cluster_id": r.cluster_id,
                }
            )
        clusters = []
        for rc in resp.ranked_clusters:
            state.node_ids.add(rc.cluster.id)
            state.node_ids.update(rc.matched_node_ids)
            state.edge_ids.update(rc.edge_ids)
            clusters.append(
                {
                    "cluster_id": rc.cluster.id,
                    "label": rc.cluster.label,
                    "mechanism": rc.cluster.mechanism_summary,
                    "score": round(rc.score, 3),
                    "member_count": rc.member_count,
                    "trial_count": rc.trial_count,
                    "evidence_level": rc.evidence_level.value,
                    "edge_ids": rc.edge_ids[:10],
                }
            )
        return {"results": results, "ranked_clusters": clusters}

    async def get_neighborhood(params: NeighborhoodIn) -> dict:
        try:
            nb = graph_service.neighborhood(params.node_id, lens)
        except ApiError as exc:
            return {"error": exc.message, "code": exc.code.value}
        center = nb.center
        edges = sorted(
            nb.edges,
            key=lambda e: (
                _RELATION_PRIORITY.get(e.relation, 4),
                0 if center.id in (e.source_id, e.target_id) else 1,
                -e.confidence,
                e.id,
            ),
        )
        shown = edges[:MAX_NEIGHBORHOOD_EDGES]
        shown_nodes = {center.id} | {n for e in shown for n in (e.source_id, e.target_id)}
        for e in shown:
            state.see_edge(e)
        nodes = [n for n in nb.nodes if n.id in shown_nodes]
        for n in nodes:
            state.see_node(n)
        cluster = None
        if nb.cluster is not None:
            state.node_ids.add(nb.cluster.id)
            cluster = {
                "id": nb.cluster.id,
                "label": nb.cluster.label,
                "mechanism": nb.cluster.mechanism_summary,
                "label_origin": "inferred",
            }
        return {
            "center": _node_view(center),
            "cluster": cluster,
            "nodes": [_node_view(n) for n in nodes],
            "edges": [_edge_view(e) for e in shown],
            "omitted_edges": max(0, len(edges) - len(shown)),
        }

    async def find_path(params: PathIn) -> dict:
        try:
            resp = path_service.find_paths(
                params.from_id,
                params.to_id,
                family=params.family or PathFamily.all,
                k=3,
                include_vus=bool(params.include_vus),
            )
        except ApiError as exc:
            return {"error": exc.message, "code": exc.code.value}
        state.paths.append(resp)
        if params.include_vus and _paths_touch_vus(resp):
            state.vus_in_paths = True
        out: dict[str, Any] = {
            "status": resp.status.value,
            "threshold": resp.threshold,
            "paths": [_path_view(state, p) for p in resp.paths],
        }
        if resp.status == PathStatus.no_supported_route and resp.coverage is not None:
            cov = resp.coverage
            out["coverage"] = {
                "sources_queried": [s.model_dump() for s in cov.sources_queried],
                "closest_partial_path": _path_view(state, cov.closest_partial_path)
                if cov.closest_partial_path
                else None,
                "missing_link": cov.missing_link.model_dump() if cov.missing_link else None,
                "suggested_question": cov.suggested_question,
                "gap_search_available": True,
            }
        return out

    async def ask_followup(params: FollowupIn) -> dict:
        if state.follow_up is not None:
            return {"error": "A follow-up question was already chosen this turn; ask only one."}
        follow_up, info = choose_followup(params.candidate_cluster_ids, state)
        if follow_up is None:
            return {"question": None, "reason": info}
        state.follow_up = follow_up
        return {**follow_up.model_dump(mode="json"), "separates": info}

    return [
        Tool(
            "resolve_to_ids",
            "Resolve further mentions to stable IDs with scores: diseases to MONDO, genes to "
            "HGNC, variants to ClinVar, symptoms to HPO. Results are unconfirmed chips. The "
            "user's message is already resolved before the first round.",
            ResolveIn,
            resolve_to_ids,
        ),
        Tool(
            "search_graph",
            "Search the atlas for typed nodes with the matched synonym; in expert mode a "
            "mechanism query also returns ranked clusters with supporting edge ids.",
            SearchIn,
            search_graph,
        ),
        Tool(
            "get_neighborhood",
            "Neighbourhood of a node: cluster, connected nodes and edges with relation, "
            "confidence, origin (observed/inferred), status and contradicting evidence counts.",
            NeighborhoodIn,
            get_neighborhood,
        ),
        Tool(
            "find_path",
            "Top paths between two nodes by trust (edge cost -log confidence), or "
            "no_supported_route with a coverage report naming the missing evidence. Variants of "
            "uncertain significance (VUS) are excluded from routes; set include_vus=true only "
            "when the user explicitly asks to include uncertain variants.",
            PathIn,
            find_path,
        ),
        Tool(
            "ask_followup",
            "Choose at most one skippable follow-up question with quick replies that best "
            "separates the remaining candidate clusters. Call only when several clusters remain.",
            FollowupIn,
            ask_followup,
        ),
    ]


def choose_followup(cluster_ids: list[str], state: TurnState) -> tuple[FollowUp | None, Any]:
    """Pick the phenotype whose presence splits the candidate clusters most evenly."""
    store = graph_service.get_graph()
    candidates = [c for c in dict.fromkeys(cluster_ids) if c in store.clusters]
    if len(candidates) < 2:
        return None, "fewer than two known candidate clusters"
    known = state.profile_ids() | {c.id for c in state.chips.values() if c.id}
    by_cluster: dict[str, set[str]] = {}
    for cid in candidates:
        phenos: set[str] = set()
        for member in store.members.get(cid, ()):
            for eid in store.incident.get(member, ()):
                edge = store.edges[eid]
                if edge.relation == Relation.has_phenotype and edge.source_id == member:
                    phenos.add(edge.target_id)
        by_cluster[cid] = phenos
    counts = Counter(p for ps in by_cluster.values() for p in ps)
    best: tuple[int, int, str] | None = None
    for pheno, n_with in counts.items():
        if pheno in known:
            continue
        split = min(n_with, len(candidates) - n_with)
        if split == 0:
            continue
        key = (split, -abs(n_with * 2 - len(candidates)), pheno)
        if best is None or key[:2] > best[:2] or (key[:2] == best[:2] and pheno < best[2]):
            best = key
    if best is None:
        return None, "no symptom separates these clusters"
    pheno_id = best[2]
    node = store.nodes.get(pheno_id)
    label = (node.label if node else pheno_id).lower()
    lang = base_language(state.reply_language)
    follow_up = FollowUp(
        question=pick(FOLLOWUP_TEXT["question"], lang).format(label=label),
        quick_replies=pick(FOLLOWUP_TEXT["replies"], lang).split("|"),
        skippable=True,
    )
    with_p = sorted(c for c, ps in by_cluster.items() if pheno_id in ps)
    return follow_up, {
        "phenotype_id": pheno_id,
        "clusters_with": with_p,
        "clusters_without": sorted(set(candidates) - set(with_p)),
    }
