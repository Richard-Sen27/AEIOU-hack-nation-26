"""Local text extraction with page numbers. Nothing here leaves the server.

PyMuPDF for text PDFs, Tesseract OCR (CLI over stdin/stdout, so no temp files) for scanned pages
and photos, pillow-heif for HEIC, python-docx for DOCX.
"""

import asyncio
import io
import os
import shutil

import pymupdf
from docx import Document as DocxDocument
from docx.oxml.ns import qn
from PIL import Image, ImageOps, UnidentifiedImageError

from backend.api.services.documents.filetypes import FileKind

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:  # noqa: BLE001
    pillow_heif = None

Image.MAX_IMAGE_PIXELS = 60_000_000
OCR_DPI = 300
OCR_TIMEOUT_S = 90.0
MIN_TEXT_CHARS = 25
DOCX_CHARS_PER_PAGE = 3500


class ExtractionError(Exception):
    """`code` is a short, content-free error code stored on the job."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


# ---- page counting (upload checks) -----------------------------------------------------------


def count_pages(kind: FileKind, data: bytes) -> int:
    if kind is FileKind.pdf:
        with _open_pdf(data) as doc:
            return doc.page_count
    if kind is FileKind.docx:
        return len(_docx_pages(data))
    if kind is FileKind.text:
        return len(_text_pages(data))
    return 1


def _open_pdf(data: bytes) -> pymupdf.Document:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:  # noqa: BLE001
        raise ExtractionError("unreadable_document") from None
    if doc.needs_pass:
        doc.close()
        raise ExtractionError("encrypted_document")
    return doc


def _text_pages(data: bytes) -> list[str]:
    text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
    pages = text.split("\f")
    return pages if any(p.strip() for p in pages) else [text]


def _docx_pages(data: bytes) -> list[str]:
    try:
        doc = DocxDocument(io.BytesIO(data))
    except Exception:  # noqa: BLE001
        raise ExtractionError("unreadable_document") from None
    pages: list[list[str]] = [[]]
    for block in doc.element.body.iterchildren():
        if block.tag == qn("w:p"):
            if block.find(f"{qn('w:pPr')}/{qn('w:pageBreakBefore')}") is not None and pages[-1]:
                pages.append([])
            text_parts: list[str] = []
            for node in block.iter():
                if node.tag == qn("w:t") and node.text:
                    text_parts.append(node.text)
                elif node.tag == qn("w:tab"):
                    text_parts.append("\t")
                elif node.tag == qn("w:br") and node.get(qn("w:type")) == "page":
                    pages[-1].append("".join(text_parts))
                    text_parts = []
                    pages.append([])
            pages[-1].append("".join(text_parts))
        elif block.tag == qn("w:tbl"):
            for row in block.iter(qn("w:tr")):
                cells = []
                for cell in row.iter(qn("w:tc")):
                    cells.append(" ".join(t.text or "" for t in cell.iter(qn("w:t"))).strip())
                pages[-1].append(" | ".join(cells))
    texts = ["\n".join(lines) for lines in pages]
    # Documents without explicit breaks: split long text into pseudo pages.
    if len(texts) == 1 and len(texts[0]) > DOCX_CHARS_PER_PAGE:
        texts = _split_long(texts[0])
    return texts or [""]


def _split_long(text: str) -> list[str]:
    pages, current, size = [], [], 0
    for line in text.split("\n"):
        if size + len(line) > DOCX_CHARS_PER_PAGE and current:
            pages.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        pages.append("\n".join(current))
    return pages


# ---- OCR -------------------------------------------------------------------------------------


def tesseract_path() -> str | None:
    return os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")


async def ocr_png(png: bytes) -> str:
    """OCR one PNG image with the local Tesseract CLI (stdin -> stdout, no files)."""
    cmd = tesseract_path()
    if not cmd:
        raise ExtractionError("ocr_unavailable")
    proc = await asyncio.create_subprocess_exec(
        cmd,
        "stdin",
        "stdout",
        "-l",
        "eng",
        "--psm",
        "3",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env={**os.environ, "OMP_THREAD_LIMIT": "1"},
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(png), timeout=OCR_TIMEOUT_S)
    except (TimeoutError, asyncio.CancelledError):
        proc.kill()
        await proc.wait()
        raise
    if proc.returncode != 0:
        raise ExtractionError("ocr_failed")
    return out.decode("utf-8", errors="replace")


def _image_to_png(data: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            img = ImageOps.exif_transpose(img).convert("L")
            if max(img.size) > 5000:
                img.thumbnail((5000, 5000))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        raise ExtractionError("unreadable_document") from None


def _pdf_pages(data: bytes) -> list[tuple[str, bytes | None]]:
    """(text, png-to-OCR or None) per page."""
    out: list[tuple[str, bytes | None]] = []
    with _open_pdf(data) as doc:
        for page in doc:
            text = page.get_text("text") or ""
            if len(text.strip()) >= MIN_TEXT_CHARS:
                out.append((text, None))
                continue
            zoom = OCR_DPI / 72
            if max(page.rect.width, page.rect.height) * zoom > 5000:
                zoom = 5000 / max(page.rect.width, page.rect.height)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY)
            out.append((text, pix.tobytes("png")))
    return out


async def extract_pages(kind: FileKind, data: bytes) -> list[str]:
    """Plain text per page (index 0 = page 1)."""
    if kind is FileKind.text:
        return _text_pages(data)
    if kind is FileKind.docx:
        return await asyncio.to_thread(_docx_pages, data)
    if kind is FileKind.pdf:
        pages = await asyncio.to_thread(_pdf_pages, data)
        texts = []
        for text, png in pages:
            texts.append(await ocr_png(png) if png is not None else text)
        return texts
    if kind is FileKind.heic and pillow_heif is None:
        raise ExtractionError("unsupported_media_type")
    png = await asyncio.to_thread(_image_to_png, data)
    return [await ocr_png(png)]
