"""Post-checks enforced in code on every agent turn, before anything is streamed.

Citations, origin and confidence, contradictions, viability, VUS, uncertainty, no supported
route, medical boundary and the patient-lens reading gate."""

import asyncio
import re
import time
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from backend.api.services import atlas_tree
from backend.api.services import graph as graph_service
from backend.api.services import search as search_service
from backend.api.services.chat import safety
from backend.api.services.chat.tools import TurnState
from backend.api.services.explanation.common import (
    AI_NOTICES,
    VUS_NOTICES,
    passes_grade,
    pick,
    reading_grade,
    split_sentences,
)
from backend.api.services.explanation.pathdata import EvidenceItem, load_evidence
from backend.db.session import user_transaction
from backend.llm import LLMClient, LLMError
from backend.schemas.chat import (
    Action,
    AgentReply,
    Card,
    Claim,
    Contradiction,
    FollowUp,
    GraphFocus,
    ProfileHints,
    SymptomMatch,
    SymptomMatchItem,
    SymptomMatchTerm,
)
from backend.schemas.enums import (
    CONFIDENCE_THRESHOLD,
    AgeRange,
    CardType,
    ChipType,
    EdgeStatus,
    Origin,
    PathStatus,
    Relation,
    Role,
    confidence_level,
)
from backend.schemas.gap import GapSearchRequest
from backend.schemas.graph import Edge

MAX_SUMMARY_SENTENCES = 3
CHILD_AGE_LIMIT = 16  # accounts are 16+; younger means a parent describes a child
# Ranges that may include an under-16 (13-17 straddles the limit: flag it, the user decides).
CHILD_AGE_RANGES = {AgeRange.under_1, AgeRange.age_1_5, AgeRange.age_6_12, AgeRange.age_13_17}
_ONSET_HINT = re.compile(r"^(?:HP:\d{7}|[A-Za-z][A-Za-z ,'-]{0,59})$")
_COUNTRY_HINT = re.compile(r"^[A-Z]{2}$")
MAX_RANKED = 5  # conditions on the reply's symptom-overlap card
MAX_SIMPLIFY_ATTEMPTS = 2
MIN_REWRITE_S = 2.0  # no rewrite starts with less of the turn's deadline left

TEXT = {
    "uncertainty": {
        "en": "The evidence for these links is weak, so treat them as unconfirmed.",
        "de": "Die Belege für diese Verbindungen sind schwach; bitte als unbestätigt betrachten.",
    },
    "no_route": {
        "en": "I found no supported route between {a} and {b}.",
        "de": "Ich habe keine gut belegte Verbindung zwischen {a} und {b} gefunden.",
    },
    "gap_search": {
        "en": "A gap search can look for this missing evidence.",
        "de": "Eine Lückensuche kann nach diesen fehlenden Belegen suchen.",
    },
    "geneticist": {
        "en": "These are groups to talk over with a genetics doctor. This is not a diagnosis.",
        "de": "Das sind Gruppen zum Besprechen in einer humangenetischen Sprechstunde. Das ist "
        "keine Diagnose.",
    },
    "under_review": {"en": " (under review)", "de": " (in Überprüfung)"},
    "contradiction": {
        "en": "Contradicting evidence: {src}",
        "de": "Widersprechende Belege: {src}",
    },
}

SIMPLIFY = (
    "Rewrite the text below in plain words for a patient or family member, at reading grade 8 "
    "or lower: short sentences, everyday words, at most 3 sentences. Keep exactly the same "
    "facts; add nothing. Keep the language of the text. Reply with the rewritten text only."
)


class AgentDraft(BaseModel):
    """What the model returns; the server turns it into the checked AgentReply."""

    summary: str = Field(description="Plain-language answer, max 3 sentences, no citations.")
    uncertainty: str | None = Field(description="Null or one sentence.")
    claims: list[Claim]
    contradictions: list[Contradiction]
    missing_evidence: list[str]
    cards: list[Card]
    graph_focus: GraphFocus | None
    actions: list[Action]
    follow_up: FollowUp | None


@dataclass
class CheckReport:
    removed_claims: int = 0
    removed_actions: int = 0
    removed_cards: int = 0
    corrected_origin: int = 0
    corrected_confidence: int = 0
    added_contradictions: int = 0
    non_viable_actions: int = 0
    dropped_follow_up: bool = False
    declined: list[str] = field(default_factory=list)
    removed_sentences: int = 0
    simplify_attempts: int = 0
    summary_grade: float | None = None
    no_supported_route: bool = False
    vus_notice: bool = False

    def as_metadata(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (0, False, None, [])}


