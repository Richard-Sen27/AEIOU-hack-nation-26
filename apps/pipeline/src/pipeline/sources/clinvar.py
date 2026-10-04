"""ClinVar variant_summary, split while streaming (GRCh38 rows only) into three cached files:

- ``variant_summary.scope.tsv.gz``: every row of the focus genes (variant nodes come from it);
- ``variant_summary.plp.tsv.gz``: every pathogenic / likely pathogenic row of any gene (gene
  counts, mechanism inference, ClinVar-supported gene-disease links, copy-number spans);
- ``variant_summary.gene_counts.tsv``: per gene, distinct P/LP and VUS variants.
"""

import csv
import gzip
import hashlib
import logging
import zlib
from collections import defaultdict

from pipeline import bio
from pipeline.contracts import Scope, Source, raw_record, record_raw
from pipeline.http import stream
from pipeline.paths import RAW

log = logging.getLogger(__name__)

URL = "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz"
FILENAME = "variant_summary.scope.tsv.gz"
PLP_FILE = bio.CLINVAR_PLP_FILE
COUNTS_FILE = bio.CLINVAR_COUNTS_FILE
# Bump when the set of files written by one fetch changes.
LAYOUT = 2


def _gene_key(scope: Scope) -> str:
    return hashlib.sha1(",".join(sorted(scope.focus_gene_ids)).encode()).hexdigest()[:16]


def is_current(scope: Scope) -> bool:
    rec = raw_record("clinvar", FILENAME)
    return bool(
        rec
        and rec.get("gene_set") == _gene_key(scope)
        and rec.get("layout") == LAYOUT
        and all((RAW / "clinvar" / f).exists() for f in (FILENAME, PLP_FILE, COUNTS_FILE))
    )


class Splitter:
    """Routes variant_summary lines (header first) into the focus file, the P/LP file and the
    per-gene counts. Works on bytes so the 400 MB stream is never held in memory."""

    def __init__(self, focus_out, plp_out, ids: set[str], symbols: set[str]):
        self.focus_out, self.plp_out = focus_out, plp_out
        self.ids, self.symbols = ids, symbols
        self.header: list[str] | None = None
        self.total = self.kept = self.plp = 0
        self.seen: dict[str, set[int]] = {"plp": set(), "vus": set()}
        self.counts: dict[str, dict[str, int]] = defaultdict(lambda: {"plp": 0, "vus": 0})

    def gene(self, row: dict[str, str]) -> str | None:
        hid = row.get("HGNC_ID") or ""
        if hid.startswith("HGNC:"):
            return hid
        sym = row.get("GeneSymbol") or ""
        return bio.gene_lookup().get(sym.upper()) if sym and ";" not in sym else None

    def handle(self, line: bytes) -> None:
        if self.header is None:
            self.header = line.decode().lstrip("#").split("\t")
            self.focus_out.write(line + b"\n")
            self.plp_out.write(line + b"\n")
            return
        self.total += 1
        cols = line.decode("utf-8", "replace").split("\t")
        row = dict(zip(self.header, cols, strict=False))
        if row.get("Assembly") != "GRCh38":
            return
        if row.get("HGNC_ID") in self.ids or row.get("GeneSymbol") in self.symbols:
            self.focus_out.write(line + b"\n")
            self.kept += 1
        cls = bio.classify(row.get("ClinicalSignificance") or "")
        kind = (
            "plp"
            if cls in ("pathogenic", "likely_pathogenic")
            else ("vus" if cls == "uncertain_significance" else None)
        )
        if kind is None:
            return
        if kind == "plp":
            self.plp_out.write(line + b"\n")
            self.plp += 1
        vid = row.get("VariationID") or ""
        hid = self.gene(row)
        if hid and vid.isdigit():
            key = int(vid)
            if key not in self.seen[kind]:
                self.seen[kind].add(key)
                self.counts[hid][kind] += 1

    def write_counts(self, path) -> None:
        with path.open("w", newline="") as f:
            w = csv.writer(f, delimiter="\t")
            w.writerow(["hgnc_id", "plp", "vus"])
            for hid in sorted(self.counts):
                c = self.counts[hid]
                w.writerow([hid, c["plp"], c["vus"]])


async def fetch(scope: Scope | None) -> None:
    assert scope is not None
    dest = RAW / "clinvar" / FILENAME
    if is_current(scope):
        log.info("clinvar: cached files for this focus gene set")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    plp_dest = RAW / "clinvar" / PLP_FILE
    plp_tmp = plp_dest.with_suffix(".part")
    focus = scope.focus()
    decomp = zlib.decompressobj(16 + zlib.MAX_WBITS)
    buf = b""
    async with stream("clinvar", URL) as response:
        version = response.headers.get("last-modified")
        with gzip.open(tmp, "wb") as out, gzip.open(plp_tmp, "wb") as plp_out:
            split = Splitter(out, plp_out, focus.gene_ids, focus.gene_symbols)
            async for chunk in response.aiter_bytes(1 << 20):
                buf += decomp.decompress(chunk)
                *lines, buf = buf.split(b"\n")
                for line in lines:
                    if line:
                        split.handle(line)
            buf += decomp.flush()
            for line in buf.split(b"\n"):
                if line:
                    split.handle(line)
    tmp.replace(dest)
    plp_tmp.replace(plp_dest)
    split.write_counts(RAW / "clinvar" / COUNTS_FILE)
    common = {"source_version": version}
    record_raw(
        "clinvar",
        URL,
        plp_dest,
        **common,
        rows_kept=split.plp,
        note="pathogenic / likely pathogenic GRCh38 rows of every gene",
    )
    record_raw(
        "clinvar",
        URL,
        RAW / "clinvar" / COUNTS_FILE,
        **common,
        genes=len(split.counts),
        note="distinct P/LP and VUS VariationIDs per gene (GRCh38 rows)",
    )
    record_raw(
        "clinvar",
        URL,
        dest,
        **common,
        gene_set=_gene_key(scope),
        layout=LAYOUT,
        rows_total=split.total,
        rows_kept=split.kept,
        note="filtered while streaming to the focus genes, GRCh38",
    )
    log.info(
        "clinvar: %d rows; %d kept for %d focus genes; %d P/LP rows; counts for %d genes",
        split.total,
        split.kept,
        len(focus.gene_ids),
        split.plp,
        len(split.counts),
    )


def normalize(scope: Scope) -> None:
    bio.normalize_clinvar(scope)


SOURCE = Source("clinvar", "scoped", fetch, normalize)
