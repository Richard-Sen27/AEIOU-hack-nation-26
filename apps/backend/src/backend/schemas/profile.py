"""PatientProfile: the shared contract between chat, documents and graph search.

Only fields the compliance rules allow. No names, birth dates, addresses or patient IDs;
unknown fields are rejected.
"""

from datetime import date, datetime
from uuid import UUID

from pydantic import ConfigDict, Field, model_validator

from backend.schemas.common import ApiModel
from backend.schemas.enums import AgeRange, ProfileSource, VariantClassification, Zygosity


class ProfileItem(ApiModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    source: ProfileSource = Field(description="Where the item came from: chat, document, manual.")
    confirmed_at: datetime | None = Field(None, description="When the user confirmed it.")
    finding_id: UUID | None = Field(None, description="Document finding it came from, if any.")


class ProfileDisease(ProfileItem):
    id: str = Field(description="MONDO ID.")
    label: str


class ProfileGene(ProfileItem):
    id: str = Field(description="HGNC ID.")
    label: str = Field(description="Gene symbol.")


class ProfileVariant(ProfileItem):
    hgvs: str | None = Field(None, description="HGVS notation, e.g. NM_003165.6:c.1631G>A.")
    clinvar_id: str | None = Field(None, description="CLINVAR:<VariationID>, if resolved.")
    gene_id: str | None = Field(None, description="HGNC ID of the gene.")
    zygosity: Zygosity | None = None
    classification: VariantClassification | None = None
    test_date: date | None = Field(None, description="Date of the genetic test.")


class ProfilePhenotype(ProfileItem):
    id: str = Field(description="HPO ID.")
    label: str
    excluded: bool = Field(False, description="True for negations ('no feeding problems').")
    onset: str | None = Field(None, description="HPO onset term ID or short label.")


class PatientProfile(ApiModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    diseases: list[ProfileDisease] = Field(default_factory=list)
    genes: list[ProfileGene] = Field(default_factory=list)
    variants: list[ProfileVariant] = Field(default_factory=list)
    phenotypes: list[ProfilePhenotype] = Field(default_factory=list)
    age_years: int | None = Field(None, ge=0, le=120, description="Age in years (no birth date).")
    age_range: AgeRange | None = Field(None, description="Age range, alternative to age_years.")
    onset: str | None = Field(None, description="Disease onset: HPO onset term ID or label.")
    country: str | None = Field(
        None,
        pattern=r"^[A-Z]{2}$",
        description="Optional ISO 3166-1 alpha-2 country, only to find nearby groups.",
    )
    about_child: bool = Field(False, description="The profile describes a child.")
    parental_responsibility_confirmed: bool = Field(
        False, description="Required true when about_child is true."
    )
    updated_at: datetime | None = Field(None, description="Server-set last update time.")

    @model_validator(mode="after")
    def _child_needs_parental_responsibility(self) -> "PatientProfile":
        if self.about_child and not self.parental_responsibility_confirmed:
            raise ValueError("parental responsibility must be confirmed for a child's profile")
        return self
