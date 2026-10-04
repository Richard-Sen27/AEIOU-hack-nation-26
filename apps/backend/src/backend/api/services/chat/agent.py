"""One orchestrating agent ("Dr. Wu"): system prompt, the turn graph (LangGraph), post-checks.

`run_graph` runs one turn as a graph; a chat run adds persistence and checkpoints, `run_agent`
is the same turn without them (eval harness, tests)."""

import asyncio
import json
import logging
import operator
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

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
# text, entities, ids or user identifiers. Written through the app's stdout handler
# (backend.observability.logs), with the request id of the turn's POST /chat.
timing_log = logging.getLogger("backend.chat.timing")

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


# ---- the turn as a LangGraph graph ---------------------------------------------------------
#
# Nodes are plain functions around the code above. Graph state holds JSON values only and only
# redacted content (it is what a checkpoint stores); everything that must never be stored (the
# LLM client with the user's credentials, the profile and its redacted text, the history, the
# tool cache, the clock) lives in the run's TurnContext, passed as LangGraph runtime context,
# which is never checkpointed. Redaction and emergency detection run before the graph, on the
# raw text, so raw text never enters the graph.


class TurnGraphState(TypedDict, total=False):
    message: str  # redacted
    emergency: bool  # set before the graph (emergency detection needs the raw text too)
    asked: list[str]  # boundary categories the message asks for
    steps: Annotated[list[dict[str, Any]], operator.add]  # status steps shown so far
    context: list[str]  # extract/resolve results handed to the first round
    partial: str | None  # error code when the answer is built from what tools gathered
    draft: dict[str, Any] | None  # the model's answer before the post-check
    reply: dict[str, Any] | None  # the checked reply
    message_id: str | None  # the stored assistant message


@dataclass
class TurnContext:
    """Per-run objects that are never checkpointed."""

    llm: LLMClient | None
    lens: Lens
    profile: PatientProfile
    profile_text: str  # redacted
    history: list[dict[str, str]]
    on_status: Callable[[str | None, str], Any] | None = None
    tracer: Tracer | None = None
    persist: Callable[[AgentReply], Awaitable[Any]] | None = None
    started: float = field(default_factory=time.monotonic)
    deadline: float = 0.0
    state: TurnState | None = None
    clock: _TurnClock | None = None
    asked: set = field(default_factory=set)
    instructions: str = ""
    tools: list = field(default_factory=list)
    result: Any = None  # ToolRunResult of the agent node
    draft: AgentDraft | None = None
    reply: AgentReply | None = None
    report: CheckReport | None = None
    pending_steps: list[dict[str, Any]] = field(default_factory=list)

    async def status(self, tool: str | None, key: str) -> None:
        assert self.state is not None
        message = self.state.status_text(key)
        self.pending_steps.append({"tool": tool, "message": message})
        if self.on_status is not None:
            res = self.on_status(tool, message)
            if hasattr(res, "__await__"):
                await res

    def take_steps(self) -> list[dict[str, Any]]:
        steps, self.pending_steps = self.pending_steps, []
        return steps


def _ctx(runtime: Runtime[TurnContext]) -> TurnContext:
    return runtime.context


def _gathered(ctx: TurnContext, exc: LLMError) -> str:
    """A deadline or bad output after tools found something: answer from what was gathered
    (built in code, post-checked, no model call). Any other error ends the turn."""
    assert ctx.state is not None and ctx.clock is not None
    ctx.clock.cut_open_tools()
    if exc.code not in ("timeout", "bad_output") or not (ctx.state.chips or ctx.state.edges):
        raise exc
    return exc.code


async def _node_safety(state: TurnGraphState, runtime: Runtime[TurnContext]) -> dict:
    ctx = _ctx(runtime)
    ctx.asked = safety.asked_categories(state["message"])
    return {"asked": sorted(c.value for c in ctx.asked)}


def _after_safety(state: TurnGraphState) -> str:
    return "emergency" if state.get("emergency") else "entities"


async def _node_emergency(state: TurnGraphState, runtime: Runtime[TurnContext]) -> dict:
    ctx = _ctx(runtime)
    ctx.reply = emergency_result(state["message"], ctx.lens).reply
    return {"reply": ctx.reply.model_dump(mode="json")}


