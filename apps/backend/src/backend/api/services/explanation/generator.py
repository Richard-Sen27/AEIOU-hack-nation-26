"""LLM explanation of one path: role prompt, citation validation, trust rules, reading gate."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field

from backend.api.services.explanation.common import (
    VUS_NOTICES,
    cited_edges,
    grade_target,
    language_name,
    passes_grade,
    pick,
    reading_grade,
)
from backend.api.services.explanation.pathdata import (
    PathData,
    compact_features,
    has_contradiction,
)
from backend.api.services.explanation.templates import enforce_trust_rules
from backend.llm import LLMClient
from backend.schemas.enums import Role, confidence_level
from backend.schemas.events import ExplainStep
from backend.schemas.graph import Edge

MAX_ATTEMPTS = 3

ROLE_STYLE: dict[Role, str] = {
    Role.guest: "The reader is exploring the atlas for the first time and has no medical "
    "background. Use short sentences and everyday words (reading grade 8 or lower). "
    "3 to 5 sentences.",
    Role.patient: "The reader is a patient or a family member. Use short sentences and everyday "
    "words (reading grade 8 or lower); explain any medical term in a few plain words. "
    "3 to 5 sentences.",
    Role.doctor: "The reader is a clinician. Use precise clinical terms and mention the "
    "evidence tier and confidence level of each link. 3 to 6 sentences.",
    Role.researcher: "The reader is a researcher. Be technical: name genes, mechanisms and node "
    "IDs, and give each link's confidence and evidence tier. 3 to 6 sentences.",
}


class ExplanationError(Exception):
    """The model could not produce a valid, cited explanation within the retry budget."""


@dataclass
class Explanation:
    text: str
    citations: list[str]
    reading_grade: float | None
    attempts: int = 1
    generated_by: str = "model"
    added_notes: list[str] = field(default_factory=list)


PATH_TASK = (
    "Explain the path in the input: how its first node connects to its last node, link by link."
)
SUBJECT_TASK = (
    "Summarise how the subject node in the input is connected in the atlas, using only the "
    "listed links. The links are a set of its connections, not a path: group them by kind "
    "(people, papers, studies, genes, symptoms, organisations ...) and start with the "
    "strongest links (highest confidence). Do not list every link one by one."
)


def instructions(role: Role, language: str, *, subject: bool = False) -> str:
    source = "the listed links" if subject else "the path data"
    return (
        "You are Dr. Wu, the AI guide of the Amber rare-disease atlas. "
        f"{SUBJECT_TASK if subject else PATH_TASK}\n"
        f"{ROLE_STYLE.get(role, ROLE_STYLE[Role.patient])}\n"
        "Rules:\n"
        f"- Use only the facts in {source}. Never add facts from memory.\n"
        "- End every sentence with the edge ids it relies on in square brackets, e.g. "
        f"[e_0123456789ab]. Cite only edge ids listed in {source}.\n"
        '- Edges with origin "inferred" are hypotheses computed from data: word them as '
        'possibilities ("may", "possibly"), never as facts.\n'
        "- If an edge has contradicting evidence, say so in the sentence about that edge.\n"
        '- If an edge\'s status is not "active", say that this link is under review.\n'
        "- If the input contains a variant of uncertain significance, add this sentence "
        f'unchanged: "{pick(VUS_NOTICES, language)}"\n'
        "- Never diagnose, recommend treatment or doses, give a prognosis or reclassify a "
        "variant.\n"
        f"- Write in {language_name(language)}. Plain text only: no markdown, no headings, "
        "no lists."
    )


def _edges_for_prompt(data: PathData) -> list[Edge]:
    """Path edges in traversal order; a subject's connections strongest first."""
    edges = data.ordered_edges()
    if data.subject_id:
        edges.sort(key=lambda e: -e.confidence)
    return edges


