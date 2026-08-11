"""Local tools for extracting, generating, and safely extending PDF files."""

from __future__ import annotations

import asyncio
import logging
import textwrap
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from shared.artifacts import resolve_artifact_source, store_artifact_bytes
from shared.types import ToolDefinition

logger = logging.getLogger(__name__)

DEFINITION = ToolDefinition(
    name="extract_pdf",
    description="Extract the text content of a PDF file at a given filesystem path.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the PDF file."},
        },
        "required": ["path"],
    },
)

GENERATE_DEFINITION = ToolDefinition(
    name="generate_pdf",
    description=(
        "Create a downloadable PDF artifact containing the supplied plain text. Use this when "
        "the user asks to generate, create, export, or download a PDF. Returns its filename, "
        "download URL, and page count."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Optional output filename only, such as profile.pdf; directory components "
                    "are discarded. Defaults to document.pdf."
                ),
            },
            "text": {"type": "string", "description": "Plain text to place in the PDF."},
        },
        "required": ["text"],
    },
)

EDIT_DEFINITION = ToolDefinition(
    name="edit_pdf",
    description=(
        "Create a downloadable edited copy of a PDF by appending supplied plain text as new "
        "page(s). The source may be an /artifacts/<filename> download URL, an artifact filename, "
        "or a readable absolute PDF path. The source is never modified. Returns the new filename, "
        "download URL, and page count."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Existing PDF as an /artifacts/<filename> URL, safe artifact filename, or "
                    "readable absolute PDF path."
                ),
            },
            "text": {"type": "string", "description": "Plain text to append as new page(s)."},
            "output_path": {
                "type": "string",
                "description": (
                    "Optional output filename only. Defaults to <source>-edited.pdf; directory "
                    "components are discarded."
                ),
            },
        },
        "required": ["path", "text"],
    },
)

_PAGE_WIDTH = 612
_PAGE_HEIGHT = 792
_LINES_PER_PAGE = 48
_TEXT_WIDTH = 88


def _escape_pdf_text(text: str) -> str:
    """Encode plain text safely for the PDF's built-in Helvetica font."""
    return (
        text.encode("latin-1", errors="replace")
        .decode("latin-1")
        .replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def _text_pages(text: str) -> list[list[str]]:
    """Wrap text into fixed-width lines and split them into printable pages."""
    lines = [
        line
        for paragraph in text.splitlines()
        for line in textwrap.wrap(paragraph, _TEXT_WIDTH) or [""]
    ]
    return [
        lines[index : index + _LINES_PER_PAGE]
        for index in range(0, len(lines) or 1, _LINES_PER_PAGE)
    ] or [[""]]


def _build_text_pdf(text: str) -> bytes:
    """Build a small, dependency-free PDF containing plain text pages."""
    pages = _text_pages(text)
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    page_ids = [4 + index * 2 for index in range(len(pages))]
    page_references = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects.append(f"<< /Type /Pages /Kids [{page_references}] /Count {len(pages)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for page_id, lines in zip(page_ids, pages, strict=True):
        commands = ["BT", "/F1 12 Tf", "72 720 Td", "14 TL"]
        for index, line in enumerate(lines):
            if index:
                commands.append("T*")
            commands.append(f"({_escape_pdf_text(line)}) Tj")
        commands.append("ET")
        stream = "\n".join(commands).encode("latin-1")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_PAGE_WIDTH} {_PAGE_HEIGHT}] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {page_id + 1} 0 R >>".encode()
        )
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")

    result = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(result))
        result.extend(f"{index} 0 obj\n".encode())
        result.extend(obj)
        result.extend(b"\nendobj\n")
    xref_offset = len(result)
    result.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    result.extend(b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:]))
    trailer = (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n"
    )
    result.extend(trailer.encode())
    return bytes(result)


async def extract_pdf(path: str) -> dict[str, str]:
    """Extract text from a PDF file.

    Args:
        path: Filesystem path to the PDF.

    Returns:
        A dict with the extracted ``text``.

    Raises:
        FileNotFoundError: If ``path`` doesn't exist.
        PdfReadError: If ``path`` isn't a valid PDF (from ``pypdf``).
    """
    logger.debug("extract_pdf: path=%r", path)
    text = await asyncio.to_thread(
        lambda: "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    )
    logger.debug("extract_pdf: path=%r extracted %d chars", path, len(text))
    return {"text": text}


async def generate_pdf(text: str, path: str | None = None) -> dict[str, str | int]:
    """Generate a downloadable PDF in the configured artifact directory."""
    logger.debug("generate_pdf: requested_filename=%r text_len=%d", path, len(text))
    pages = len(_text_pages(text))
    artifact = await asyncio.to_thread(
        store_artifact_bytes,
        _build_text_pdf(text),
        requested_filename=path,
        default_stem="document",
        extension=".pdf",
    )
    return {
        "filename": artifact.filename,
        "download_url": artifact.download_url,
        "pages": pages,
    }


def _build_edited_pdf(path: Path, text: str) -> tuple[bytes, int]:
    """Copy a PDF and append generated text pages in memory."""
    writer = PdfWriter()
    writer.append(PdfReader(path))
    generated = PdfReader(BytesIO(_build_text_pdf(text)))
    writer.append(generated)
    output = BytesIO()
    writer.write(output)
    return output.getvalue(), len(writer.pages)


async def edit_pdf(
    path: str,
    text: str,
    output_path: str | None = None,
) -> dict[str, str | int]:
    """Append text pages and store a downloadable copy without changing the source."""
    logger.debug("edit_pdf: path=%r output_path=%r text_len=%d", path, output_path, len(text))
    source = await asyncio.to_thread(resolve_artifact_source, path, extension=".pdf")
    content, pages = await asyncio.to_thread(_build_edited_pdf, source, text)
    artifact = await asyncio.to_thread(
        store_artifact_bytes,
        content,
        requested_filename=output_path,
        default_stem=f"{source.stem}-edited",
        extension=".pdf",
    )
    return {
        "filename": artifact.filename,
        "download_url": artifact.download_url,
        "pages": pages,
    }
