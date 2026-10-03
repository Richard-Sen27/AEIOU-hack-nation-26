"""Synthetic test documents and helpers for the document service tests."""

import io
import json

import pymupdf
from docx import Document as DocxDocument
from PIL import Image, ImageDraw, ImageFont

# Synthetic genetic report: fake name, date of birth, address and patient id.
FAKE_NAME = "Johanna Mustermann"
FAKE_DOB = "14.02.2019"
FAKE_ADDRESS = "42 Maple Street"
FAKE_ID = "99887766"
FAKE_FILENAME = "mustermann_report_secret.pdf"
VARIANT_LINE = "Gene: STXBP1 Variant: NM_003165.6:c.1631G>A Zygosity: heterozygous"

REPORT_LINES = [
    "Molecular Genetics Laboratory - Genetic Test Report",
    f"Patient: {FAKE_NAME}",
    f"DOB: {FAKE_DOB}",
    f"Address: {FAKE_ADDRESS}, Springfield, IL 62704",
    f"MRN: {FAKE_ID}",
    "Report date: 2026-03-14",
    VARIANT_LINE,
    "Classification: Uncertain significance (VUS)",
]
REPORT_TEXT = "\n".join(REPORT_LINES)
PII = (FAKE_NAME, "Mustermann", FAKE_DOB, FAKE_ADDRESS, FAKE_ID)


def text_pdf(lines: list[str] = REPORT_LINES, pages: int = 1) -> bytes:
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page()
        y = 72
        for line in lines:
            page.insert_text((50, y), line, fontsize=11)
            y += 18
    data = doc.tobytes()
    doc.close()
    return data


def text_image(lines: list[str], fmt: str = "PNG") -> bytes:
    font = ImageFont.load_default(size=36)
    img = Image.new("L", (2000, 80 + 60 * len(lines)), color=255)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((40, 40 + 60 * i), line, fill=0, font=font)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def scanned_pdf(lines: list[str]) -> bytes:
    png = text_image(lines)
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=60 + 30 * len(lines) + 40)
    page.insert_image(page.rect, stream=png)
    data = doc.tobytes()
    doc.close()
    return data


def docx_bytes(paragraphs: list[str], page_break_after: int | None = None) -> bytes:
    doc = DocxDocument()
    for i, p in enumerate(paragraphs):
        doc.add_paragraph(p)
        if page_break_after is not None and i == page_break_after:
            doc.add_page_break()
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def variant_extraction(**overrides) -> dict:
    item = {
        "gene": "STXBP1",
        "hgvs": "NM_003165.6:c.1631G>A",
        "zygosity": "heterozygous",
        "classification": "uncertain_significance",
        "test_date": "2026-03-14",
        "page": 1,
        "snippet": VARIANT_LINE,
    }
    item.update(overrides)
    return {"variants": [item]}


def model_inputs(mock) -> list[str]:
    """Everything sent to the model (instructions + input), one string per request."""
    return [json.dumps(r["body"]) for r in mock.state.recorded("responses")]


async def upload(user, data: bytes, filename: str = FAKE_FILENAME, ctype: str = "application/pdf"):
    return await user.client.post("/documents", files={"file": (filename, data, ctype)})


async def job_events(user, job_id) -> list[dict]:
    resp = await user.client.get(f"/jobs/{job_id}")
    assert resp.status_code == 200, resp.text
    events = []
    for block in resp.text.replace("\r\n", "\n").split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
    return events
