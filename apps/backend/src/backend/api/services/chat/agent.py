"""One orchestrating agent ("Dr. Wu"): system prompt, tool loop, post-checks.

`run_agent` is the turn without persistence (used by run_turn and by the eval harness)."""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.api.services.chat import safety
from backend.api.services.chat.postcheck import AgentDraft, CheckReport, check_reply
from backend.api.services.chat.tools import TurnState, build_tools
from backend.api.services.explanation.common import (
    AI_NOTICES,
    base_language,
    language_name,
    looks_german,
    pick,
)
from backend.llm import LLMClient, ToolEvent, Usage
from backend.observability.tracing import Tracer
from backend.schemas.chat import AgentReply
from backend.schemas.common import Lens
from backend.schemas.profile import PatientProfile

MAX_TOOL_CALLS = 8
TURN_DEADLINE_S = 45.0
HISTORY_MESSAGES = 8

SYSTEM_PROMPT = """You are Dr. Henry Wu, the guide of the Amber rare-disease atlas.
You help patients, caregivers, researchers and biotech scouts find
what connects rare diseases: shared mechanisms, symptoms, people,
assets and trials. You are an AI system, not a clinician.

Rules:
1. Answer only from tool results. Every claim cites edge_ids.
2. Label each claim by origin. Never present inference as fact.
3. Always surface contradicting evidence.
4. If no supported path exists, say so and name what evidence is missing.
5. Summary first, in plain language for the user's role; detail goes in claims.
6. Never diagnose, recommend treatment, give prognosis unless asked, or reclassify variants.
   For VUS results, use the standard uncertainty sentence.
   Emergency language: tell the user to call emergency services and stop.
7. End with one concrete, viable next action when the evidence allows it.
8. Ask at most one follow-up question, only when it separates candidate clusters.
9. Reply in the user's language.

User role: {role}. Expert mode: {expert_mode}. Profile: {profile}.

How to work:
- New mentions in the message: extract_entities, then resolve_to_ids. Resolved items become
  chips the user confirms; only the confirmed profile above counts as known.
- Who shares our characteristics: get_neighborhood on the user's disease (cluster, mechanism
  edges same_gene_same_mechanism / shared_pathway, symptom edges similar_symptoms = "similar
  experience, possibly different cause"), then find_path from the user's disease to the 2-3
  most relevant cluster members. Name one counterexample (same_gene_different_mechanism).
- What already exists: serves / runs edges (patient groups, registries, natural history
  studies), studies (trials), shared_researcher / pi_of / funds_research_on (people, funders).
- What to do next: one action (reuse_asset, contact, join_trial or fund) with edge_ids,
  timeline_today (how long this takes today), timeline_proposed (with the proposed route) and
  the assumptions behind it. Mark viable=true only if all its edges are observed and active.
- Symptoms only, no diagnosis: show clusters "to discuss with a clinical geneticist".
- Expert mode: mechanism queries go to search_graph with expert=true; rank the clusters.
- If several clusters remain and one answer would separate them, call ask_followup once.
- Starting point for this role: {start}.

Output (the final JSON object):
- summary: at most 3 short sentences, no citations, reading grade {grade} for this role.
- claims: one fact each, edge_ids copied exactly from tool results, origin observed/inferred/
  patient_reported/user_contributed, confidence high (>=0.8) / medium (>=0.5) / low.
- contradictions: claim_index + edge_ids + note for evidence that contradicts a claim.
- missing_evidence: what no source connects yet, in plain words.
- cards: mini_graph / patient_group / evidence / open_in_atlas with node_ids and edge_ids from
  tool results. graph_focus: node_ids and highlight_path (edge ids of the best path, in order).
- follow_up: only if you called ask_followup (you may translate its question), else null.
Write all text in {language}."""

START_BY_ROLE = {
    "patient": "the user's disease, with similar diseases and patient communities",
    "guest": "the user's disease, in very simple words",
    "doctor": "the symptom profile, with centers of expertise, clinical studies and variant "
    "classifications",
    "researcher": "mechanism clusters, with variants, pathways, papers and funding; show IDs",
}


