"""Documents: upload -> extract -> redact -> classify -> structured findings -> review.

Raw bytes live only in memory for the life of the job (Starlette may spool a large upload to
an anonymous temporary file, which it closes and so deletes after the request); the filename is
never stored; nothing raw is written to the database or logs; the model only sees redacted text.
"""

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import BackgroundTasks, UploadFile
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.errors import ApiError
from backend.api.services import account as account_service
from backend.api.services import auth as auth_service
from backend.api.services import contributions as contributions_service
from backend.api.services import search as search_service
from backend.api.services.documents import analysis
from backend.api.services.documents.extract import ExtractionError, count_pages, extract_pages
from backend.api.services.documents.filetypes import sniff
from backend.api.services.documents.profile_merge import profile_item
from backend.db.models import DocumentRecord, FindingRecord, JobRecord
from backend.db.session import user_transaction
from backend.llm import LLMError
from backend.privacy.redaction import redact
from backend.schemas.account import CurrentUser
from backend.schemas.contributions import (
    CandidateEdgeContributionCreate,
    CandidateEdgePayload,
    ContributionCreate,
)
from backend.schemas.documents import Document, Finding, Job, JobAccepted
from backend.schemas.enums import (
    VUS_NOTICE,
    DocType,
    DocumentStatus,
    ErrorCode,
    FindingType,
    JobKind,
    JobStage,
    JobStatus,
    NodeType,
    VariantClassification,
)
from backend.schemas.events import JobDoneEvent, JobErrorEvent, JobEvent, JobProgressEvent
from backend.schemas.profile import PatientProfile

log = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_PAGES = 30
PROCESS_TIMEOUT_S = 600.0
JOB_POLL_S = 0.5
JOB_STREAM_MAX_S = 900.0
MAX_CONCURRENT_JOBS = 2

_job_slots = asyncio.Semaphore(MAX_CONCURRENT_JOBS)

# Job error code (stored on the job row; never content) -> (API error code, fixed message).
JOB_ERRORS: dict[str, tuple[ErrorCode, str]] = {
    "unsupported_media_type": (
        ErrorCode.unsupported_media_type,
        "This file type is not supported.",
    ),
    "unreadable_document": (ErrorCode.unsupported_media_type, "The document could not be read."),
    "encrypted_document": (
        ErrorCode.unsupported_media_type,
        "The document is password-protected.",
    ),
    "too_many_pages": (ErrorCode.payload_too_large, "The document has more than 30 pages."),
    "no_text_found": (ErrorCode.bad_request, "No readable text was found in the document."),
    "ocr_unavailable": (ErrorCode.internal_error, "Text recognition is not available."),
    "ocr_failed": (ErrorCode.internal_error, "Text recognition failed."),
    "sign_in_required": (ErrorCode.sign_in_required, "Sign in with ChatGPT to use this feature."),
    "llm_reauth_required": (ErrorCode.sign_in_required, "Please sign in with ChatGPT again."),
    "llm_usage_limit_exceeded": (
        ErrorCode.rate_limited,
        "Your ChatGPT plan's usage limit was reached. Please try again later.",
    ),
    "llm_usage_unavailable": (
        ErrorCode.upstream_error,
        "Your ChatGPT plan cannot be used for this right now.",
    ),
    "llm_timeout": (ErrorCode.upstream_error, "The model took too long to respond."),
    "llm_bad_output": (ErrorCode.upstream_error, "The model returned an unusable answer."),
    "llm_upstream": (ErrorCode.upstream_error, "An upstream service failed. Please try again."),
    "timeout": (ErrorCode.upstream_error, "Processing took too long."),
    "cancelled": (ErrorCode.internal_error, "Processing was interrupted."),
    "internal_error": (ErrorCode.internal_error, "Something went wrong."),
}

_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]{1,200})")
_PMID_RE = re.compile(r"\bPMID:?\s*(\d{1,9})\b")


def _now() -> datetime:
    return datetime.now(UTC)


# ---- upload -------------------------------------------------------------------------------------


async def _read_limited(file: UploadFile) -> bytes:
    chunks, size = [], 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise ApiError(413, ErrorCode.payload_too_large, "The upload is larger than 20 MB.")
        chunks.append(chunk)
    return b"".join(chunks)


