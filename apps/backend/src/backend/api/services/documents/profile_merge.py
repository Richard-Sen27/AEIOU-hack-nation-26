"""Confirmed finding -> PatientProfile item (source=document, with the finding id).

The merge itself is account.merge_profile_items (locked read-modify-write under RLS).
"""

from datetime import UTC, date, datetime

from backend.db.models import FindingRecord
from backend.schemas.enums import FindingType, ProfileSource, VariantClassification, Zygosity
from backend.schemas.profile import ProfileDisease, ProfileGene, ProfilePhenotype, ProfileVariant

ProfileItem = ProfileDisease | ProfileGene | ProfilePhenotype | ProfileVariant


def profile_item(finding: FindingRecord) -> ProfileItem | None:
    """None for findings that do not belong in the profile (candidate edges, unresolved ids)."""
    common = {
        "source": ProfileSource.document,
        "confirmed_at": datetime.now(UTC),
        "finding_id": finding.id,
    }
    p = finding.payload or {}
    ftype = FindingType(finding.type)
    label = p.get("label") or finding.value
    if ftype is FindingType.gene and finding.normalized_id:
        return ProfileGene(id=finding.normalized_id, label=p.get("symbol") or label, **common)
    if ftype is FindingType.disease and finding.normalized_id:
        return ProfileDisease(id=finding.normalized_id, label=label, **common)
    if ftype is FindingType.phenotype and finding.normalized_id:
        return ProfilePhenotype(
            id=finding.normalized_id, label=label, excluded=bool(p.get("excluded")), **common
        )
    if ftype is FindingType.variant:
        return ProfileVariant(
            hgvs=p.get("hgvs"),
            clinvar_id=p.get("clinvar_id"),
            gene_id=p.get("gene_id"),
            zygosity=Zygosity(p["zygosity"]) if p.get("zygosity") else None,
            classification=(
                VariantClassification(p["classification"]) if p.get("classification") else None
            ),
            test_date=date.fromisoformat(p["test_date"]) if p.get("test_date") else None,
            **common,
        )
    return None
