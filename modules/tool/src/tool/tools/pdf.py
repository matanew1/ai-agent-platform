"""Local tool: extract text from a PDF file."""

from __future__ import annotations

import asyncio
import logging

from pypdf import PdfReader

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
