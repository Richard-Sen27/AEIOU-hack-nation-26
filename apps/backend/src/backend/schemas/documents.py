from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from backend.schemas.common import ApiModel
from backend.schemas.enums import DocType, DocumentStatus, FindingType, JobKind, JobStatus


class Document(ApiModel):
    """Uploaded document metadata. The filename and raw bytes are never stored."""

    id: UUID
    status: DocumentStatus
    doc_type: DocType | None = Field(None, description="Classification, once known.")
    page_count: int | None = None
    created_at: datetime
    raw_deleted_at: datetime | None = Field(None, description="When the raw bytes were deleted.")


class Finding(ApiModel):
    id: UUID
    document_id: UUID
    type: FindingType
    value: str = Field(description="Extracted value as shown to the user (redacted).")
    normalized_id: str | None = Field(None, description="Resolved ID (MONDO, HGNC, HP, CLINVAR).")
    page: int | None = Field(None, description="1-based page number.")
    snippet: str | None = Field(None, description="Redacted source snippet to highlight.")
    confirmed: bool | None = Field(None, description="true confirmed, false rejected, null open.")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured details (variant: hgvs, zygosity, classification, test_date).",
    )
    vus_notice: str | None = Field(None, description="Set for uncertain_significance variants.")
    decided_at: datetime | None = None


class JobAccepted(ApiModel):
    job_id: UUID
    document_id: UUID


class Job(ApiModel):
    id: UUID
    kind: JobKind
    status: JobStatus
    progress: int = Field(0, ge=0, le=100, description="Percent complete.")
    document_id: UUID | None = None
    error: str | None = Field(None, description="Error code only, never content.")
    created_at: datetime
    result: dict[str, Any] | None = Field(
        None, description="Job result: stage and counts; gap search keeps its candidates here."
    )
