from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, RootModel

from backend.schemas.common import ApiModel
from backend.schemas.enums import (
    AssetType,
    ContributionKind,
    ContributionStatus,
    EdgeStatus,
    FlagStatus,
    Origin,
    Relation,
)


class PhenotypeProfilePayload(ApiModel):
    model_config = ConfigDict(extra="forbid")

    disease_id: str = Field(description="MONDO ID of the disease.")
    phenotype_ids: list[str] = Field(description="HPO IDs present.")
    excluded_phenotype_ids: list[str] = Field(default_factory=list, description="HPO IDs absent.")
    age_range: str | None = Field(None, description="Optional age range (no birth date).")


class AssetPayload(ApiModel):
    model_config = ConfigDict(extra="forbid")

    asset_type: AssetType
    name: str = Field(max_length=200)
    url: str | None = Field(None, max_length=500)
    description: str | None = Field(None, max_length=2000)
    disease_ids: list[str] = Field(default_factory=list, description="MONDO IDs it relates to.")


class CandidateEdgePayload(ApiModel):
    """A candidate edge from a researcher's paper or a gap-search result (public sources only)."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(max_length=80, description="Graph node ID (MONDO:, HGNC:, HP:, ...).")
    target_id: str = Field(max_length=80, description="Graph node ID.")
    relation: Relation
    source_url: str | None = Field(None, max_length=500, description="Public source URL.")
    source_id_ref: str | None = Field(
        None, max_length=40, description="Public source identifier (PMID:..., NCT...)."
    )
    quote: str | None = Field(None, max_length=500, description="Supporting span from the source.")


class PhenotypeProfileContributionCreate(ApiModel):
    kind: Literal[ContributionKind.phenotype_profile]
    payload: PhenotypeProfilePayload


class AssetContributionCreate(ApiModel):
    kind: Literal[ContributionKind.asset]
    payload: AssetPayload


class CandidateEdgeContributionCreate(ApiModel):
    kind: Literal[ContributionKind.candidate_edge]
    payload: CandidateEdgePayload


class ContributionCreate(
    RootModel[
        Annotated[
            PhenotypeProfileContributionCreate
            | AssetContributionCreate
            | CandidateEdgeContributionCreate,
            Field(discriminator="kind"),
        ]
    ]
):
    """A user contribution; needs an active 'contribute' consent."""


class Contribution(ApiModel):
    id: UUID
    kind: ContributionKind
    payload: dict[str, Any]
    status: ContributionStatus
    origin: Origin = Field(
        Origin.patient_reported,
        description="patient_reported, or user_contributed for candidate edges.",
    )
    consent_id: UUID | None = None
    created_at: datetime


class SharedContribution(ApiModel):
    """A contribution visible to everyone (active consent), without user identity."""

    id: UUID
    kind: ContributionKind
    payload: dict[str, Any]
    status: ContributionStatus
    origin: Origin = Field(
        Origin.patient_reported,
        description="patient_reported, or user_contributed for candidate edges.",
    )
    created_at: datetime


class FlagCreate(ApiModel):
    reason: str = Field(min_length=1, max_length=500, description="Why the edge looks wrong.")


class FlagResult(ApiModel):
    edge_id: str
    status: EdgeStatus = Field(description="under_review once flagged.")
    open_flags: int


class EdgeFlag(ApiModel):
    id: UUID
    edge_id: str
    reason: str
    status: FlagStatus
    created_at: datetime
