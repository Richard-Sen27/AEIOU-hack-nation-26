"""NCBI / EMBL-EBI MANE Select summary: GRCh38 gene coordinates (chromosome, start, end, strand).

Public data from the MANE project (NCBI RefSeq and EMBL-EBI Ensembl/GENCODE). The coordinates go
onto the gene nodes in the HGNC normalizer; this source writes no tables of its own.
"""

from pipeline.contracts import Scope, Source, write_tables
from pipeline.http import download

RELEASE = "1.5"
FILENAME = f"MANE.GRCh38.v{RELEASE}.summary.txt.gz"
URL = f"https://ftp.ncbi.nlm.nih.gov/refseq/MANE/MANE_human/release_{RELEASE}/{FILENAME}"
LICENSE = "Public data, MANE project (NCBI RefSeq and EMBL-EBI Ensembl/GENCODE)"


async def fetch(scope: Scope | None) -> None:
    await download(
        "mane",
        URL,
        FILENAME,
        source_version=f"MANE v{RELEASE}",
        license=LICENSE,
        content="MANE Select transcript summary (GRCh38 gene coordinates)",
    )


def normalize(scope: Scope) -> None:
    # Coordinates are gene attributes, merged in bio.normalize_hgnc; keep an empty table set so
    # Stage 4 sees the source as normalized.
    write_tables("mane", [], [], [])


SOURCE = Source("mane", "bulk", fetch, normalize)
