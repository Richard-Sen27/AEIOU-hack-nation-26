"""Calls: surveys, studies and trials looking for participants ("Find trials and studies looking
for participants").

A verified doctor or researcher with a visible public card writes a call; the Amber team reviews
its wording, ethics approval and registry number (not its science) and publishes it. Every
signed-in user sees every published call; nothing about who looked at one is stored. Calls never
offer, promise, price or promote a treatment: they describe research that looks for participants
and link to its registry entry.
"""

import re
import unicodedata
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, ConfigDict, Field, model_validator

from backend.schemas.common import ApiModel
from backend.schemas.people import PublicCard

MAX_TITLE = 140
MAX_SUMMARY = 1000
MAX_PARTICIPATION = 1000
MAX_ELIGIBILITY = 1500
MAX_LABEL = 200
MAX_ETHICS_REFERENCE = 100
MAX_URL = 500
MAX_DISEASES = 10
MAX_GENES = 20
MAX_PHENOTYPES = 30
MAX_COUNTRIES = 60
MAX_OPEN_CALLS = 10  # draft, pending review and published calls per publisher

MONDO_PATTERN = r"^MONDO:\d{7}$"
HGNC_PATTERN = r"^HGNC:\d{1,9}$"
HP_PATTERN = r"^HP:\d{7}$"
COUNTRY_PATTERN = r"^[A-Z]{2}$"
# ClinicalTrials.gov (NCT), German Clinical Trials Register (DRKS), EU CT number
# (2023-123456-12-00) and the older EudraCT number (2019-123456-12).
REGISTRY_PATTERN = r"^(NCT\d{8}|DRKS\d{8}|\d{4}-\d{6}-\d{2}(-\d{2})?)$"

REVIEW_BADGE = (
    "Reviewed by the Amber team for wording, ethics and registry numbers, not for scientific "
    "quality"
)
NOTICE = (
    "Ask your doctor whether this trial or study could apply to you. This is not an eligibility "
    "check: only the study team decides who can take part."
)
LIST_HEADING = "Find trials and studies looking for participants"


class CallKind(StrEnum):
    survey = "survey"
    study = "study"
    trial = "trial"


class CallStatus(StrEnum):
    draft = "draft"
    pending_review = "pending_review"
    published = "published"
    closed = "closed"
    withdrawn = "withdrawn"
    rejected = "rejected"


class RequestedField(StrEnum):
    """What a sign-up (connect stage 4) may offer to share, chosen from a fixed menu."""

    diagnosis = "diagnosis"
    genetic_findings = "genetic_findings"
    symptoms = "symptoms"
    age_range = "age_range"
    country = "country"


def _clean(value: str, *, multiline: bool) -> str:
    """NFC, no control characters (newlines only in long texts), trimmed."""
    value = unicodedata.normalize("NFC", value)
    allowed = {"\n"} if multiline else set()
    value = value.replace("\r\n", "\n").replace("\t", " ")
    if any(unicodedata.category(c) in ("Cc", "Zl", "Zp") and c not in allowed for c in value):
        raise ValueError("control characters are not allowed")
    if multiline:
        value = re.sub(r"\n{3,}", "\n\n", value)
        value = "\n".join(" ".join(line.split()) for line in value.split("\n"))
    else:
        value = " ".join(value.split())
    if not value.strip():
        raise ValueError("must not be empty")
    return value.strip()


def _line(value: str) -> str:
    return _clean(value, multiline=False)


def _text(value: str) -> str:
    return _clean(value, multiline=True)


def _https(value: str) -> str:
    value = value.strip()
    if any(unicodedata.category(c) in ("Cc", "Zs") for c in value):
        raise ValueError("no spaces or control characters")
    if not re.match(r"^https://[^/\s?#]+\.[^/\s?#]+", value, re.IGNORECASE):
        raise ValueError("an https link is required")
    return value


