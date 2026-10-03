"""ClinVar variant_summary, filtered to the in-scope genes while streaming (GRCh38 rows only)."""

import gzip
import hashlib
import logging
import zlib

from pipeline import bio
from pipeline.contracts import Scope, Source, raw_record, record_raw
from pipeline.http import stream
from pipeline.paths import RAW

log = logging.getLogger(__name__)

URL = "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz"
FILENAME = "variant_summary.scope.tsv.gz"


def _gene_key(scope: Scope) -> str:
    return hashlib.sha1(",".join(sorted(scope.gene_ids)).encode()).hexdigest()[:16]


async def fetch(scope: Scope | None) -> None:
    assert scope is not None
    dest = RAW / "clinvar" / FILENAME
    key = _gene_key(scope)
    rec = raw_record("clinvar", FILENAME)
    if dest.exists() and rec and rec.get("gene_set") == key:
        log.info("clinvar: cached filtered file for this gene set")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    ids, symbols = scope.gene_ids, scope.gene_symbols
    kept = total = 0
    header: list[str] | None = None
    decomp = zlib.decompressobj(16 + zlib.MAX_WBITS)
    buf = b""
    async with stream("clinvar", URL) as response:
        version = response.headers.get("last-modified")
        with gzip.open(tmp, "wb") as out:

            def handle(line: bytes) -> None:
                nonlocal header, kept, total
                if header is None:
                    header = line.decode().lstrip("#").split("\t")
                    out.write(line + b"\n")
                    return
                total += 1
                cols = line.decode("utf-8", "replace").split("\t")
                row = dict(zip(header, cols, strict=False))
                if row.get("Assembly") != "GRCh38":
                    return
                if row.get("HGNC_ID") in ids or row.get("GeneSymbol") in symbols:
                    out.write(line + b"\n")
                    kept += 1

            async for chunk in response.aiter_bytes(1 << 20):
                buf += decomp.decompress(chunk)
                *lines, buf = buf.split(b"\n")
                for line in lines:
                    if line:
                        handle(line)
            buf += decomp.flush()
            for line in buf.split(b"\n"):
                if line:
                    handle(line)
    tmp.replace(dest)
    record_raw(
        "clinvar",
        URL,
        dest,
        version,
        gene_set=key,
        rows_total=total,
        rows_kept=kept,
        note="filtered while streaming to in-scope genes, GRCh38",
    )
    log.info("clinvar: kept %d of %d rows", kept, total)


def normalize(scope: Scope) -> None:
    bio.normalize_clinvar(scope)


SOURCE = Source("clinvar", "scoped", fetch, normalize)
