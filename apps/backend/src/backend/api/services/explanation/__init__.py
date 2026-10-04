"""Explanation: role-specific, cited path explanations, cached in explanations_cache."""

import json
import logging
import time
from collections.abc import AsyncIterator, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import not_found
from backend.api.services import auth as auth_service
from backend.api.services.explanation.common import chunk_text, llm_error, reading_grade
from backend.api.services.explanation.generator import (
    Explanation,
    ExplanationError,
    generate_explanation,
)
from backend.api.services.explanation.pathdata import PathData, cache_key, load_path_data
from backend.api.services.explanation.templates import template_explanation
from backend.db.session import user_transaction
from backend.llm import LLMClient, LLMError
from backend.observability import tracing
from backend.schemas.account import CurrentUser
from backend.schemas.common import Lens
from backend.schemas.enums import ErrorCode
from backend.schemas.events import (
    ExplainDeltaEvent,
    ExplainErrorEvent,
    ExplainEvent,
    ExplainFinalEvent,
)

__all__ = [
    "Explanation",
    "ExplanationError",
    "generate",
    "get_cached",
    "start_generation",
    "store_explanation",
    "template_explanation",
]

log = logging.getLogger(__name__)
UNVERSIONED = "unversioned"

_CACHED_SQL = text(
    "SELECT text, citations FROM explanations_cache WHERE path_id = :pid AND role = :role"
    " AND language = :lang AND data_version = :dv"
)
_UPSERT_SQL = text(
    "INSERT INTO explanations_cache (path_id, role, language, data_version, text, citations)"
    " VALUES (:pid, :role, :lang, :dv, :text, CAST(:citations AS jsonb))"
    " ON CONFLICT (path_id, role, language, data_version)"
    " DO UPDATE SET text = EXCLUDED.text, citations = EXCLUDED.citations, created_at = now()"
)


async def _data_version(db: AsyncSession) -> str:
    from backend.api.services.account import current_data_version

    return await current_data_version(db) or UNVERSIONED


async def get_cached(
    db: AsyncSession, edge_ids: Sequence[str], lens: Lens, *, subject_node_id: str | None = None
) -> ExplainFinalEvent | None:
    """Cached explanation for (cache_key, role, language, data_version), or None. The key is
    path_id(edge_ids), or for a subject summary path_id(["subject:<id>", *edge_ids])."""
    pid = cache_key(edge_ids, subject_node_id)
    dv = await _data_version(db)
    row = (
        (
            await db.execute(
                _CACHED_SQL,
                {"pid": pid, "role": lens.role.value, "lang": lens.language, "dv": dv},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    citations = row["citations"] if isinstance(row["citations"], list) else []
    return ExplainFinalEvent(
        path_id=pid,
        text=row["text"],
        citations=[str(c) for c in citations],
        cached=True,
        reading_grade=reading_grade(row["text"], lens.language),
        role=lens.role,
        language=lens.language,
        data_version=dv,
    )


async def store_explanation(
    db: AsyncSession, data: PathData, lens: Lens, explanation: Explanation
) -> None:
    await db.execute(
        _UPSERT_SQL,
        {
            "pid": data.path_id,
            "role": lens.role.value,
            "lang": lens.language,
            "dv": data.data_version or UNVERSIONED,
            "text": explanation.text,
            "citations": json.dumps(explanation.citations),
        },
    )


async def start_generation(
    edge_ids: Sequence[str],
    lens: Lens,
    user: CurrentUser,
    *,
    subject_node_id: str | None = None,
) -> AsyncIterator[ExplainEvent]:
    """Validate the request (404 unknown edges or subject, 401 no usable ChatGPT sign-in) and
    return the stream. Used by the route so request-level failures become HTTP errors."""
    async with user_transaction(user.id) as db:
        data = await load_path_data(db, edge_ids, subject_id=subject_node_id)
    if data.missing or not data.edges:
        raise not_found("Unknown edge IDs.")
    if subject_node_id and data.subject is None:
        raise not_found("Unknown subject node.")
    llm = await auth_service.llm_for_user(user.id)
    return _stream(data, lens, user, llm)


def generate(edge_ids: Sequence[str], lens: Lens, user: CurrentUser) -> AsyncIterator[ExplainEvent]:
    """Stream a new explanation (delta..., final) on the user's plan; validates and caches it."""

    async def _gen() -> AsyncIterator[ExplainEvent]:
        stream = await start_generation(edge_ids, lens, user)
        async for event in stream:
            yield event

    return _gen()


async def _stream(
    data: PathData, lens: Lens, user: CurrentUser, llm: LLMClient
) -> AsyncIterator[ExplainEvent]:
    started = time.monotonic()
    tracer = tracing.get_tracer()
    meta = {"path_id": data.path_id, "role": lens.role.value, "language": lens.language}
    with tracer.trace("explain.generate", user_id=str(user.id), metadata=meta) as span:
        try:
            result = await generate_explanation(llm, data, lens.role, lens.language)
        except LLMError as exc:
            code, message = llm_error(exc)
            span.update(level="ERROR", status_message=f"llm:{exc.code}")
            yield ExplainEvent(ExplainErrorEvent(code=code, message=message))
            return
        except ExplanationError:
            span.update(level="ERROR", status_message="invalid_citations")
            yield ExplainEvent(
                ExplainErrorEvent(
                    code=ErrorCode.upstream_error,
                    message="Dr. Wu could not produce a correctly cited explanation. "
                    "Please try again.",
                )
            )
            return
        async with user_transaction(user.id) as db:
            await store_explanation(db, data, lens, result)
        span.update(
            output={"citations": result.citations},
            metadata={
                **meta,
                "attempts": result.attempts,
                "reading_grade": result.reading_grade,
                "added_notes": len(result.added_notes),
                "latency_ms": round((time.monotonic() - started) * 1000),
            },
        )
    for chunk in chunk_text(result.text, words=6):
        yield ExplainEvent(ExplainDeltaEvent(text=chunk))
    yield ExplainEvent(
        ExplainFinalEvent(
            path_id=data.path_id,
            text=result.text,
            citations=result.citations,
            cached=False,
            reading_grade=result.reading_grade,
            role=lens.role,
            language=lens.language,
            data_version=data.data_version or UNVERSIONED,
        )
    )
