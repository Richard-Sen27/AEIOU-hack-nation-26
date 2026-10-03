"""Gap-search agent: looks for evidence for a missing link. Never receives user data.

The agent's input is built only from public graph terms of the two nodes (ids, labels,
synonyms): `build_agent_input` takes a `PublicTerms` and nothing else. Candidates are verified
in code (quote occurs in the fetched source text), are always `pending_review`, are kept for the
user on a job row and are never written to graph tables.
"""

import asyncio
import json
import logging
import re
import time
import unicodedata
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import openai
from pydantic import BaseModel, Field
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import ApiError
from backend.api.services import auth as auth_service
from backend.api.services.gap_search import tools as gap_tools
from backend.api.services.gap_search.tools import ToolContext
from backend.config import get_settings
from backend.db.models import JobRecord
from backend.db.session import user_transaction
from backend.llm import LLMClient, LLMError, Tool
from backend.schemas.account import CurrentUser
from backend.schemas.enums import (
    RELATION_FAMILY,
    EdgeFamily,
    ErrorCode,
    GapStopReason,
    JobKind,
    JobStatus,
    PathFamily,
    Relation,
)
from backend.schemas.events import (
    GapCandidateEvent,
    GapErrorEvent,
    GapFinalEvent,
    GapProgressEvent,
    GapSearchEvent,
)
from backend.schemas.gap import CandidateEdge, GapSearchRequest

log = logging.getLogger(__name__)

MAX_STEPS = 8  # tool calls
MAX_TURNS = MAX_STEPS + 3  # model responses
MAX_TOKENS = 150_000
TIMEOUT_S = 90.0
MAX_CANDIDATES = 5
MIN_QUOTE_CHARS = 20
MAX_QUOTE_CHARS = 1000
MAX_SYNONYMS = 8

TOOL_MESSAGES = {
    "pubmed_search": "Searching PubMed",
    "clinicaltrials_search": "Searching ClinicalTrials.gov",
    "fetch_page": "Reading a source page",
    "web_search": "Searching the web",
}


# ---- public terms (the only input the agent ever gets) ------------------------------------------


class PublicNode(BaseModel):
    id: str
    type: str
    label: str
    synonyms: list[str] = Field(default_factory=list)


class PublicTerms(BaseModel):
    """Graph ids and public labels/synonyms of the two nodes. Nothing about the user."""

    source: PublicNode
    target: PublicNode
    family: PathFamily


