"""ClinGen: dosage sensitivity (haploinsufficiency) and gene-disease validity curations."""

from pipeline import bio
from pipeline.contracts import Scope, Source
from pipeline.http import download

DOSAGE_URL = "https://ftp.clinicalgenome.org/ClinGen_gene_curation_list_GRCh38.tsv"
VALIDITY_URL = "https://search.clinicalgenome.org/kb/gene-validity/download"


async def fetch(scope: Scope | None) -> None:
    await download("clingen", DOSAGE_URL, "ClinGen_gene_curation_list_GRCh38.tsv")
    await download("clingen", VALIDITY_URL, "gene_validity.csv")


def normalize(scope: Scope) -> None:
    bio.normalize_clingen(scope)


SOURCE = Source("clingen", "bulk", fetch, normalize)
