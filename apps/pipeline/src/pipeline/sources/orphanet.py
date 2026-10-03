"""Orphanet open scientific data (Orphadata, CC BY 4.0): genes, phenotypes, epidemiology."""

from pipeline import bio
from pipeline.contracts import Scope, Source
from pipeline.http import download

BASE = "https://www.orphadata.com/data/xml/"
FILES = {
    "en_product1.xml": "nomenclature",
    "en_product4.xml": "phenotypes (HPO)",
    "en_product6.xml": "gene associations",
    "en_product9_prev.xml": "epidemiology (prevalence)",
}
LICENSE = "CC BY 4.0, Orphanet: an online rare disease and orphan drug data base. INSERM. www.orpha.net"


async def fetch(scope: Scope | None) -> None:
    for name, content in FILES.items():
        await download("orphanet", BASE + name, name, license=LICENSE, content=content)


def normalize(scope: Scope) -> None:
    bio.normalize_orphanet(scope)


SOURCE = Source("orphanet", "bulk", fetch, normalize)