async def accept_upload(
    db: AsyncSession, user: CurrentUser, file: UploadFile, background: BackgroundTasks
) -> JobAccepted:
    """Check size and type, create document + job rows, schedule process_document.

    Raw bytes stay in memory only; the filename is not stored.
    """
    if not user.age_confirmed:  # require_user enforces this too
        raise ApiError(
            403,
            ErrorCode.age_confirmation_required,
            "Confirm that you are 16 or older to use this feature.",
        )
    try:
        data = await _read_limited(file)
    finally:
        await file.close()
    kind = sniff(data) if data else None
    if kind is None:
        raise ApiError(415, ErrorCode.unsupported_media_type)
    try:
        pages = await asyncio.to_thread(count_pages, kind, data)
    except ExtractionError as exc:
        _, message = JOB_ERRORS.get(exc.code, JOB_ERRORS["unreadable_document"])
        raise ApiError(415, ErrorCode.unsupported_media_type, message) from None
    if pages > MAX_PAGES:
        raise ApiError(413, ErrorCode.payload_too_large, "The document has more than 30 pages.")

    doc = DocumentRecord(user_id=user.id, status=DocumentStatus.queued.value, page_count=pages)
    db.add(doc)
    await db.flush()
    job = JobRecord(
        user_id=user.id,
        kind=JobKind.document_extraction.value,
        status=JobStatus.queued.value,
        progress=0,
        result={"stage": JobStage.queued.value},
        document_id=doc.id,
    )
    db.add(job)
    await db.flush()
    background.add_task(process_document, job.id, doc.id, user.id, data)
    return JobAccepted(job_id=job.id, document_id=doc.id)


# ---- background job -----------------------------------------------------------------------------


class _Gone(Exception):
    """The document was deleted (or consent revoked) while processing."""


async def _progress(
    job_id: UUID, document_id: UUID, user_id: UUID, stage: JobStage, percent: int, **doc: Any
) -> None:
    async with user_transaction(user_id) as db:
        found = await db.scalar(
            update(JobRecord)
            .where(JobRecord.id == job_id)
            .values(
                status=JobStatus.running.value,
                progress=percent,
                result={"stage": stage.value},
                updated_at=_now(),
            )
            .returning(JobRecord.id)
        )
        if found is None:
            raise _Gone
        await db.execute(
            update(DocumentRecord)
            .where(DocumentRecord.id == document_id)
            .values(status=DocumentStatus.processing.value, updated_at=_now(), **doc)
        )


async def _redact_pages(pages: list[str]) -> list[str]:
    return [(await asyncio.to_thread(redact, p)).text if p.strip() else p for p in pages]


async def process_document(job_id: UUID, document_id: UUID, user_id: UUID, data: bytes) -> None:
    """Background job; uses user_transaction(user_id) and sets raw_deleted_at when done."""
    holder = [data]
    del data
    error: str | None = None
    result: dict[str, Any] = {}
    try:
        async with asyncio.timeout(PROCESS_TIMEOUT_S), _job_slots:
            result = await _run_job(job_id, document_id, user_id, holder)
    except _Gone:
        return
    except ExtractionError as exc:
        error = exc.code if exc.code in JOB_ERRORS else "unreadable_document"
    except ApiError as exc:
        error = "sign_in_required" if exc.code is ErrorCode.sign_in_required else "internal_error"
    except LLMError as exc:
        error = f"llm_{exc.code}"
    except TimeoutError:
        error = "timeout"
    except asyncio.CancelledError:
        error = "cancelled"
        raise
    except Exception as exc:  # noqa: BLE001
        log.error("document job failed: %s", type(exc).__name__)
        error = "internal_error"
    finally:
        holder.clear()  # drop the last reference to the raw bytes
        await asyncio.shield(_finish(job_id, document_id, user_id, error, result))


async def _run_job(
    job_id: UUID, document_id: UUID, user_id: UUID, holder: list[bytes]
) -> dict[str, Any]:
    await _progress(job_id, document_id, user_id, JobStage.extracting_text, 5)
    kind = sniff(holder[0])
    if kind is None:
        raise ExtractionError("unsupported_media_type")
    pages = await extract_pages(kind, holder[0])
    holder.clear()
    if len(pages) > MAX_PAGES:
        raise ExtractionError("too_many_pages")
    if not any(len(p.strip()) >= 3 for p in pages):
        raise ExtractionError("no_text_found")

    await _progress(job_id, document_id, user_id, JobStage.redacting, 30, page_count=len(pages))
    redacted = await _redact_pages(pages)
    del pages

    llm = await auth_service.llm_for_user(user_id)
    await _progress(job_id, document_id, user_id, JobStage.classifying, 45)
    doc_type = await analysis.classify(llm, redacted)
    await _progress(
        job_id, document_id, user_id, JobStage.extracting_findings, 60, doc_type=doc_type.value
    )
    drafts = await analysis.extract(llm, doc_type, redacted)
    source_ref = _paper_ref(redacted) if doc_type is DocType.research_paper else None

    async with user_transaction(user_id) as db:
        drafts = await _resolve(db, drafts)
        exists = await db.scalar(
            select(DocumentRecord.id).where(DocumentRecord.id == document_id).with_for_update()
        )
        if exists is None:
            raise _Gone
        for d in drafts:
            if d.type is FindingType.candidate_edge and source_ref:
                d.payload["source_id_ref"] = source_ref
            db.add(
                FindingRecord(
                    document_id=document_id,
                    user_id=user_id,
                    type=d.type.value,
                    value=d.value,
                    normalized_id=d.normalized_id,
                    page=d.page,
                    snippet=d.snippet,
                    payload=d.payload,
                )
            )
    return {"finding_count": len(drafts), "doc_type": doc_type.value}