Line = Annotated[str, AfterValidator(_line)]
Text = Annotated[str, AfterValidator(_text)]


def _unique(values: list) -> list:
    return list(dict.fromkeys(values))


class CallInput(ApiModel):
    """A call as the publisher writes it (create or full replace). Atlas IDs must exist in the
    current atlas; a study or trial needs its ethics approval reference, a trial its registry ID
    (NCT, EU CT / EudraCT or DRKS)."""

    model_config = ConfigDict(extra="forbid")

    kind: CallKind
    title: Annotated[Line, Field(max_length=MAX_TITLE)]
    summary: Annotated[Text, Field(max_length=MAX_SUMMARY)] = Field(
        description="What the research is about and what it wants to find out."
    )
    participation: Annotated[Text, Field(max_length=MAX_PARTICIPATION)] = Field(
        description="What taking part involves (time, visits, remote, compensation for costs)."
    )
    eligibility_text: Annotated[Text, Field(max_length=MAX_ELIGIBILITY)] | None = Field(
        None, description="Who can take part, in the study team's words."
    )
    disease_ids: list[Annotated[str, Field(pattern=MONDO_PATTERN)]] = Field(
        min_length=1, max_length=MAX_DISEASES, description="Atlas diseases (MONDO IDs)."
    )
    gene_ids: list[Annotated[str, Field(pattern=HGNC_PATTERN)]] = Field(
        default_factory=list, max_length=MAX_GENES, description="Atlas genes (HGNC IDs)."
    )
    phenotype_ids: list[Annotated[str, Field(pattern=HP_PATTERN)]] = Field(
        default_factory=list, max_length=MAX_PHENOTYPES, description="Atlas symptoms (HP IDs)."
    )
    min_age: int | None = Field(None, ge=0, le=120, description="Shown as information.")
    max_age: int | None = Field(None, ge=0, le=120, description="Shown as information.")
    children_ok: bool = Field(False, description="Children can take part (with their parents).")
    countries: list[Annotated[str, Field(pattern=COUNTRY_PATTERN)]] = Field(
        default_factory=list,
        max_length=MAX_COUNTRIES,
        description="ISO 3166-1 alpha-2 codes where it runs; shown as information.",
    )
    remote: bool = Field(False, description="Can be done without visiting a site.")
    run_by_label: Annotated[Line, Field(max_length=MAX_LABEL)] | None = Field(
        None, description="Institution or team that runs it, as text."
    )
    run_by_node_id: Annotated[str, Field(max_length=100)] | None = Field(
        None, description="Atlas institution or patient organisation that runs it."
    )
    ethics_body: Annotated[Line, Field(max_length=MAX_LABEL)] | None = Field(
        None, description="Ethics committee that approved it."
    )
    ethics_reference: Annotated[Line, Field(max_length=MAX_ETHICS_REFERENCE)] | None = Field(
        None, description="Approval reference. Required for studies and trials."
    )
    registry_id: Annotated[str, Field(pattern=REGISTRY_PATTERN)] | None = Field(
        None, description="NCT, EU CT / EudraCT or DRKS number. Required for trials."
    )
    external_url: Annotated[str, Field(max_length=MAX_URL), AfterValidator(_https)] | None = Field(
        None, description="https link to the study's own page or registry entry."
    )
    opens_at: date | None = None
    closes_at: date | None = None
    max_signups: int | None = Field(None, ge=1, le=10000)
    requested_fields: list[RequestedField] = Field(
        default_factory=lambda: [RequestedField.diagnosis],
        max_length=len(RequestedField),
        description="What a sign-up may offer to share (fixed menu; used by sign-ups later).",
    )

    @model_validator(mode="after")
    def _dedupe(self) -> "CallInput":
        # Cross-field rules (ethics, registry, ages, dates) are checked by the service, so the
        # 422 can name the field.
        self.disease_ids = _unique(self.disease_ids)
        self.gene_ids = _unique(self.gene_ids)
        self.phenotype_ids = _unique(self.phenotype_ids)
        self.countries = _unique(self.countries)
        self.requested_fields = _unique(self.requested_fields)
        return self


