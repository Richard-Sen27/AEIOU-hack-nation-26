"""HGNC: the complete approved gene set with aliases and previous symbols."""

from pipeline import bio
from pipeline.contracts import Scope, Source
from pipeline.http import download

URL = "https://storage.googleapis.com/public-download-files/hgnc/tsv/tsv/hgnc_complete_set.txt"


async def fetch(scope: Scope | None) -> None:
    await download("hgnc", URL, "hgnc_complete_set.txt")


def normalize(scope: Scope) -> None:
    bio.normalize_hgnc(scope)


SOURCE = Source("hgnc", "bulk", fetch, normalize)