async def _finish(
    job_id: UUID, document_id: UUID, user_id: UUID, error: str | None, result: dict[str, Any]
) -> None:
    now = _now()
    try:
        async with user_transaction(user_id) as db:
            await db.execute(
                update(DocumentRecord)
                .where(DocumentRecord.id == document_id)
                .values(
                    status=(DocumentStatus.failed if error else DocumentStatus.ready).value,
                    raw_deleted_at=now,
                    updated_at=now,
                )
            )
            await db.execute(
                update(JobRecord)
                .where(JobRecord.id == job_id)
                .values(
                    status=(JobStatus.failed if error else JobStatus.succeeded).value,
                    progress=100 if not error else JobRecord.progress,
                    error=error,
                    result=(
                        {"stage": JobStage.done.value, **result}
                        if not error
                        else {"stage": JobStage.done.value}
                    ),
                    updated_at=now,
                )
            )
    except Exception as exc:  # noqa: BLE001
        log.error("could not finish document job: %s", type(exc).__name__)


def _paper_ref(pages: list[str]) -> str | None:
    head = "\n".join(pages[:2])
    if m := _DOI_RE.search(head):
        return "DOI:" + m.group(1).rstrip(".,;)")
    if m := _PMID_RE.search(head):
        return f"PMID:{m.group(1)}"
    return None


# ---- id resolution (search service) -------------------------------------------------------------


async def _search(db: AsyncSession, q: str, types: list[NodeType] | None):
    try:
        async with db.begin_nested():
            resp = await search_service.search(db, q, types=types, limit=5)
    except NotImplementedError:
        return []
    except Exception as exc:  # noqa: BLE001
        log.warning("finding resolution failed: %s", type(exc).__name__)
        return []
    return list(resp.results)


def _same(a: str | None, b: str) -> bool:
    return bool(a) and analysis.norm(a) == analysis.norm(b)


async def _resolve(db: AsyncSession, drafts: list[analysis.FindingDraft]):
    """Map genes -> HGNC, diseases -> MONDO, symptoms -> HPO, variants -> ClinVar.

    Unresolved genes, diseases and symptoms are dropped (a profile item needs a graph id);
    variants are kept with whatever resolved.
    """
    out: list[analysis.FindingDraft] = []
    gene_ids: dict[str, str] = {}
    for d in drafts:
        if d.type is FindingType.gene:
            results = await _search(db, d.lookup or d.value, [NodeType.gene])
            hit = next(
                (
                    r
                    for r in results
                    if _same(r.label, d.value) or _same(r.matched_synonym, d.value)
                ),
                None,
            )
            if hit is None:
                continue
            d.normalized_id = hit.id
            d.payload["label"] = hit.label
            gene_ids[analysis.norm(d.value)] = hit.id
        elif d.type in (FindingType.disease, FindingType.phenotype):
            ntype = NodeType.disease if d.type is FindingType.disease else NodeType.phenotype
            results = await _search(db, d.lookup or d.value, [ntype])
            if not results:
                continue
            d.normalized_id = results[0].id
            d.payload["label"] = results[0].label
            d.payload["matched_synonym"] = results[0].matched_synonym
        elif d.type is FindingType.variant:
            results = await _search(db, d.payload["hgvs"], [NodeType.variant])
            hgvs = d.payload["hgvs"].replace(" ", "")
            hit = next(
                (
                    r
                    for r in results
                    if hgvs in (r.label or "").replace(" ", "")
                    or hgvs in (r.matched_synonym or "").replace(" ", "")
                ),
                None,
            )
            if hit is not None:
                d.normalized_id = hit.id
                d.payload["clinvar_id"] = hit.id
        elif d.type is FindingType.candidate_edge:
            subj = await _search(db, d.payload["subject"], None)
            obj = await _search(db, d.payload["object"], None)
            if not subj or not obj or subj[0].id == obj[0].id:
                continue
            d.payload |= {
                "source_id": subj[0].id,
                "source_label": subj[0].label,
                "target_id": obj[0].id,
                "target_label": obj[0].label,
                "origin": "user_contributed",
                "status": "pending_review",
            }
        out.append(d)
    for d in out:
        if d.type is FindingType.variant:
            d.payload["gene_id"] = gene_ids.get(analysis.norm(d.payload["gene"]))
    return out