def _origin(edges: list[Edge]) -> Origin:
    origins = {e.origin for e in edges}
    for o in (Origin.inferred, Origin.user_contributed, Origin.patient_reported):
        if o in origins:
            return o
    return Origin.observed


def _contradicted(edge: Edge, evidence: dict[str, list[EvidenceItem]]) -> bool:
    return bool(edge.contradiction_count) or any(ev.contradicts for ev in evidence.get(edge.id, []))


def _viable(edges: list[Edge], evidence: dict[str, list[EvidenceItem]]) -> bool:
    return bool(edges) and all(
        e.origin == Origin.observed
        and e.status == EdgeStatus.active
        and not _contradicted(e, evidence)
        for e in edges
    )


def _sentences(text: str) -> list[str]:
    return split_sentences(" ".join(text.split()))


async def _resolve_edges(state: TurnState, ids: set[str]) -> dict[str, Edge]:
    """Edge data for every seen ID (tool outputs first, then the in-memory graph)."""
    out = {i: state.edges[i] for i in ids if i in state.edges}
    for i in ids - set(out):
        edge = graph_service.get_edge(i)
        if edge is not None:
            out[i] = edge
    return out


def _paths_all_below_threshold(state: TurnState) -> bool:
    if not state.paths:
        return False
    for resp in state.paths:
        if resp.status == PathStatus.ok and any(
            p.min_confidence >= CONFIDENCE_THRESHOLD for p in resp.paths
        ):
            return False
    return True


