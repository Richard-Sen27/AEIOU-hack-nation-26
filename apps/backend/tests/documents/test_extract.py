import pytest
from docfiles import docx_bytes, scanned_pdf, text_image, text_pdf

from backend.api.services.documents.extract import (
    ExtractionError,
    count_pages,
    extract_pages,
    tesseract_path,
)
from backend.api.services.documents.filetypes import FileKind

needs_tesseract = pytest.mark.skipif(not tesseract_path(), reason="tesseract not installed")
OCR_LINES = ["Gene STXBP1 heterozygous", "Seizures since infancy"]


async def test_text_pdf_keeps_pages():
    data = text_pdf(["first page text STXBP1"], pages=3)
    pages = await extract_pages(FileKind.pdf, data)
    assert len(pages) == 3
    assert all("STXBP1" in p for p in pages)
    assert count_pages(FileKind.pdf, data) == 3


@needs_tesseract
async def test_scanned_pdf_uses_ocr():
    pages = await extract_pages(FileKind.pdf, scanned_pdf(OCR_LINES))
    assert len(pages) == 1
    assert "STXBP1" in pages[0]
    assert "Seizures" in pages[0]


@needs_tesseract
@pytest.mark.parametrize("fmt,kind", [("PNG", FileKind.png), ("JPEG", FileKind.jpeg)])
async def test_photo_ocr(fmt, kind):
    pages = await extract_pages(kind, text_image(OCR_LINES, fmt))
    assert "STXBP1" in pages[0]


async def test_docx_page_breaks():
    data = docx_bytes(["Page one STXBP1", "still page one", "Page two text"], page_break_after=1)
    pages = await extract_pages(FileKind.docx, data)
    assert len(pages) == 2
    assert "STXBP1" in pages[0] and "Page two" in pages[1]
    assert count_pages(FileKind.docx, data) == 2


async def test_plain_text_form_feed_pages():
    pages = await extract_pages(FileKind.text, b"one\fthree STXBP1")
    assert pages == ["one", "three STXBP1"]


async def test_broken_pdf_raises_code():
    with pytest.raises(ExtractionError) as exc:
        count_pages(FileKind.pdf, b"%PDF-1.4 garbage")
    assert exc.value.code == "unreadable_document"


async def test_no_temp_files_written(monkeypatch):
    import tempfile

    def _boom(*a, **k):
        raise AssertionError("temporary file created")

    for name in ("mkstemp", "NamedTemporaryFile", "TemporaryFile", "mkdtemp"):
        monkeypatch.setattr(tempfile, name, _boom)
    await extract_pages(FileKind.pdf, text_pdf())
    await extract_pages(FileKind.docx, docx_bytes(["x"]))
    if tesseract_path():
        await extract_pages(FileKind.png, text_image(OCR_LINES))
