"""Local tool: extract text from a PDF file."""

from __future__ import annotations

import asyncio
import logging

from pypdf import PdfReader

from tool.decorator import mcp_tool

logger = logging.getLogger(__name__)


def _read_pdf_text(path: str) -> str:
    """Extract text from every page of a PDF. Runs in a worker thread -
    ``pypdf`` is synchronous and PDF parsing can be slow enough to block
    the event loop.
    """
    reader = PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


@mcp_tool(
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
    text = await asyncio.to_thread(_read_pdf_text, path)
    logger.debug("extract_pdf: path=%r extracted %d chars", path, len(text))
    return {"text": text}