async def _node_entities(state: TurnGraphState, runtime: Runtime[TurnContext]) -> dict:
    ctx = _ctx(runtime)
    assert ctx.llm is not None and ctx.state is not None and ctx.clock is not None
    try:
        try:
            async with asyncio.timeout(max(0.0, ctx.deadline - time.monotonic())):
                await _warm_models(ctx.llm, ctx.clock)
                context = await _entities_first(ctx.llm, ctx.state, ctx.clock, ctx.status)
        except TimeoutError:
            raise LLMError("timeout", "turn exceeded its deadline") from None
    except LLMError as exc:
        return {"partial": _gathered(ctx, exc), "steps": ctx.take_steps()}
    return {"context": context, "partial": None, "steps": ctx.take_steps()}


def _after_entities(state: TurnGraphState) -> str:
    return "partial" if state.get("partial") else "agent"


async def _node_agent(state: TurnGraphState, runtime: Runtime[TurnContext]) -> dict:
    """The model/tool rounds and the final answer (the round with tools disabled), inside the
    gateway's run_tools, which enforces the round, call and time budgets."""
    ctx = _ctx(runtime)
    assert ctx.llm is not None and ctx.clock is not None
    items: list[dict[str, str]] = [*ctx.history[-HISTORY_MESSAGES:]]
    items.append({"role": "user", "content": state["message"]})
    items += [{"role": "developer", "content": c} for c in state.get("context") or []]

    async def on_event(event: ToolEvent) -> None:
        ctx.clock.tool_event(event)
        if event.type == "tool_start" and event.name:
            await ctx.status(event.name, event.name)
        elif event.type == "final_round":
            ctx.clock.step("budget", event.name or "unknown", 0)
            await ctx.status(None, "answer")

    elapsed = time.monotonic() - ctx.started
    try:
        ctx.result = await ctx.llm.run_tools(
            instructions=ctx.instructions,
            input=items,
            tools=ctx.tools,
            final_schema=AgentDraft,
            kind="main",
            max_tool_calls=MAX_TOOL_CALLS,
            deadline_s=max(0.0, ctx.deadline - time.monotonic()),
            on_event=on_event,
            max_rounds=MAX_TOOL_ROUNDS,
            tools_for_s=max(0.0, TOOL_PHASE_S - elapsed),
            final_note=FINAL_NOTE,
            tool_effort="low",
        )
    except LLMError as exc:
        return {"partial": _gathered(ctx, exc), "steps": ctx.take_steps()}
    if ctx.result.output is None:
        return {"partial": None, "steps": ctx.take_steps()}
    ctx.draft = ctx.result.output
    return {
        "partial": None,
        "draft": ctx.draft.model_dump(mode="json"),
        "steps": ctx.take_steps(),
    }


def _after_agent(state: TurnGraphState) -> str:
    return "postcheck" if state.get("draft") else "partial"


async def _node_partial(state: TurnGraphState, runtime: Runtime[TurnContext]) -> dict:
    """The answer built in code from what the tools gathered (deadline or bad output)."""
    ctx = _ctx(runtime)
    assert ctx.state is not None
    ctx.draft = partial_draft(ctx.state)
    return {"draft": ctx.draft.model_dump(mode="json")}


async def _node_postcheck(state: TurnGraphState, runtime: Runtime[TurnContext]) -> dict:
    ctx = _ctx(runtime)
    assert ctx.state is not None and ctx.clock is not None and ctx.draft is not None
    partial = state.get("partial")
    await ctx.status(None, "checks")
    checks_started = time.monotonic()
    ctx.reply, ctx.report = await check_reply(
        ctx.draft,
        ctx.state,
        None if partial else ctx.llm,
        asked=ctx.asked,
        deadline=ctx.deadline,
    )
    ctx.clock.step("check", "postcheck", (time.monotonic() - checks_started) * 1000)
    ctx.clock.finish("partial" if partial else "answered", partial)
    if ctx.tracer is not None:
        with ctx.tracer.span("chat.postcheck", metadata=ctx.report.as_metadata()):
            pass
    return {"reply": ctx.reply.model_dump(mode="json"), "steps": ctx.take_steps()}


async def _node_persist(state: TurnGraphState, runtime: Runtime[TurnContext]) -> dict:
    """Store the reply (and end the run) in one transaction."""
    ctx = _ctx(runtime)
    assert ctx.persist is not None and ctx.reply is not None
    message_id = await ctx.persist(ctx.reply)
    return {"message_id": str(message_id)}


