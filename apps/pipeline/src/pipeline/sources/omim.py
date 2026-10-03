"""OMIM genemap2 (optional): skipped unless OMIM_API_KEY is set."""

import logging

from pipeline import bio
from pipeline.config import settings
from pipeline.contracts import Scope, Source, raw_record, record_raw
from pipeline.http import stream
from pipeline.paths import RAW

log = logging.getLogger(__name__)

URL = "https://data.omim.org/downloads/{key}/genemap2.txt"


async def fetch(scope: Scope | None) -> None:
    if not settings.omim_api_key:
        log.info("omim: OMIM_API_KEY not set; skipping (optional source)")
        return
    dest = RAW / "omim" / "genemap2.txt"
    if dest.exists() and raw_record("omim", "genemap2.txt"):
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    async with stream("omim", URL.format(key=settings.omim_api_key)) as response:
        with dest.open("wb") as f:
            async for chunk in response.aiter_bytes(1 << 20):
                f.write(chunk)
    # The key is part of the URL; never write it into the metadata.
    record_raw("omim", URL.format(key="<OMIM_API_KEY>"), dest, None)


def normalize(scope: Scope) -> None:
    bio.normalize_omim(scope)


SOURCE = Source("omim", "bulk", fetch, normalize)
