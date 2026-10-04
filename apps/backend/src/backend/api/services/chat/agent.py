"""One orchestrating agent ("Dr. Wu"): system prompt, tool loop, post-checks.

`run_agent` is the turn without persistence (used by run_turn and by the eval harness)."""

import asyncio
import json
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from backend.api.services import graph as graph_service
from backend.api.services.chat import safety
from backend.api.services.chat.postcheck import AgentDraft, CheckReport, check_reply
from backend.api.services.chat.tools import (
    _RELATION_PRIORITY,
    TurnState,
    build_tools,
    extract,
    extraction_mentions,
    match_phenotypes,
    resolve,
    symptoms_only,
)
from backend.api.services.explanation.common import (
    AI_NOTICES,
    base_language,
    language_name,
    looks_german,
    pick,
)
from backend.api.services.explanation.templates import RELATION_PHRASES
from backend.llm import LLMClient, LLMError, ToolEvent, Usage, observe_calls
from backend.observability.tracing import Tracer
from backend.schemas.chat import AgentReply, Card, Claim
from backend.schemas.common import Lens
from backend.schemas.enums import CardType, EdgeStatus, Origin, PathStatus, confidence_level
from backend.schemas.graph import Edge
from backend.schemas.profile import PatientProfile

# Budget, chosen from real turns on the ChatGPT plan (3.5-10 s per model call, tools ~0.1 s):
# the message is extracted and resolved before the first round (one small-model call), then
# at most MAX_TOOL_ROUNDS rounds may call tools, and none starts after TOOL_PHASE_S into the
# turn; the next call is the final answer with tools disabled. That ends a standard turn at
# about 30 s. TURN_DEADLINE_S is only the backstop: when it fires, the turn answers from what
# its tools gathered (built in code, post-checked) instead of failing.
MAX_TOOL_CALLS = 8
MAX_TOOL_ROUNDS = 3
TOOL_PHASE_S = 15.0
TURN_DEADLINE_S = 90.0
HISTORY_MESSAGES = 8
PARTIAL_CLAIMS = 3

# Per-step timing of each turn: step names, model slugs and milliseconds only, never message
# text, entities, ids or user identifiers. The app configures no log handlers and uvicorn only
# configures its own loggers, so this logger gets its own stderr handler to show up in the
# server log.
timing_log = logging.getLogger("backend.chat.timing")
if not timing_log.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    timing_log.addHandler(_handler)
    timing_log.setLevel(logging.INFO)

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
- The user's message is already extracted and resolved: the resolve_to_ids result after it
  lists the ids. Use them directly; call resolve_to_ids only for terms it is missing. Resolved
  items become chips the user confirms; only the confirmed profile above counts as known.
- You have at most {rounds} rounds of tool calls. Call independent tools together in one
  round (for example get_neighborhood and search_graph, or several find_path calls).
- Who shares our characteristics: get_neighborhood on the user's disease (cluster, mechanism
  edges same_gene_same_mechanism / shared_pathway, symptom edges similar_symptoms = "similar
  experience, possibly different cause"), then find_path from the user's disease to the 2-3
  most relevant cluster members. Name one counterexample (same_gene_different_mechanism).
- What already exists: serves / runs edges (patient groups, registries, natural history
  studies), studies (trials), shared_researcher / pi_of / funds_research_on (people, funders).
- What to do next: one action (reuse_asset, contact, join_trial or fund) with edge_ids,
  timeline_today (how long this takes today), timeline_proposed (with the proposed route) and
  the assumptions behind it. Mark viable=true only if all its edges are observed and active.
- Symptoms only, no diagnosis: the server already ran match_phenotypes on them (its result
  follows the message). Present its results as "conditions in the atlas whose recorded
  symptoms overlap", with the overlap count ("3 of your 4 symptoms are recorded for it"), and
  cite the has_phenotype edge_ids it lists. Never give a probability, likelihood or
  percentage, never write "you have" or "this is", never call one a diagnosis; they are to
  discuss with a clinical geneticist. Call match_phenotypes only for symptoms it lacks.
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


