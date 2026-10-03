import pytest
from docfiles import docx_bytes, text_image, text_pdf, upload

from backend.api.ratelimit import limiter
from backend.api.services.documents import MAX_UPLOAD_BYTES, filetypes
from backend.api.services.documents.filetypes import FileKind, sniff

HEIC_HEADER = (
    b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 40
)  # ftyp box, major brand heic
HEIF_MIF1_HEADER = b"\x00\x00\x00\x1cftypmif1\x00\x00\x00\x00mif1miafheic" + b"\x00" * 40
AVIF_HEADER = b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00avifmif1miaf" + b"\x00" * 40


@pytest.mark.parametrize("use_magic", [False, True])
def test_sniff_allowed_types(monkeypatch, use_magic):
    if use_magic and not filetypes.magic_available():
        pytest.skip("libmagic not installed")
    if not use_magic:
        monkeypatch.setattr(filetypes, "_magic", None)
    assert sniff(text_pdf()) is FileKind.pdf
    assert sniff(text_image(["hello"], "PNG")) is FileKind.png
    assert sniff(text_image(["hello"], "JPEG")) is FileKind.jpeg
    assert sniff(docx_bytes(["hello"])) is FileKind.docx
    assert sniff(b"Plain text report\nGene: STXBP1\n") is FileKind.text
    assert sniff(HEIC_HEADER) is FileKind.heic
    assert sniff(HEIF_MIF1_HEADER) is FileKind.heic


@pytest.mark.parametrize(
    "data",
    [
        b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 100,  # Windows executable
        b"GIF89a" + b"\x00" * 50,
        b"PK\x03\x04" + b"\x00" * 50,  # zip that is not a DOCX
        AVIF_HEADER,
        b"\x00\x01\x02binary\xff\xfe",
        b"",
    ],
)
def test_sniff_rejects(monkeypatch, data):
    monkeypatch.setattr(filetypes, "_magic", None)
    assert sniff(data) is None


def test_file_name_and_content_type_are_ignored(monkeypatch):
    monkeypatch.setattr(filetypes, "_magic", None)
    # An executable renamed to .pdf stays rejected; a PDF named .txt is a PDF.
    assert sniff(b"MZ\x90\x00" + b"\x00" * 100) is None
    assert sniff(text_pdf()) is FileKind.pdf


async def test_guest_gets_401(client):
    resp = await client.post("/documents", files={"file": ("a.pdf", text_pdf(), "application/pdf")})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "sign_in_required"


async def test_no_consent_gets_403(make_user):
    user = await make_user(consents=[])
    resp = await upload(user, text_pdf())
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "consent_required"


async def test_age_not_confirmed_gets_403(make_user):
    user = await make_user(consents=["health_data"], age_confirmed=False)
    resp = await upload(user, text_pdf())
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "age_confirmation_required"


async def test_wrong_type_rejected(make_user):
    user = await make_user(consents=["health_data"])
    resp = await upload(user, b"GIF89a" + b"\x00" * 200, "report.pdf", "application/pdf")
    assert resp.status_code == 415
    assert resp.json()["error"]["code"] == "unsupported_media_type"


async def test_oversize_rejected(make_user):
    user = await make_user(consents=["health_data"])
    data = b"%PDF-1.4\n" + b"0" * (MAX_UPLOAD_BYTES + 10)
    resp = await upload(user, data)
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "payload_too_large"


async def test_too_many_pages_rejected(make_user):
    user = await make_user(consents=["health_data"])
    resp = await upload(user, text_pdf(["page"], pages=31))
    assert resp.status_code == 413
    assert "30 pages" in resp.json()["error"]["message"]


async def test_rate_limit_ten_per_hour(make_user):
    limiter.reset()
    user = await make_user(consents=["health_data"])
    bad = b"GIF89a" + b"\x00" * 50  # rejected quickly, still counts against the limit
    codes = [(await upload(user, bad)).status_code for _ in range(11)]
    assert codes[:10] == [415] * 10
    assert codes[10] == 429
    other = await make_user(consents=["health_data"])
    assert (await upload(other, bad)).status_code == 415
    limiter.reset()