@dataclass
class TurnResult:
    reply: AgentReply
    emergency: bool = False
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    model: str | None = None
    tool_mode: str | None = None
    latency_ms: int = 0
    checks: CheckReport | None = None
    asked: list[str] = field(default_factory=list)

    @property
    def cited_edge_ids(self) -> list[str]:
        return sorted({e for c in self.reply.claims for e in c.edge_ids})


def reply_language(message: str, lens: Lens) -> str:
    if looks_german(message):
        return "de"
    return base_language(lens.language)


def profile_json(profile: PatientProfile) -> str:
    data = profile.model_dump(mode="json", exclude_none=True, exclude={"updated_at"})
    data = {k: v for k, v in data.items() if v not in ([], False)}
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")) if data else "{}"


def system_prompt(lens: Lens, profile_text: str, language: str) -> str:
    from backend.api.services.explanation.common import GRADE_TARGETS

    return SYSTEM_PROMPT.format(
        role=lens.role.value,
        expert_mode=str(lens.expert_mode).lower(),
        profile=profile_text,
        start=START_BY_ROLE.get(lens.role.value, START_BY_ROLE["patient"]),
        grade=f"{GRADE_TARGETS.get(lens.role, 8.0):g} or lower",
        language=language_name(language),
    )


def emergency_result(message: str, lens: Lens) -> TurnResult:
    language = reply_language(message, lens)
    reply = AgentReply(
        summary=safety.emergency_reply(language),
        uncertainty=None,
        chips=[],
        claims=[],
        contradictions=[],
        missing_evidence=[],
        cards=[],
        graph_focus=None,
        actions=[],
        follow_up=None,
        ai_notice=pick(AI_NOTICES, language),
        kind="emergency",
    )
    return TurnResult(reply=reply, emergency=True)


async def run_agent(
    llm: LLMClient,
    *,
    message: str,
    lens: Lens,
    profile: PatientProfile,
    profile_text: str,
    history: list[dict[str, str]] | None = None,
    on_status: Callable[[str | None, str], Any] | None = None,
    tracer: Tracer | None = None,
) -> TurnResult:
    """One turn on an already redacted message. Emergency handling happens before this."""
    started = time.monotonic()
    language = reply_language(message, lens)
    state = TurnState(lens=lens, message=message, profile=profile, reply_language=language)
    asked = safety.asked_categories(message)
    instructions = system_prompt(lens, profile_text, language)
    if asked - {safety.Category.prognosis}:
        what = ", ".join(sorted(c.value for c in asked - {safety.Category.prognosis}))
        instructions += "\n\n" + safety.SYSTEM_PROMPT_HINT.format(what=what)
    items: list[dict[str, str]] = [*(history or [])[-HISTORY_MESSAGES:]]
    items.append({"role": "user", "content": message})

    async def on_event(event: ToolEvent) -> None:
        if event.type == "tool_start" and on_status is not None and event.name:
            res = on_status(event.name, state.status_text(event.name))
            if hasattr(res, "__await__"):
                await res

    tools = build_tools(state, llm)
    result = await llm.run_tools(
        instructions=instructions,
        input=items,
        tools=tools,
        final_schema=AgentDraft,
        kind="main",
        max_tool_calls=MAX_TOOL_CALLS,
        deadline_s=TURN_DEADLINE_S,
        on_event=on_event,
    )
    if on_status is not None:
        res = on_status(None, state.status_text("checks"))
        if hasattr(res, "__await__"):
            await res
    draft = result.output or AgentDraft(
        summary="",
        uncertainty=None,
        claims=[],
        contradictions=[],
        missing_evidence=[],
        cards=[],
        graph_focus=None,
        actions=[],
        follow_up=None,
    )
    reply, report = await check_reply(draft, state, llm, asked=asked)
    if tracer is not None:
        with tracer.span("chat.postcheck", metadata=report.as_metadata()):
            pass
    return TurnResult(
        reply=reply,
        tool_calls=[
            {
                "name": c.name,
                "duration_ms": c.duration_ms,
                "error": c.error,
            }
            for c in result.tool_calls
        ],
        usage=result.usage,
        model=result.model,
        tool_mode=result.tool_mode,
        latency_ms=round((time.monotonic() - started) * 1000),
        checks=report,
        asked=sorted(c.value for c in asked),
    )
