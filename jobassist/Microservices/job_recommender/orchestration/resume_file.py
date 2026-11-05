"""Read a CV/resume file (PDF, Word .docx, or plain text) into plain text."""

from __future__ import annotations

import io
from pathlib import PurePath

import docx
from pypdf import PdfReader
from pypdf.errors import PdfReadError

SUPPORTED_SUFFIXES = (".pdf", ".docx", ".txt", ".md")


class ResumeReadError(ValueError):
    """The file could not be turned into CV text."""


def _pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except PdfReadError as exc:
        raise ResumeReadError(f"could not read the PDF: {exc}") from exc


def _docx_text(data: bytes) -> str:
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - python-docx raises several unrelated types
        raise ResumeReadError(f"could not read the Word document: {exc}") from exc
    lines = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            lines.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(lines)


def read_resume(filename: str, data: bytes) -> str:
    """Return the text of the CV in *data*; *filename* decides the format."""
    suffix = PurePath(filename).suffix.lower()
    if suffix == ".pdf":
        text = _pdf_text(data)
    elif suffix == ".docx":
        text = _docx_text(data)
    elif suffix in (".txt", ".md"):
        text = data.decode("utf-8", errors="replace")
    else:
        raise ResumeReadError(
            f"unsupported file type '{suffix or filename}' — use PDF, Word (.docx) or text"
        )
    text = text.strip()
    if not text:
        raise ResumeReadError(
            "no text found in the file (a scanned PDF needs to be saved as text first)"
        )
    return text
