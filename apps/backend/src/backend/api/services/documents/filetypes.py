"""Upload type detection on content (never the file name or the client's content type).

Uses python-magic when libmagic is available, otherwise a strict built-in signature check.
Either way DOCX, HEIC and plain text get a structural check on top.
"""

import io
import zipfile
from enum import StrEnum


class FileKind(StrEnum):
    pdf = "pdf"
    png = "png"
    jpeg = "jpeg"
    heic = "heic"
    docx = "docx"
    text = "text"


_HEIC_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"hevm", b"hevs"}
_HEIF_GENERIC = {b"mif1", b"msf1"}

_MAGIC_MIME = {
    "application/pdf": FileKind.pdf,
    "image/png": FileKind.png,
    "image/jpeg": FileKind.jpeg,
    "image/heic": FileKind.heic,
    "image/heif": FileKind.heic,
    "image/heic-sequence": FileKind.heic,
    "image/heif-sequence": FileKind.heic,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": FileKind.docx,
    "application/zip": FileKind.docx,
    "text/plain": FileKind.text,
}

try:  # libmagic is a system library; missing on some dev machines
    import magic as _magic

    _magic.from_buffer(b"%PDF-1.4", mime=True)
except Exception:  # noqa: BLE001
    _magic = None


def magic_available() -> bool:
    return _magic is not None


def is_heic(head: bytes) -> bool:
    if len(head) < 16 or head[4:8] != b"ftyp":
        return False
    box_size = int.from_bytes(head[0:4], "big")
    major = head[8:12]
    if major in _HEIC_BRANDS:
        return True
    if major in _HEIF_GENERIC:
        end = min(box_size, len(head))
        compat = {head[i : i + 4] for i in range(16, end - 3, 4)}
        return bool(compat & _HEIC_BRANDS)
    return False


def is_docx(data: bytes) -> bool:
    if not data.startswith(b"PK\x03\x04"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                return False
            info = zf.getinfo("word/document.xml")
            return info.file_size < 200 * 1024 * 1024  # zip bomb guard
    except (zipfile.BadZipFile, KeyError, ValueError):
        return False


def is_text(data: bytes) -> bool:
    if not data or b"\x00" in data:
        return False
    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    printable = sum(1 for c in decoded if c.isprintable() or c in "\n\r\t\f")
    return printable / len(decoded) > 0.97


def _builtin(data: bytes) -> FileKind | None:
    if data.startswith(b"%PDF-"):
        return FileKind.pdf
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return FileKind.png
    if data.startswith(b"\xff\xd8\xff"):
        return FileKind.jpeg
    if is_heic(data[:64]):
        return FileKind.heic
    if is_docx(data):
        return FileKind.docx
    if is_text(data):
        return FileKind.text
    return None


def sniff(data: bytes) -> FileKind | None:
    """The allowed kind of `data`, or None when it is not an allowed type."""
    if _magic is None:
        return _builtin(data)
    try:
        mime = _magic.from_buffer(data[:8192], mime=True)
    except Exception:  # noqa: BLE001
        return _builtin(data)
    kind = _MAGIC_MIME.get(mime)
    if kind is None and mime.startswith("text/"):
        kind = FileKind.text
    if kind is None:
        # libmagic does not know every HEIF brand
        return FileKind.heic if is_heic(data[:64]) else None
    if kind is FileKind.docx and not is_docx(data):
        return None
    if kind is FileKind.text and not is_text(data):
        return None
    if kind is FileKind.pdf and not data.startswith(b"%PDF-"):
        return None
    return kind