# ---- reads --------------------------------------------------------------------------------------


def finding_out(rec: FindingRecord) -> Finding:
    payload = dict(rec.payload or {})
    vus = (
        rec.type == FindingType.variant.value
        and payload.get("classification") == VariantClassification.uncertain_significance.value
    )
    return Finding(
        id=rec.id,
        document_id=rec.document_id,
        type=FindingType(rec.type),
        value=rec.value,
        normalized_id=rec.normalized_id,
        page=rec.page,
        snippet=rec.snippet,
        confirmed=rec.confirmed,
        payload=payload,
        vus_notice=VUS_NOTICE if vus else None,
        decided_at=rec.decided_at,
    )


async def list_documents(db: AsyncSession, user: CurrentUser) -> list[Document]:
    """The user's documents, newest first."""
    rows = await db.scalars(
        select(DocumentRecord)
        .where(DocumentRecord.user_id == user.id)
        .order_by(DocumentRecord.created_at.desc(), DocumentRecord.id)
    )
    return [Document.model_validate(r) for r in rows]


async def _own_document(db: AsyncSession, user: CurrentUser, document_id: UUID) -> DocumentRecord:
    doc = await db.scalar(
        select(DocumentRecord).where(
            DocumentRecord.id == document_id, DocumentRecord.user_id == user.id
        )
    )
    if doc is None:
        raise ApiError(404, ErrorCode.not_found)
    return doc


async def list_findings(db: AsyncSession, user: CurrentUser, document_id: UUID) -> list[Finding]:
    """Findings of one document with page and snippet; 404 if not the user's."""
    await _own_document(db, user, document_id)
    rows = await db.scalars(
        select(FindingRecord)
        .where(FindingRecord.document_id == document_id)
        .order_by(FindingRecord.page.nulls_last(), FindingRecord.created_at, FindingRecord.id)
    )
    return [finding_out(r) for r in rows]


async def get_job(db: AsyncSession, user: CurrentUser, job_id: UUID) -> Job:
    rec = await db.scalar(
        select(JobRecord).where(JobRecord.id == job_id, JobRecord.user_id == user.id)
    )
    if rec is None:
        raise ApiError(404, ErrorCode.not_found)
    return Job(
        id=rec.id,
        kind=JobKind(rec.kind),
        status=JobStatus(rec.status),
        progress=rec.progress,
        document_id=rec.document_id,
        error=rec.error,
        created_at=rec.created_at,
        result=rec.result,
    )


# ---- review -------------------------------------------------------------------------------------


async def _own_finding(db: AsyncSession, user: CurrentUser, finding_id: UUID) -> FindingRecord:
    rec = await db.scalar(
        select(FindingRecord)
        .where(FindingRecord.id == finding_id, FindingRecord.user_id == user.id)
        .with_for_update()
    )
    if rec is None:
        raise ApiError(404, ErrorCode.not_found)
    return rec


async def _active_contribute_consent(db: AsyncSession, user: CurrentUser) -> bool:
    return bool(
        await db.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM consents WHERE user_id = :uid"
                " AND consent_type = 'contribute' AND revoked_at IS NULL)"
            ),
            {"uid": user.id},
        )
    )


async def _contribute_edge(db: AsyncSession, user: CurrentUser, rec: FindingRecord) -> None:
    """A confirmed candidate edge enters the shared graph only as a consented contribution."""
    p = dict(rec.payload or {})
    if p.get("contribution_id") or not p.get("source_id_ref"):
        return
    if not await _active_contribute_consent(db, user):
        return
    body = ContributionCreate(
        CandidateEdgeContributionCreate(
            kind="candidate_edge",
            payload=CandidateEdgePayload(
                source_id=p["source_id"],
                target_id=p["target_id"],
                relation=p["relation"],
                source_id_ref=p["source_id_ref"],
                quote=(p.get("quote") or "")[:500] or None,
            ),
        )
    )
    try:
        async with db.begin_nested():
            contribution = await contributions_service.create(db, user, body)
    except ApiError:
        return  # failed screening or validation: stays a private finding
    rec.payload = {**p, "contribution_id": str(contribution.id)}