async def check_reply(
    draft: AgentDraft,
    state: TurnState,
    llm: LLMClient | None,
    *,
    asked: set[safety.Category],
    deadline: float | None = None,
) -> tuple[AgentReply, CheckReport]:
    """`deadline` (monotonic seconds) bounds the reading gate's model calls: past it the
    summary keeps its best version so far."""
    report = CheckReport()
    lang = state.reply_language
    seen_edges = state.edge_ids
    edges = await _resolve_edges(state, seen_edges)
    seen_nodes = state.node_ids | state.profile_ids()

    # 1. citations: every claim cites at least one edge, all returned by tools this turn
    claims: list[Claim] = []
    index_map: dict[int, int] = {}
    for i, claim in enumerate(draft.claims):
        ids = list(dict.fromkeys(claim.edge_ids))
        if not ids or any(e not in edges for e in ids):
            report.removed_claims += 1
            continue
        index_map[i] = len(claims)
        claims.append(claim.model_copy(update={"edge_ids": ids}))

    cited = {e for c in claims for e in c.edge_ids}
    action_edges = {e for a in draft.actions for e in a.edge_ids if e in edges}
    async with user_transaction(None) as db:
        evidence = await load_evidence(db, cited | action_edges)

    # 2. origin and confidence from the cited edges; non-active edges flagged in the text
    for idx, claim in enumerate(claims):
        cedges = [edges[e] for e in claim.edge_ids]
        origin = _origin(cedges)
        level = confidence_level(min(e.confidence for e in cedges))
        text = claim.text
        under_review = pick(TEXT["under_review"], lang)
        if any(e.status != EdgeStatus.active for e in cedges) and under_review not in text:
            text = text.rstrip() + under_review
        report.corrected_origin += origin != claim.origin
        report.corrected_confidence += level != claim.confidence
        claims[idx] = claim.model_copy(update={"origin": origin, "confidence": level, "text": text})

    # 3. contradictions: keep valid model entries, add every contradicted cited edge
    contradictions: list[Contradiction] = []
    have: set[tuple[int, str]] = set()
    for c in draft.contradictions:
        if c.claim_index not in index_map:
            continue
        ci = index_map[c.claim_index]
        ids = [e for e in c.edge_ids if e in claims[ci].edge_ids]
        if ids:
            contradictions.append(c.model_copy(update={"claim_index": ci, "edge_ids": ids}))
            have.update((ci, e) for e in ids)
    for ci, claim in enumerate(claims):
        for eid in claim.edge_ids:
            if (ci, eid) in have or not _contradicted(edges[eid], evidence):
                continue
            items = [ev for ev in evidence.get(eid, []) if ev.contradicts]
            src = (
                "; ".join(
                    ev.label() + (f": “{ev.quote[:160]}”" if ev.quote else "") for ev in items[:2]
                )
                or f"{edges[eid].contradiction_count} item(s) on edge {eid}"
            )
            contradictions.append(
                Contradiction(
                    claim_index=ci,
                    edge_ids=[eid],
                    note=pick(TEXT["contradiction"], lang).format(src=src),
                )
            )
            have.add((ci, eid))
            report.added_contradictions += 1

    # 4. actions: viable only if every edge is observed, active and uncontradicted
    actions: list[Action] = []
    for a in draft.actions:
        valid = [e for e in dict.fromkeys(a.edge_ids) if e in edges]
        if not valid:
            report.removed_actions += 1
            continue
        viable = len(valid) == len(set(a.edge_ids)) and _viable([edges[e] for e in valid], evidence)
        if a.viable and not viable:
            report.non_viable_actions += 1
        actions.append(a.model_copy(update={"edge_ids": valid, "viable": viable}))
    actions.sort(key=lambda a: not a.viable)

    # 5. cards and graph focus: only IDs returned by tools
    cards: list[Card] = []
    for card in draft.cards:
        nodes = [n for n in card.node_ids if n in seen_nodes]
        cedges = [e for e in card.edge_ids if e in edges]
        if not nodes and not cedges:
            report.removed_cards += 1
            continue
        cards.append(card.model_copy(update={"node_ids": nodes, "edge_ids": cedges}))
    focus = None
    if draft.graph_focus is not None:
        focus = GraphFocus(
            node_ids=[n for n in draft.graph_focus.node_ids if n in seen_nodes],
            highlight_path=[e for e in draft.graph_focus.highlight_path if e in edges],
        )
    best_path = next(
        (p for r in state.paths if r.status == PathStatus.ok for p in r.paths if p.supported), None
    )
    if focus is None or not (focus.node_ids or focus.highlight_path):
        if best_path is not None:
            nodes = list(
                dict.fromkeys(n for s in best_path.steps for n in (s.from_node.id, s.to_node.id))
            )
            focus = GraphFocus(node_ids=nodes, highlight_path=best_path.edge_ids)
        else:
            chip_nodes = [c.id for c in state.chips.values() if c.id and not c.negated]
            focus = GraphFocus(node_ids=chip_nodes, highlight_path=[]) if chip_nodes else None
    elif best_path is not None and not focus.highlight_path:
        # A connection question: the Atlas draws the best supported route the tools found, also
        # when the model named only the nodes.
        path_nodes = [n for s in best_path.steps for n in (s.from_node.id, s.to_node.id)]
        focus = GraphFocus(
            node_ids=list(dict.fromkeys([*focus.node_ids, *path_nodes])),
            highlight_path=best_path.edge_ids,
        )

    # 6. follow-up: only the one ask_followup chose (the model may translate its wording)
    follow_up = None
    if state.follow_up is not None:
        follow_up = state.follow_up
        if draft.follow_up is not None and draft.follow_up.question.strip():
            replies = [r for r in draft.follow_up.quick_replies if r.strip()][:4]
            follow_up = FollowUp(
                question=draft.follow_up.question.strip(),
                quick_replies=replies or state.follow_up.quick_replies,
                skippable=True,
            )
    elif draft.follow_up is not None:
        report.dropped_follow_up = True

    # 7. medical boundary on the summary, claims and actions
    prognosis_asked = safety.Category.prognosis in asked
    filtered = safety.filter_sentences(draft.summary, prognosis_asked=prognosis_asked)
    removed = set(filtered.removed)
    report.removed_sentences += len(filtered.removed)
    kept_claims: list[Claim] = []
    claim_map: dict[int, int] = {}
    for i, claim in enumerate(claims):
        cats = safety.stated_categories(claim.text, prognosis_asked=prognosis_asked)
        if cats:
            removed |= cats
            report.removed_claims += 1
            continue
        claim_map[i] = len(kept_claims)
        kept_claims.append(claim)
    contradictions = [
        c.model_copy(update={"claim_index": claim_map[c.claim_index]})
        for c in contradictions
        if c.claim_index in claim_map
    ]
    claims = kept_claims
    safe_actions = []
    for a in actions:
        cats = safety.stated_categories(
            " ".join([a.title, *a.assumptions]), prognosis_asked=prognosis_asked
        )
        if cats:
            removed |= cats
            report.removed_actions += 1
        else:
            safe_actions.append(a)
    actions = safe_actions
    declined = (asked - {safety.Category.prognosis}) | removed
    report.declined = sorted(c.value for c in declined)

    if declined and not (claims or cards or (focus and (focus.node_ids or focus.highlight_path))):
        chip_nodes = [c.id for c in state.chips.values() if c.id]
        fallback = chip_nodes or await _search_context(state)
        if fallback:
            focus = GraphFocus(node_ids=fallback, highlight_path=[])
            cards.append(Card(type=CardType.open_in_atlas, node_ids=fallback[:1], edge_ids=[]))

    # 8. summary: reading gate on the model's text (patients and guests), then fixed sentences
    core = _sentences(filtered.text)[:MAX_SUMMARY_SENTENCES]
    core_text = " ".join(core)
    if llm is not None and core_text and state.lens.role in (Role.patient, Role.guest):
        core_text, report = await _reading_gate(
            core_text, state, llm, report, prognosis_asked, deadline
        )
    no_route = state.paths and all(r.status == PathStatus.no_supported_route for r in state.paths)
    prefix: list[str] = []
    decline = safety.decline_sentence(declined, lang)
    if decline:
        prefix.append(decline)
    gap_search = None
    missing = [m.strip()[:300] for m in draft.missing_evidence if m.strip()][:5]
    if no_route:
        report.no_supported_route = True
        resp = state.paths[0]
        gap_search = GapSearchRequest(from_id=resp.from_id, to_id=resp.to_id, family=resp.family)
        label = {
            n: (state.nodes[n].label if n in state.nodes else _label(n))
            for n in (resp.from_id, resp.to_id)
        }
        sentence = pick(TEXT["no_route"], lang).format(a=label[resp.from_id], b=label[resp.to_id])
        if not decline:
            prefix.append(sentence)
        for r in state.paths:
            if r.coverage and r.coverage.missing_link:
                desc = r.coverage.missing_link.description
                if desc not in missing:
                    missing.insert(0, desc)
        missing.append(pick(TEXT["gap_search"], lang))
    core_sentences = _sentences(core_text)[: max(1, MAX_SUMMARY_SENTENCES - len(prefix))]
    summary_parts = [*prefix, *core_sentences]
    if _symptoms_only(state):
        summary_parts.append(pick(TEXT["geneticist"], lang))
    if _touches_vus(state, claims, focus, cards):
        vus = pick(VUS_NOTICES, lang)
        report.vus_notice = True
        if vus not in " ".join(summary_parts):
            summary_parts.append(vus)
    summary = " ".join(p for p in summary_parts if p).strip()
    if not summary:
        summary = pick(TEXT["uncertainty"], lang)

    uncertainty = (
        draft.uncertainty.strip() if draft.uncertainty and draft.uncertainty.strip() else None
    )
    if uncertainty:
        uncertainty = _sentences(uncertainty)[0] if _sentences(uncertainty) else None
    below = _paths_all_below_threshold(state) or (
        not state.paths
        and claims
        and all(min(edges[e].confidence for e in c.edge_ids) < CONFIDENCE_THRESHOLD for c in claims)
    )
    if below:
        uncertainty = pick(TEXT["uncertainty"], lang)
    if uncertainty and safety.stated_categories(uncertainty, prognosis_asked=prognosis_asked):
        uncertainty = None
    report.summary_grade = reading_grade(summary, lang)

    chips = list(state.chips.values())
    reply = AgentReply(
        summary=summary,
        uncertainty=uncertainty,
        chips=chips,
        claims=claims,
        contradictions=contradictions,
        missing_evidence=missing,
        cards=cards,
        graph_focus=focus,
        actions=actions,
        follow_up=follow_up,
        gap_search=gap_search,
        ai_notice=pick(AI_NOTICES, lang),
        kind="declined" if decline else "answer",
        profile_hints=profile_hints(state),
        symptom_match=symptom_match(state, edges),
    )
    return reply, report


