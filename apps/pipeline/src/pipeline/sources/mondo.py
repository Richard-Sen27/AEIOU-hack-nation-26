"""MONDO: disease ids, labels, synonyms, cross-references (OMIM/Orphanet -> MONDO)."""

from pipeline import bio
from pipeline.contracts import Scope, Source
from pipeline.http import download

URL = "https://purl.obolibrary.org/obo/mondo.json"


async def fetch(scope: Scope | None) -> None:
    await download("mondo", URL, "mondo.json")


def normalize(scope: Scope) -> None:
    bio.normalize_mondo(scope)


SOURCE = Source("mondo", "bulk", fetch, normalize)