def path_payload(data: PathData) -> dict:
    steps = []
    for edge in _edges_for_prompt(data):
        support = data.supporting(edge.id)[:3]
        steps.append(
            {
                "edge_id": edge.id,
                "from": {"id": edge.source_id, "label": data.node_label(edge.source_id)},
                "relation": edge.relation.value,
                "to": {"id": edge.target_id, "label": data.node_label(edge.target_id)},
                "confidence": round(edge.confidence, 2),
                "confidence_level": confidence_level(edge.confidence).value,
                "origin": edge.origin.value,
                "status": edge.status.value,
                "features": compact_features(edge.features),
                "evidence": [
                    {
                        "tier": ev.tier,
                        "source": ev.label(),
                        "quote": (ev.quote or "")[:240] or None,
                    }
                    for ev in support
                ],
                "contradicting_evidence": [
                    {"source": ev.label(), "quote": (ev.quote or "")[:240] or None}
                    for ev in data.contradicting(edge.id)[:3]
                ]
                if has_contradiction(edge, data)
                else [],
            }
        )
    vus = [{"id": n.id, "label": n.label} for n in data.vus_nodes()]
    subject = data.subject
    if subject is not None:
        return {
            "subject": {"id": subject.id, "label": subject.label, "type": subject.type.value},
            "link_edge_ids": [step["edge_id"] for step in steps],
            "links": steps,
            "variants_of_uncertain_significance": vus,
        }
    return {
        "path_edge_ids": data.edge_ids,
        "steps": steps,
        "variants_of_uncertain_significance": vus,
    }


def _clean(text: str) -> str:
    lines = [line.strip().lstrip("#*-• ").strip() for line in text.strip().splitlines()]
    return " ".join(line for line in lines if line).replace("**", "")


def _citation_problem(text: str, allowed: set[str], *, subject: bool = False) -> str | None:
    cited = cited_edges(text)
    invalid = [c for c in cited if c not in allowed]
    if invalid:
        scope = "among the listed links" if subject else "part of this path"
        return (
            f"You cited edge ids that are not {scope}: "
            + ", ".join(invalid)
            + ". Cite only these edge ids: "
            + ", ".join(sorted(allowed))
            + "."
        )
    if not cited:
        return "You did not cite any edge ids. End every sentence with its edge ids in brackets."
    return None


async def generate_explanation(
    llm: LLMClient,
    data: PathData,
    role: Role,
    language: str,
    *,
    max_attempts: int = MAX_ATTEMPTS,
    on_step: Callable[[ExplainStep], None] | None = None,
) -> Explanation:
    """Generate, validate and (if needed) regenerate. Raises ExplanationError when no attempt
    cites only path edges; accepts the simplest valid attempt when the reading gate fails.
    `on_step` hears each step (writing, checking, fixing_sources, simplifying) as it starts."""
    step = on_step or (lambda _: None)
    allowed = set(data.edge_ids)
    payload = json.dumps(path_payload(data), ensure_ascii=False)
    items: list[dict] = [{"role": "user", "content": payload}]
    best: Explanation | None = None
    next_step: ExplainStep = "writing"
    for attempt in range(1, max_attempts + 1):
        subject = data.subject_id is not None
        step(next_step)
        raw = await llm.complete_text(
            instructions=instructions(role, language, subject=subject), input=items, kind="main"
        )
        step("checking")
        text = _clean(raw)
        problem = _citation_problem(text, allowed, subject=subject)
        next_step = "fixing_sources"
        if problem is None:
            next_step = "simplifying"
            text, added = enforce_trust_rules(text, data, language)
            grade = reading_grade(text, language)
            candidate = Explanation(
                text, cited_edges(text), grade, attempts=attempt, added_notes=added
            )
            if best is None or (grade or 0) < (best.reading_grade or 0):
                best = candidate
            if passes_grade(grade, role, language):
                return candidate
            problem = (
                f"The text reads at grade {grade}; the target is grade "
                f"{grade_target(role, language):g} or lower. Rewrite it simpler: shorter "
                "sentences, everyday words, same facts and citations."
            )
        items = [
            *items,
            {"role": "assistant", "content": raw or "(empty)"},
            {"role": "user", "content": problem},
        ]
    if best is not None:
        best.attempts = max_attempts
        return best
    raise ExplanationError("no valid explanation")