def symptom_match(state: TurnState, edges: dict[str, Edge]) -> SymptomMatch | None:
    """The reply's symptom-overlap ranking, built in code from this turn's match_phenotypes
    result (no model text): the top conditions with their overlap count, and every shared or
    contradicting symptom backed by a has_phenotype edge of that condition that the tool
    returned. A condition left without a citable shared symptom is dropped."""
    if not state.symptom_match:
        return None

    def terms(disease_id: str, views: list[dict]) -> list[SymptomMatchTerm]:
        out = []
        for v in views:
            edge = edges.get(v.get("edge_id", ""))
            if (
                edge is None
                or edge.relation != Relation.has_phenotype
                or edge.source_id != disease_id
            ):
                continue
            out.append(
                SymptomMatchTerm(
                    user_symptom=v["user_symptom"],
                    recorded_as=v["recorded_as"],
                    match=v["match"],
                    edge_id=edge.id,
                )
            )
        return out

    items: list[SymptomMatchItem] = []
    for r in state.symptom_match:
        shared = terms(r["id"], r.get("shared", []))
        if not shared:
            continue
        node = state.nodes.get(r["id"]) or graph_service.get_node(r["id"])
        items.append(
            SymptomMatchItem(
                id=r["id"],
                label=r["label"],
                overlap=r["overlap"],
                of=r["of"],
                on_map=node is not None and atlas_tree.is_focus(node),
                shared=shared,
                absent=terms(r["id"], r.get("recorded_but_absent_for_user", [])),
            )
        )
        if len(items) == MAX_RANKED:
            break
    return SymptomMatch(items=items) if items else None