class AtlasRef(ApiModel):
    id: str
    label: str | None = Field(description="From the current atlas; null if it left the atlas.")


class WordingIssue(ApiModel):
    """A phrase the wording check does not allow (offers, promises or prices of a treatment)."""

    field: str
    term: str = Field(description="The rule that matched, e.g. 'cure' or 'free medication'.")


class Call(ApiModel):
    """A published call as every signed-in user sees it."""

    id: UUID
    kind: CallKind
    title: str
    summary: str
    participation: str
    eligibility_text: str | None
    diseases: list[AtlasRef]
    genes: list[AtlasRef]
    phenotypes: list[AtlasRef]
    min_age: int | None
    max_age: int | None
    adults_only: bool = Field(description="min_age is 18 or more: show 'for adults'.")
    children_ok: bool
    countries: list[str]
    remote: bool
    run_by_label: str | None
    run_by_node: AtlasRef | None
    ethics_body: str | None
    ethics_reference: str | None
    registry_id: str | None
    registry_url: str | None = Field(description="Link to the public registry entry.")
    external_url: str | None
    opens_at: date | None
    closes_at: date | None
    max_signups: int | None
    requested_fields: list[RequestedField]
    publisher: PublicCard | None = Field(
        description="The publisher's public card ('run by [name], [institution]'). Always set "
        "on published calls in the list; null on the publisher's own view while their card is "
        "hidden."
    )
    published_at: datetime | None
    demo: bool = Field(description="Seeded demo data: label it 'Demo, not a real study'.")
    review_badge: str = Field(REVIEW_BADGE, description="Show on every published call.")
    notice: str = Field(NOTICE, description="Show on every call.")


class CallList(ApiModel):
    heading: str = LIST_HEADING
    items: list[Call] = Field(
        description="Every published call that is not past its closing date and whose publisher "
        "still has a visible, verified card; newest first."
    )


class OwnCall(Call):
    """The publisher's own call, in any status."""

    status: CallStatus
    review_note: str | None = Field(description="The reviewer's note (always set on rejection).")
    submitted_at: datetime | None
    reviewed_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    expired: bool = Field(description="Published but past its closing date: no longer listed.")
    editable: bool = Field(description="Draft, pending review or rejected: PUT is allowed.")
    wording_issues: list[WordingIssue] = Field(
        description="What the wording check would refuse on submit."
    )


class OwnCallList(ApiModel):
    items: list[OwnCall] = Field(description="Newest first.")
    can_publish: bool = Field(
        description="The user is a verified doctor or researcher with a visible card."
    )
    open_limit: int = Field(
        MAX_OPEN_CALLS, description="Most draft, pending and published calls at a time."
    )


class CallReviewExport(ApiModel):
    call_id: UUID
    action: str
    note: str | None
    created_at: datetime


class CallExport(ApiModel):
    id: UUID
    kind: str
    title: str
    summary: str
    participation: str
    eligibility_text: str | None = None
    disease_ids: list[str]
    gene_ids: list[str]
    phenotype_ids: list[str]
    min_age: int | None = None
    max_age: int | None = None
    children_ok: bool
    countries: list[str]
    remote: bool
    run_by_label: str | None = None
    run_by_node_id: str | None = None
    ethics_body: str | None = None
    ethics_reference: str | None = None
    registry_id: str | None = None
    external_url: str | None = None
    opens_at: date | None = None
    closes_at: date | None = None
    max_signups: int | None = None
    requested_fields: list[str]
    status: str
    review_note: str | None = None
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None
    published_at: datetime | None = None
    closed_at: datetime | None = None
    demo: bool
    created_at: datetime
    updated_at: datetime
