"""Gene Ontology: human gene -> biological process annotations (GOA)."""

from pipeline import bio
from pipeline.contracts import Scope, Source
from pipeline.http import download

GAF_URL = "https://current.geneontology.org/annotations/goa_human.gaf.gz"
OBO_URL = "https://purl.obolibrary.org/obo/go/go-basic.obo"


async def fetch(scope: Scope | None) -> None:
    await download("go", GAF_URL, "goa_human.gaf.gz")
    await download("go", OBO_URL, "go-basic.obo")


def normalize(scope: Scope) -> None:
    bio.normalize_go(scope)


SOURCE = Source("go", "bulk", fetch, normalize)