def profile_hints(state: TurnState) -> ProfileHints | None:
    """Age, onset and country from this turn's extraction, unconfirmed like chips (only values
    the PatientProfile would accept), plus whether the message seems to be about a child."""
    ex = state.extraction
    if ex is None:
        return None
    age = ex.age_years if ex.age_years is not None and 0 <= ex.age_years <= 120 else None
    onset = (ex.onset or "").strip() or None
    if onset is not None and not _ONSET_HINT.match(onset):
        onset = None
    country = (ex.country or "").strip().upper() or None
    if country is not None and not _COUNTRY_HINT.match(country):
        country = None
    child = (
        ex.about_child
        or (age is not None and age < CHILD_AGE_LIMIT)
        or (age is None and ex.age_range in CHILD_AGE_RANGES)
    )
    hints = ProfileHints(
        age_years=age,
        age_range=ex.age_range if age is None else None,
        onset=onset,
        country=country,
        about_child_suspected=child,
    )
    if hints == ProfileHints():
        return None
    return hints


async def _search_context(state: TurnState) -> list[str]:
    """Graph context for a decline when the tools found none: search the redacted message."""
    try:
        async with user_transaction(None) as db:
            resp = await search_service.search(db, state.message, limit=3)
    except Exception:  # noqa: BLE001 - the decline still stands without context
        return []
    ids = [r.id for r in resp.results]
    state.node_ids.update(ids)
    return ids


def _label(node_id: str) -> str:
    node = graph_service.get_node(node_id)
    return node.label if node else node_id


def _symptoms_only(state: TurnState) -> bool:
    chips = [c for c in state.chips.values() if c.id]
    if not chips or state.profile.diseases or state.profile.genes or state.profile.variants:
        return False
    return all(c.type == ChipType.symptom for c in chips)


def _touches_vus(state: TurnState, claims: list[Claim], focus, cards: list[Card]) -> bool:
    if state.vus_in_paths:  # the user asked to route through uncertain variants
        return True
    ids: set[str] = set()
    for c in claims:
        for eid in c.edge_ids:
            edge = state.edges.get(eid) or graph_service.get_edge(eid)
            if edge is not None:
                ids.update((edge.source_id, edge.target_id))
    if focus is not None:
        ids.update(focus.node_ids)
    for card in cards:
        ids.update(card.node_ids)
    ids.update(c.id for c in state.chips.values() if c.id and c.type == ChipType.variant)
    for nid in ids:
        node = state.nodes.get(nid) or graph_service.get_node(nid)
        if node is not None and graph_service.is_vus(node):
            return True
    for v in state.profile.variants:
        if v.classification == "uncertain_significance" and (
            (v.clinvar_id and v.clinvar_id in ids) or (v.gene_id and v.gene_id in ids)
        ):
            return True
    return False


async def _reading_gate(
    text: str,
    state: TurnState,
    llm: LLMClient,
    report: CheckReport,
    prognosis_asked: bool,
    deadline: float | None = None,
) -> tuple[str, CheckReport]:
    grade = reading_grade(text, state.reply_language)
    best, best_grade = text, grade
    attempts = 0
    while (
        not passes_grade(best_grade, state.lens.role, state.reply_language)
        and attempts < MAX_SIMPLIFY_ATTEMPTS
    ):
        left = None if deadline is None else deadline - time.monotonic()
        if left is not None and left <= MIN_REWRITE_S:
            break
        attempts += 1
        try:
            async with asyncio.timeout(left):
                rewritten = await llm.complete_text(
                    instructions=SIMPLIFY, input=best, kind="small", effort="low"
                )
        except (LLMError, TimeoutError):
            break
        rewritten = safety.filter_sentences(rewritten, prognosis_asked=prognosis_asked).text
        rewritten = " ".join(_sentences(rewritten)[:MAX_SUMMARY_SENTENCES])
        if not rewritten:
            continue
        g = reading_grade(rewritten, state.reply_language)
        if g is None or best_grade is None or g < best_grade:
            best, best_grade = rewritten, g
    report.simplify_attempts = attempts
    return best, report
