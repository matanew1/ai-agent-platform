"""Extract plain text from supported document formats."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from docx import Document
from pypdf import PdfReader


def extract_document_text(filename: str, content: bytes) -> str:
    """Extract text from a TXT, PDF, or DOCX document."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".txt":
        return content.decode("utf-8")
    if suffix == ".pdf":
        return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages)
    if suffix == ".docx":
        return "\n".join(paragraph.text for paragraph in Document(BytesIO(content)).paragraphs)
    raise ValueError(f"Unsupported document type: {suffix or 'no extension'}")