class _TurnClock:
    """Writes one timing line per model call, tool call and post-check, and one per turn."""

    def __init__(self, tool_names: set[str]):
        self.started = time.monotonic()
        self.tool_names = tool_names
        self.open_tools: dict[str, tuple[str, float]] = {}
        self.model_calls = 0
        self.tool_calls = 0

    def elapsed_ms(self) -> int:
        return round((time.monotonic() - self.started) * 1000)

    def _name(self, name: str | None) -> str:
        return name if name in self.tool_names else "unknown"

    def step(
        self,
        kind: str,
        name: str,
        duration_ms: float,
        error: str | None = None,
        model: str | None = None,
    ) -> None:
        timing_log.info(
            "chat step kind=%s name=%s%s duration_ms=%d elapsed_ms=%d%s",
            kind,
            name,
            f" model={model}" if model else "",
            round(duration_ms),
            self.elapsed_ms(),
            f" error={error}" if error else "",
        )

    def model_call(self, step: str, model: str, duration_ms: float, error: str | None) -> None:
        self.model_calls += 1
        self.step("model", step, duration_ms, error, model=model or "unknown")

    def tool_event(self, event: ToolEvent) -> None:
        key = event.call_id or ""
        if event.type == "tool_start":
            self.open_tools[key] = (self._name(event.name), time.monotonic())
        elif event.type == "tool_end":
            self.open_tools.pop(key, None)
            self.tool_calls += 1
            self.step("tool", self._name(event.name), event.duration_ms or 0.0, event.error)

    def cut_open_tools(self) -> None:
        """Tools still running when the deadline fired never send tool_end."""
        for name, started in self.open_tools.values():
            self.tool_calls += 1
            self.step("tool", name, (time.monotonic() - started) * 1000, "cancelled")
        self.open_tools.clear()

    def finish(self, outcome: str, error: str | None = None) -> None:
        timing_log.info(
            "chat turn outcome=%s total_ms=%d model_calls=%d tool_calls=%d%s",
            outcome,
            self.elapsed_ms(),
            self.model_calls,
            self.tool_calls,
            f" error={error}" if error else "",
        )


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
        rounds=MAX_TOOL_ROUNDS,
    )


FINAL_NOTE = (
    "Name in missing_evidence, in plain words, what you could not check in this turn. Every "
    "claim still cites edge_ids from the tool results; never diagnose."
)
CONTEXT_NOTE = (
    "The server ran extract_entities and resolve_to_ids on the user's message before this "
    "round. Chips are unconfirmed suggestions."
)
PARTIAL_TEXT = {
    "summary": {
        "en": "I ran out of time before I could finish checking, so this answer is incomplete.",
        "de": "Mir ist die Zeit ausgegangen, bevor ich alles prüfen konnte; diese Antwort ist "
        "unvollständig.",
    },
    "found": {
        "en": "Below is what I found so far.",
        "de": "Unten steht, was ich bis dahin gefunden habe.",
    },
    "missing": {
        "en": "Not checked in time: the remaining connections for this question. Ask again to "
        "continue.",
        "de": "Nicht rechtzeitig geprüft: die übrigen Verbindungen zu dieser Frage. Fragen Sie "
        "erneut, um weiterzumachen.",
    },
}


def _label(state: TurnState, node_id: str) -> str:
    node = state.nodes.get(node_id) or graph_service.get_node(node_id)
    return node.label if node else node_id


def _partial_edges(state: TurnState) -> list[Edge]:
    """The best supported path found, else the strongest edges at the resolved chips."""
    for resp in state.paths:
        if resp.status == PathStatus.ok:
            for path in resp.paths:
                if path.supported:
                    return [s.edge for s in path.steps][:PARTIAL_CLAIMS]
    anchors = {c.id for c in state.chips.values() if c.id and not c.negated}
    edges = [e for e in state.edges.values() if anchors & {e.source_id, e.target_id}]
    edges.sort(
        key=lambda e: (
            e.origin != Origin.observed,
            e.status != EdgeStatus.active,
            _RELATION_PRIORITY.get(e.relation, 4),
            -e.confidence,
            e.id,
        )
    )
    return edges[:PARTIAL_CLAIMS]