async def load_terms(db: AsyncSession, request: GapSearchRequest) -> PublicTerms:
    if request.from_id == request.to_id:
        raise ApiError(422, ErrorCode.validation_error, "Invalid request fields: to_id")
    nodes = {}
    for node_id in (request.from_id, request.to_id):
        row = (
            (
                await db.execute(
                    text("SELECT id, type, label FROM nodes WHERE id = :id"), {"id": node_id}
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise ApiError(404, ErrorCode.not_found)
        synonyms = (
            await db.scalars(
                text(
                    "SELECT DISTINCT synonym FROM node_synonyms WHERE node_id = :id"
                    " AND lower(synonym) <> lower(:label) ORDER BY synonym LIMIT 50"
                ),
                {"id": node_id, "label": row["label"]},
            )
        ).all()
        picked = sorted(synonyms, key=len)[:MAX_SYNONYMS]
        nodes[node_id] = PublicNode(
            id=row["id"], type=row["type"], label=row["label"], synonyms=picked
        )
    return PublicTerms(
        source=nodes[request.from_id], target=nodes[request.to_id], family=request.family
    )


def allowed_relations(family: PathFamily) -> list[Relation]:
    if family is PathFamily.all:
        return list(Relation)
    return [r for r, f in RELATION_FAMILY.items() if f == EdgeFamily(family.value)]


def build_agent_input(terms: PublicTerms) -> str:
    return json.dumps(
        {
            "node_a": terms.source.model_dump(),
            "node_b": terms.target.model_dump(),
            "edge_family": terms.family.value,
            "allowed_relations": [r.value for r in allowed_relations(terms.family)],
        },
        ensure_ascii=False,
    )


def instructions(web_search: bool) -> str:
    tools = "pubmed_search, clinicaltrials_search, " + ("web_search, " if web_search else "")
    return (
        "You look for published evidence of a direct relation between two nodes of a "
        "rare-disease knowledge graph, because the graph has no supported route between them. "
        f"Tools: {tools}fetch_page. Build search queries only from the node ids, labels and "
        "synonyms you are given. Keep it short: a few searches, then answer. "
        "Return candidates: source_id and target_id are the two given node ids, relation is "
        "one of allowed_relations, quote is a sentence copied character for character from a "
        "tool result, and source_url is the url of that tool result exactly as given. "
        f"At most {MAX_CANDIDATES} candidates; return an empty list when nothing states such "
        "a relation. Never invent quotes or urls."
    )


class CandidateDraft(BaseModel):
    source_id: str
    target_id: str
    relation: Relation
    quote: str
    source_url: str


class GapAgentOutput(BaseModel):
    candidates: list[CandidateDraft]


# ---- verification -------------------------------------------------------------------------------


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"[‐-―]", "-", value).replace("’", "'")
    return re.sub(r"\s+", " ", value).strip().casefold()


def verify(
    drafts: list[CandidateDraft], terms: PublicTerms, ctx: ToolContext
) -> list[CandidateEdge]:
    """Keep candidates whose quote occurs in the fetched source text; drop everything else."""
    ends = {terms.source.id, terms.target.id}
    allowed = set(allowed_relations(terms.family))
    out: list[CandidateEdge] = []
    seen: set[tuple] = set()
    for d in drafts:
        if {d.source_id, d.target_id} != ends or d.relation not in allowed:
            continue
        quote = d.quote.strip()
        if not (MIN_QUOTE_CHARS <= len(quote) <= MAX_QUOTE_CHARS):
            continue
        source = ctx.sources.get(d.source_url.strip())
        if source is None or _norm(quote) not in _norm(source.text):
            continue
        key = (d.relation, source.url, _norm(quote))
        if key in seen:
            continue
        seen.add(key)
        out.append(
            CandidateEdge(
                source_id=d.source_id,
                target_id=d.target_id,
                relation=d.relation,
                quote=quote,
                source_url=source.url,
                source_type=source.source_type,
                source_id_ref=source.source_ref,
            )
        )
    return out[:MAX_CANDIDATES]


# ---- agent runners ------------------------------------------------------------------------------


class _TokenBudget(Exception):
    pass


class _Fallback(Exception):
    pass


@dataclass
class _Outcome:
    output: GapAgentOutput | None
    stop_reason: GapStopReason
    runner: str


def _bind(ctx: ToolContext):
    async def pubmed_search(query: str) -> dict:
        """Search PubMed abstracts. Returns pmid, url, title and abstract per article."""
        return await gap_tools.pubmed_search(ctx, query)

    async def clinicaltrials_search(query: str) -> dict:
        """Search ClinicalTrials.gov studies. Returns nct_id, url, title, summary, conditions."""
        return await gap_tools.clinicaltrials_search(ctx, query)

    async def fetch_page(url: str) -> dict:
        """Fetch a public web page (http/https) and return its text."""
        return await gap_tools.fetch_page(ctx, url)

    async def web_search(query: str) -> dict:
        """Search the web. Returns title, url and snippet; use fetch_page to read a result."""
        return await gap_tools.web_search(ctx, query)

    fns = [pubmed_search, clinicaltrials_search, fetch_page]
    if ctx.web_search_enabled:
        fns.append(web_search)
    return fns


async def _run_agents_sdk(llm: LLMClient, terms: PublicTerms, ctx: ToolContext) -> _Outcome:
    from agents import Agent, MaxTurnsExceeded, RunHooks, Runner, function_tool

    from backend.llm.agents_sdk import build_agents_model, namespaced_tools, run_config

    class _Budget(RunHooks):
        async def on_llm_end(self, context, agent, response) -> None:
            if context.usage.total_tokens > MAX_TOKENS:
                raise _TokenBudget

    model = await build_agents_model(llm, kind="main")
    agent = Agent(
        name="gap_search",
        instructions=instructions(ctx.web_search_enabled),
        model=model,
        tools=namespaced_tools([function_tool(f) for f in _bind(ctx)]),
        output_type=GapAgentOutput,
    )
    result = Runner.run_streamed(
        agent,
        input=build_agent_input(terms),
        run_config=run_config(),
        max_turns=MAX_TURNS,
        hooks=_Budget(),
    )
    try:
        async for _ in result.stream_events():
            pass
    except MaxTurnsExceeded:
        return _Outcome(None, GapStopReason.max_steps, "agents_sdk")
    except openai.BadRequestError:
        if ctx.steps == 0:
            raise _Fallback from None
        raise LLMError("upstream", "request rejected", status=400) from None
    except openai.APIStatusError as exc:
        raise _llm_error(exc) from None
    except (openai.APITimeoutError, openai.APIConnectionError):
        raise LLMError("upstream", "connection failed") from None
    finally:
        result.cancel()
    output = result.final_output
    if not isinstance(output, GapAgentOutput):
        raise LLMError("bad_output", "agent output failed validation")
    return _Outcome(output, _stop_reason(ctx), "agents_sdk")


def _stop_reason(ctx: ToolContext, total_tokens: int = 0) -> GapStopReason:
    if ctx.exhausted == "tokens" or total_tokens > MAX_TOKENS:
        return GapStopReason.max_tokens
    if ctx.exhausted == "steps":
        return GapStopReason.max_steps
    return GapStopReason.completed


def _llm_error(exc: openai.APIStatusError) -> LLMError:
    from backend.llm.client import _map_status_error

    return _map_status_error(exc)


class _QueryArgs(BaseModel):
    query: str


class _UrlArgs(BaseModel):
    url: str


async def _run_gateway(llm: LLMClient, terms: PublicTerms, ctx: ToolContext) -> _Outcome:
    """Fallback: the gateway's own tool loop with the same tools and budgets."""
    ctx.max_tokens = MAX_TOKENS

    def tool(name: str, description: str, args: type[BaseModel], fn) -> Tool:
        async def handler(params: BaseModel) -> dict:
            return await fn(ctx, **params.model_dump())

        return Tool(name, description, args, handler)

    tools = [
        tool("pubmed_search", "Search PubMed abstracts.", _QueryArgs, gap_tools.pubmed_search),
        tool(
            "clinicaltrials_search",
            "Search ClinicalTrials.gov studies.",
            _QueryArgs,
            gap_tools.clinicaltrials_search,
        ),
        tool("fetch_page", "Fetch a public web page.", _UrlArgs, gap_tools.fetch_page),
    ]
    if ctx.web_search_enabled:
        tools.append(tool("web_search", "Search the web.", _QueryArgs, gap_tools.web_search))
    result = await llm.run_tools(
        instructions=instructions(ctx.web_search_enabled),
        input=build_agent_input(terms),
        tools=tools,
        final_schema=GapAgentOutput,
        kind="main",
        max_tool_calls=MAX_STEPS,
        deadline_s=TIMEOUT_S,
    )
    return _Outcome(result.output, _stop_reason(ctx, result.usage.total_tokens), "gateway")


async def run_agent(llm: LLMClient, terms: PublicTerms, ctx: ToolContext) -> _Outcome:
    try:
        async with asyncio.timeout(TIMEOUT_S):
            try:
                return await _run_agents_sdk(llm, terms, ctx)
            except _Fallback:
                log.info("gap search: Agents SDK request rejected; using the gateway tool loop")
                return await _run_gateway(llm, terms, ctx)
    except TimeoutError:
        return _Outcome(None, GapStopReason.timeout, "timeout")
    except _TokenBudget:
        return _Outcome(None, GapStopReason.max_tokens, "budget")
    except LLMError as exc:
        if exc.code == "timeout":
            return _Outcome(None, GapStopReason.timeout, "timeout")
        raise


# ---- job row ------------------------------------------------------------------------------------


async def _create_job(user_id: UUID, terms: PublicTerms) -> UUID:
    async with user_transaction(user_id) as db:
        job = JobRecord(
            user_id=user_id,
            kind=JobKind.gap_search.value,
            status=JobStatus.running.value,
            progress=0,
            result={
                "from_id": terms.source.id,
                "to_id": terms.target.id,
                "family": terms.family.value,
            },
        )
        db.add(job)
        await db.flush()
        return job.id


async def _finish_job(
    user_id: UUID, job_id: UUID, *, error: str | None, result: dict[str, Any]
) -> None:
    try:
        async with user_transaction(user_id) as db:
            current = await db.scalar(
                text("SELECT result FROM jobs WHERE id = :id"), {"id": job_id}
            )
            await db.execute(
                update(JobRecord)
                .where(JobRecord.id == job_id)
                .values(
                    status=(JobStatus.failed if error else JobStatus.succeeded).value,
                    progress=100,
                    error=error,
                    result={**(current or {}), **result},
                )
            )
    except Exception as exc:  # noqa: BLE001
        log.error("could not finish gap-search job: %s", type(exc).__name__)


# ---- stream -------------------------------------------------------------------------------------


_ERRORS: dict[str, tuple[ErrorCode, str]] = {
    "reauth_required": (ErrorCode.sign_in_required, "Please sign in with ChatGPT again."),
    "usage_limit_exceeded": (
        ErrorCode.rate_limited,
        "Your ChatGPT plan's usage limit was reached. Please try again later.",
    ),
    "usage_unavailable": (
        ErrorCode.upstream_error,
        "Your ChatGPT plan cannot be used for this right now.",
    ),
}


async def prepare(
    db: AsyncSession, request: GapSearchRequest, user: CurrentUser
) -> tuple[PublicTerms, LLMClient]:
    """Validate before streaming: 422 same node, 404 unknown node, 401 no usable sign-in."""
    terms = await load_terms(db, request)
    llm = await auth_service.llm_for_user(user.id)
    return terms, llm


def run(
    request: GapSearchRequest,
    user: CurrentUser,
    *,
    prepared: tuple[PublicTerms, LLMClient] | None = None,
) -> AsyncIterator[GapSearchEvent]:
    """Stream progress and pending_review candidate edges under hard budgets (90 s)."""

    async def _stream() -> AsyncIterator[GapSearchEvent]:
        if prepared is None:
            async with user_transaction(user.id) as db:
                terms, llm = await prepare(db, request, user)
        else:
            terms, llm = prepared
        started = time.monotonic()
        queue: asyncio.Queue[GapProgressEvent] = asyncio.Queue()

        def on_step(step: int, tool: str) -> None:
            queue.put_nowait(
                GapProgressEvent(
                    step=step,
                    tool=tool,
                    message=TOOL_MESSAGES.get(tool, "Working"),
                    elapsed_s=round(time.monotonic() - started, 2),
                )
            )

        ctx = ToolContext(settings=get_settings(), max_steps=MAX_STEPS, on_step=on_step)
        job_id = await _create_job(user.id, terms)
        yield GapSearchEvent(
            GapProgressEvent(step=0, tool=None, message="Starting the search", elapsed_s=0.0)
        )
        task = asyncio.create_task(run_agent(llm, terms, ctx))
        finished = False
        try:
            while not task.done():
                getter = asyncio.ensure_future(queue.get())
                await asyncio.wait({task, getter}, return_when=asyncio.FIRST_COMPLETED)
                if getter.done():
                    yield GapSearchEvent(getter.result())
                else:
                    getter.cancel()
            while not queue.empty():
                yield GapSearchEvent(queue.get_nowait())
            try:
                outcome = task.result()
            except LLMError as exc:
                code, message = _ERRORS.get(
                    exc.code, (ErrorCode.upstream_error, "The search failed. Please try again.")
                )
                await _finish_job(user.id, job_id, error=f"llm_{exc.code}", result={})
                finished = True
                yield GapSearchEvent(GapErrorEvent(code=code, message=message))
                return
            candidates = verify(outcome.output.candidates if outcome.output else [], terms, ctx)
            await _finish_job(
                user.id,
                job_id,
                error=None,
                result={
                    "stage": "done",
                    "candidates": [c.model_dump(mode="json") for c in candidates],
                    "candidate_count": len(candidates),
                    "stop_reason": outcome.stop_reason.value,
                    "steps": ctx.steps,
                },
            )
            finished = True
            for c in candidates:
                yield GapSearchEvent(GapCandidateEvent(candidate=c))
            yield GapSearchEvent(
                GapFinalEvent(
                    candidate_count=len(candidates),
                    stop_reason=outcome.stop_reason,
                    job_id=job_id,
                )
            )
        finally:
            if not task.done():
                task.cancel()
            if not finished:
                await asyncio.shield(_finish_job(user.id, job_id, error="cancelled", result={}))

    return _stream()
