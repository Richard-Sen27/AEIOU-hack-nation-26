from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, File, Request, UploadFile

from backend.api.deps import DB, HealthDataConsentUser, User
from backend.api.errors import responses
from backend.api.ratelimit import UPLOAD_LIMIT, admit_model_request, limiter
from backend.api.services import documents
from backend.api.sse import EventStream, sse_doc, sse_response
from backend.schemas.documents import Document, Finding, JobAccepted
from backend.schemas.events import JobEvent
from backend.schemas.profile import PatientProfile

router = APIRouter(tags=["documents"])


@router.post(
    "/documents",
    response_model=JobAccepted,
    status_code=202,
    responses=responses(401, 403, 413, 415, 422, 429, 501),
    operation_id="uploadDocument",
)
@limiter.limit(UPLOAD_LIMIT)
async def upload_document(
    request: Request,
    db: DB,
    background: BackgroundTasks,
    file: Annotated[
        UploadFile,
        File(description="PDF, PNG, JPEG, HEIC, DOCX or plain text; max 20 MB, 30 pages."),
    ],
    user: HealthDataConsentUser,
) -> JobAccepted:
    """Upload a document for extraction; returns the job to follow. Counts against the
    account's daily model budget (jobs queue, two at a time per process)."""
    ticket = await admit_model_request(request, user.id, slot=False)
    try:
        return await documents.accept_upload(db, user, file, background)
    except BaseException:
        ticket.cancel()
        raise


@router.get(
    "/documents",
    response_model=list[Document],
    responses=responses(401, 501),
    operation_id="listDocuments",
)
async def list_documents(db: DB, user: User) -> list[Document]:
    """The user's documents."""
    return await documents.list_documents(db, user)


@router.get(
    "/documents/{document_id}/findings",
    response_model=list[Finding],
    responses=responses(401, 404, 501),
    operation_id="listFindings",
)
async def list_findings(document_id: UUID, db: DB, user: User) -> list[Finding]:
    """Findings with page and snippet."""
    return await documents.list_findings(db, user, document_id)


@router.delete(
    "/documents/{document_id}",
    status_code=204,
    responses=responses(401, 404, 501),
    operation_id="deleteDocument",
)
async def delete_document(document_id: UUID, db: DB, user: User) -> None:
    """Delete a document and its findings."""
    await documents.delete_document(db, user, document_id)


@router.post(
    "/findings/{finding_id}/confirm",
    response_model=PatientProfile,
    responses=responses(401, 403, 404, 501),
    operation_id="confirmFinding",
)
async def confirm_finding(finding_id: UUID, db: DB, user: HealthDataConsentUser) -> PatientProfile:
    """Confirm a finding; returns the updated profile."""
    return await documents.confirm_finding(db, user, finding_id)


@router.post(
    "/findings/{finding_id}/reject",
    response_model=PatientProfile,
    responses=responses(401, 403, 404, 501),
    operation_id="rejectFinding",
)
async def reject_finding(finding_id: UUID, db: DB, user: HealthDataConsentUser) -> PatientProfile:
    """Reject a finding; returns the updated profile."""
    return await documents.reject_finding(db, user, finding_id)


@router.get(
    "/jobs/{job_id}",
    response_class=EventStream,
    responses={
        **sse_doc(JobEvent, "Stream of JobEvent (progress..., done | error)."),
        **responses(401, 404, 501),
    },
    operation_id="streamJob",
)
async def stream_job(job_id: UUID, db: DB, user: User) -> EventStream:
    """Job progress."""
    await documents.get_job(db, user, job_id)
    return sse_response(documents.job_events(job_id, user))