def build_turn_graph(*, persist: bool) -> StateGraph:
    """safety -> (emergency | entities -> agent -> [partial] -> postcheck) -> [persist].

    New steps (a pause for the user's confirmation, a multi-step plan) go between agent and
    postcheck; see docs/homework.md."""
    graph = StateGraph(TurnGraphState, context_schema=TurnContext)
    graph.add_node("safety", _node_safety)
    graph.add_node("emergency", _node_emergency)
    graph.add_node("entities", _node_entities)
    graph.add_node("agent", _node_agent)
    graph.add_node("partial", _node_partial)
    graph.add_node("postcheck", _node_postcheck)
    graph.add_edge(START, "safety")
    graph.add_conditional_edges("safety", _after_safety, ["emergency", "entities"])
    graph.add_conditional_edges("entities", _after_entities, ["agent", "partial"])
    graph.add_conditional_edges("agent", _after_agent, ["postcheck", "partial"])
    graph.add_edge("partial", "postcheck")
    if persist:
        graph.add_node("persist", _node_persist)
        graph.add_edge("emergency", "persist")
        graph.add_edge("postcheck", "persist")
        graph.add_edge("persist", END)
    else:
        graph.add_edge("emergency", END)
        graph.add_edge("postcheck", END)
    return graph


_compiled: dict[tuple[bool, int], Any] = {}


def _turn_graph(persist: bool, checkpointer: Any = None):
    key = (persist, id(checkpointer))
    if key not in _compiled:
        _compiled[key] = build_turn_graph(persist=persist).compile(checkpointer=checkpointer)
    return _compiled[key]


async def run_graph(
    llm: LLMClient | None,
    *,
    message: str,
    lens: Lens,
    profile: PatientProfile,
    profile_text: str,
    history: list[dict[str, str]] | None = None,
    emergency: bool = False,
    on_status: Callable[[str | None, str], Any] | None = None,
    tracer: Tracer | None = None,
    persist: Callable[[AgentReply], Awaitable[Any]] | None = None,
    checkpointer: Any = None,
    config: dict[str, Any] | None = None,
    steps: list[dict[str, Any]] | None = None,
) -> TurnResult:
    """One turn on an already redacted message, as a graph run. With `persist` the graph ends
    by storing the reply; with `checkpointer` + `config` its state is checkpointed per node."""
    ctx = TurnContext(
        llm=llm,
        lens=lens,
        profile=profile,
        profile_text=profile_text,
        history=list(history or []),
        on_status=on_status,
        tracer=tracer,
        persist=persist,
    )
    ctx.deadline = ctx.started + TURN_DEADLINE_S
    language = reply_language(message, lens)
    ctx.state = TurnState(lens=lens, message=message, profile=profile, reply_language=language)
    instructions = system_prompt(lens, profile_text, language)
    asked = safety.asked_categories(message)
    if asked - {safety.Category.prognosis}:
        what = ", ".join(sorted(c.value for c in asked - {safety.Category.prognosis}))
        instructions += "\n\n" + safety.SYSTEM_PROMPT_HINT.format(what=what)
    ctx.instructions = instructions
    if llm is not None:
        ctx.tools = build_tools(ctx.state, llm)
    ctx.clock = _TurnClock({t.name for t in ctx.tools} | {"extract_entities"})
    graph = _turn_graph(persist is not None, checkpointer)
    initial: TurnGraphState = {"message": message, "emergency": emergency, "steps": steps or []}
    with observe_calls(ctx.clock.model_call):
        try:
            await graph.ainvoke(initial, config or {}, context=ctx)
        except LLMError as exc:
            ctx.clock.cut_open_tools()
            ctx.clock.finish("deadline" if exc.code == "timeout" else "error", exc.code)
            raise
        except asyncio.CancelledError:
            ctx.clock.cut_open_tools()
            ctx.clock.finish("cancelled")
            raise
        except Exception as exc:
            ctx.clock.cut_open_tools()
            ctx.clock.finish("error", type(exc).__name__)
            raise
    assert ctx.reply is not None
    if emergency:
        return TurnResult(reply=ctx.reply, emergency=True)
    result = ctx.result
    return TurnResult(
        reply=ctx.reply,
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
        latency_ms=round((time.monotonic() - ctx.started) * 1000),
        checks=ctx.report,
        asked=sorted(c.value for c in asked),
    )


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
    """One turn on an already redacted message, without persistence (eval harness, tests).
    Emergency handling happens before this. Same graph as a chat run, minus its last node."""
    return await run_graph(
        llm,
        message=message,
        lens=lens,
        profile=profile,
        profile_text=profile_text,
        history=history,
        on_status=on_status,
        tracer=tracer,
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