def partial_draft(state: TurnState) -> AgentDraft:
    """A short answer built in code from what the tools gathered, for a turn the deadline cut:
    each claim is one cited edge in a fixed sentence; the post-check runs on it as usual."""
    lang = base_language(state.reply_language)
    phrases = RELATION_PHRASES.get(lang, RELATION_PHRASES["en"])
    claims = []
    for e in _partial_edges(state):
        phrase = phrases.get(e.relation.value, phrases["_default"])
        text = phrase.format(s=_label(state, e.source_id), t=_label(state, e.target_id))
        claims.append(
            Claim(
                text=text[0].upper() + text[1:] + ".",
                edge_ids=[e.id],
                origin=e.origin,
                confidence=confidence_level(e.confidence),
            )
        )
    nodes = list(dict.fromkeys(n for c in claims for e in c.edge_ids for n in _ends(state, e)))
    summary = pick(PARTIAL_TEXT["summary"], lang)
    if claims:
        summary += " " + pick(PARTIAL_TEXT["found"], lang)
    return AgentDraft(
        summary=summary,
        uncertainty=None,
        claims=claims,
        contradictions=[],
        missing_evidence=[pick(PARTIAL_TEXT["missing"], lang)],
        cards=[Card(type=CardType.open_in_atlas, node_ids=nodes[:4], edge_ids=[])] if nodes else [],
        graph_focus=None,
        actions=[],
        follow_up=None,
    )


def _ends(state: TurnState, edge_id: str) -> tuple[str, ...]:
    edge = state.edges.get(edge_id)
    return (edge.source_id, edge.target_id) if edge else ()


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
    deadline = started + TURN_DEADLINE_S
    language = reply_language(message, lens)
    state = TurnState(lens=lens, message=message, profile=profile, reply_language=language)
    asked = safety.asked_categories(message)
    instructions = system_prompt(lens, profile_text, language)
    if asked - {safety.Category.prognosis}:
        what = ", ".join(sorted(c.value for c in asked - {safety.Category.prognosis}))
        instructions += "\n\n" + safety.SYSTEM_PROMPT_HINT.format(what=what)
    items: list[dict[str, str]] = [*(history or [])[-HISTORY_MESSAGES:]]
    items.append({"role": "user", "content": message})

    tools = build_tools(state, llm)
    clock = _TurnClock({t.name for t in tools} | {"extract_entities"})

    async def status(tool: str | None, key: str) -> None:
        if on_status is not None:
            res = on_status(tool, state.status_text(key))
            if hasattr(res, "__await__"):
                await res

    async def on_event(event: ToolEvent) -> None:
        clock.tool_event(event)
        if event.type == "tool_start" and event.name:
            await status(event.name, event.name)
        elif event.type == "final_round":
            clock.step("budget", event.name or "unknown", 0)
            await status(None, "answer")

    result = None
    partial: str | None = None
    with observe_calls(clock.model_call):
        try:
            try:
                async with asyncio.timeout(TURN_DEADLINE_S):
                    await _warm_models(llm, clock)
                    context = await _entities_first(llm, state, clock, status)
            except TimeoutError:
                raise LLMError("timeout", "turn exceeded its deadline") from None
            items += [{"role": "developer", "content": c} for c in context]
            elapsed = time.monotonic() - started
            result = await llm.run_tools(
                instructions=instructions,
                input=items,
                tools=tools,
                final_schema=AgentDraft,
                kind="main",
                max_tool_calls=MAX_TOOL_CALLS,
                deadline_s=max(0.0, deadline - time.monotonic()),
                on_event=on_event,
                max_rounds=MAX_TOOL_ROUNDS,
                tools_for_s=max(0.0, TOOL_PHASE_S - elapsed),
                final_note=FINAL_NOTE,
                tool_effort="low",
            )
        except LLMError as exc:
            clock.cut_open_tools()
            if exc.code not in ("timeout", "bad_output") or not (state.chips or state.edges):
                clock.finish("deadline" if exc.code == "timeout" else "error", exc.code)
                raise
            partial = exc.code  # answer from what was gathered (post-checked, no model call)
        except asyncio.CancelledError:
            clock.cut_open_tools()
            clock.finish("cancelled")
            raise
        except Exception as exc:
            clock.cut_open_tools()
            clock.finish("error", type(exc).__name__)
            raise

        await status(None, "checks")
        draft = partial_draft(state) if result is None or result.output is None else result.output
        checks_started = time.monotonic()
        reply, report = await check_reply(
            draft, state, None if partial else llm, asked=asked, deadline=deadline
        )
        clock.step("check", "postcheck", (time.monotonic() - checks_started) * 1000)
    clock.finish("partial" if partial else "answered", partial)
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
            for c in (result.tool_calls if result else [])
        ],
        usage=result.usage if result else Usage(),
        model=result.model if result else None,
        tool_mode=result.tool_mode if result else None,
        latency_ms=round((time.monotonic() - started) * 1000),
        checks=report,
        asked=sorted(c.value for c in asked),
    )


