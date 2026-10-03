"""HPO: the phenotype ontology plus disease and gene annotations."""

from pipeline import bio
from pipeline.contracts import Scope, Source
from pipeline.http import download

BASE = "https://github.com/obophenotype/human-phenotype-ontology/releases/latest/download/"
FILES = ["hp.json", "hp.obo", "phenotype.hpoa", "genes_to_phenotype.txt"]


def _release(response) -> str | None:
    # .../releases/download/v2026-08-11/hp.json
    parts = str(response.url).split("/")
    return parts[-2] if "download" in parts else None


async def fetch(scope: Scope | None) -> None:
    for name in FILES:
        await download("hpo", BASE + name, name, source_version=_release)


def normalize(scope: Scope) -> None:
    bio.normalize_hpo(scope)


SOURCE = Source("hpo", "bulk", fetch, normalize)
