"""Reactome: gene (NCBI Gene id) -> lowest-level human pathway."""

from pipeline import bio
from pipeline.contracts import Scope, Source
from pipeline.http import download

BASE = "https://reactome.org/download/current/"


async def fetch(scope: Scope | None) -> None:
    await download("reactome", BASE + "NCBI2Reactome.txt", "NCBI2Reactome.txt")
    await download("reactome", BASE + "ReactomePathways.txt", "ReactomePathways.txt")
    await download(
        "reactome", BASE + "ReactomePathwaysRelation.txt", "ReactomePathwaysRelation.txt"
    )


def normalize(scope: Scope) -> None:
    bio.normalize_reactome(scope)


SOURCE = Source("reactome", "bulk", fetch, normalize)