async def _warm_models(llm: LLMClient, clock: _TurnClock) -> None:
    """Resolve both model slugs (a cached model list makes this instant; the chat service
    starts the listing while it redacts the message)."""
    started = time.monotonic()
    await llm.resolve_model("small")
    await llm.resolve_model("main")
    clock.step("prep", "models", (time.monotonic() - started) * 1000)


async def _entities_first(
    llm: LLMClient,
    state: TurnState,
    clock: _TurnClock,
    status: Callable[[str | None, str], Any],
) -> list[str]:
    """extract_entities and resolve_to_ids in code before the first round, so the first round
    can already use the ids; for a symptoms-only message also match_phenotypes, so the first
    round already has the conditions whose recorded symptoms overlap (no search rounds, no
    extra model call). Returns these results as tool results for the model ([] when there are
    none). Bad extraction output is not fatal: the model can still resolve terms itself."""
    await status("extract_entities", "extract_entities")
    started = time.monotonic()
    try:
        extraction = await extract(state, llm)
    except LLMError as exc:
        clock.step("tool", "extract_entities", (time.monotonic() - started) * 1000, exc.code)
        clock.tool_calls += 1
        if exc.code != "bad_output":
            raise
        return []
    clock.tool_calls += 1
    clock.step("tool", "extract_entities", (time.monotonic() - started) * 1000)
    mentions = extraction_mentions(extraction)
    if not mentions:
        return []
    await status("resolve_to_ids", "resolve_to_ids")
    started = time.monotonic()
    resolution = await resolve(state, mentions)
    clock.tool_calls += 1
    clock.step("tool", "resolve_to_ids", (time.monotonic() - started) * 1000)
    payload = json.dumps({**resolution, "note": CONTEXT_NOTE}, ensure_ascii=False)
    context = [f'<tool_result name="resolve_to_ids">{payload}</tool_result>']
    if symptoms_only(extraction):
        await status("match_phenotypes", "match_phenotypes")
        started = time.monotonic()
        present = [m.english or m.text for m in extraction.symptoms if not m.negated]
        absent = [m.english or m.text for m in extraction.symptoms if m.negated]
        matches = match_phenotypes(state, present, absent)
        clock.tool_calls += 1
        clock.step("tool", "match_phenotypes", (time.monotonic() - started) * 1000)
        payload = json.dumps(matches, ensure_ascii=False)
        context.append(f'<tool_result name="match_phenotypes">{payload}</tool_result>')
    return context