async def _withdraw_contributions(
    db: AsyncSession, user: CurrentUser, recs: list[FindingRecord]
) -> None:
    for rec in recs:
        cid = (rec.payload or {}).get("contribution_id")
        if not cid:
            continue
        try:
            async with db.begin_nested():
                await contributions_service.delete(db, user, UUID(cid))
        except ApiError:
            pass
        rec.payload = {k: v for k, v in (rec.payload or {}).items() if k != "contribution_id"}


async def confirm_finding(db: AsyncSession, user: CurrentUser, finding_id: UUID) -> PatientProfile:
    """Mark a finding confirmed and merge it into the PatientProfile."""
    rec = await _own_finding(db, user, finding_id)
    if rec.confirmed is not True:
        rec.confirmed = True
        rec.decided_at = _now()
    if rec.type == FindingType.candidate_edge.value:
        await _contribute_edge(db, user, rec)
        await db.flush()
        return await account_service.get_profile(db, user)
    await db.flush()
    current = await account_service.get_profile(db, user)
    if any(
        i.finding_id == rec.id
        for name in ("diseases", "genes", "variants", "phenotypes")
        for i in getattr(current, name)
    ):
        return current
    item = profile_item(rec)
    if item is None:
        return current
    return await account_service.merge_profile_items(db, user.id, [item])


async def reject_finding(db: AsyncSession, user: CurrentUser, finding_id: UUID) -> PatientProfile:
    """Mark a finding rejected (and remove it from the profile if it was merged)."""
    rec = await _own_finding(db, user, finding_id)
    if rec.confirmed is not False:
        rec.confirmed = False
        rec.decided_at = _now()
    await _withdraw_contributions(db, user, [rec])
    await db.flush()
    profile = await account_service.remove_profile_items(db, user.id, finding_ids=[rec.id])
    return profile if profile is not None else await account_service.get_profile(db, user)


async def delete_document(db: AsyncSession, user: CurrentUser, document_id: UUID) -> None:
    """Delete a document and its findings (and profile items that came from them)."""
    await _own_document(db, user, document_id)
    recs = list(
        await db.scalars(select(FindingRecord).where(FindingRecord.document_id == document_id))
    )
    if recs:
        await _withdraw_contributions(db, user, recs)
        await account_service.remove_profile_items(db, user.id, finding_ids=[r.id for r in recs])
    await db.execute(delete(DocumentRecord).where(DocumentRecord.id == document_id))


# ---- job stream ---------------------------------------------------------------------------------


def job_error_event(job_id: UUID, code: str | None) -> JobEvent:
    api_code, message = JOB_ERRORS.get(code or "", JOB_ERRORS["internal_error"])
    return JobEvent(JobErrorEvent(job_id=job_id, code=api_code, message=message))


def job_events(job_id: UUID, user: CurrentUser) -> AsyncIterator[JobEvent]:
    """Stream progress/done/error for one of the user's jobs (poll with user_transaction)."""

    async def _stream() -> AsyncIterator[JobEvent]:
        last: tuple | None = None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + JOB_STREAM_MAX_S
        while True:
            async with user_transaction(user.id) as db:
                rec = await db.scalar(
                    select(JobRecord).where(JobRecord.id == job_id, JobRecord.user_id == user.id)
                )
                if rec is None:
                    raise ApiError(404, ErrorCode.not_found)
                status, progress, error = rec.status, rec.progress, rec.error
                result = dict(rec.result or {})
                document_id = rec.document_id
            stage = JobStage(result.get("stage", JobStage.queued.value))
            if status == JobStatus.failed.value:
                yield job_error_event(job_id, error)
                return
            key = (stage, progress)
            if key != last and status != JobStatus.succeeded.value:
                last = key
                yield JobEvent(
                    JobProgressEvent(job_id=job_id, stage=stage, percent=min(progress, 100))
                )
            if status == JobStatus.succeeded.value:
                yield JobEvent(JobProgressEvent(job_id=job_id, stage=JobStage.done, percent=100))
                yield JobEvent(
                    JobDoneEvent(
                        job_id=job_id,
                        document_id=document_id,
                        finding_count=int(
                            result.get("finding_count", result.get("candidate_count", 0)) or 0
                        ),
                    )
                )
                return
            if loop.time() > deadline:
                raise ApiError(502, ErrorCode.upstream_error)
            await asyncio.sleep(JOB_POLL_S)

    return _stream()
