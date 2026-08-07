"""Local tool: extract plain text from a Markdown file."""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from shared.types import ToolDefinition

logger = logging.getLogger(__name__)

# Deliberately regex-based rather than a Markdown-parsing dependency - this
# only needs to strip the common syntax, not render Markdown correctly for
# every edge case. See `.claude/rules/architecture.md` on avoiding
# unnecessary abstraction/dependencies.
_CODE_FENCE = re.compile(r"```.*?\n(.*?)```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`]+)`")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HEADER = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_EMPHASIS = re.compile(r"(\*\*\*|\*\*|\*|___|__|_)(.+?)\1")
_BLOCKQUOTE = re.compile(r"^>\s?", re.MULTILINE)
_HORIZONTAL_RULE = re.compile(r"^([-*_])\1{2,}\s*$", re.MULTILINE)
_BLANK_LINES = re.compile(r"\n{3,}")

DEFINITION = ToolDefinition(
    name="extract_markdown",
    description="Extract plain text content from a Markdown file at a given filesystem path.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the Markdown file."},
        },
        "required": ["path"],
    },
)


def _strip_markdown(text: str) -> str:
    """Strip common Markdown syntax, leaving the readable text behind."""
    text = _CODE_FENCE.sub(lambda m: m.group(1), text)
    text = _INLINE_CODE.sub(lambda m: m.group(1), text)
    text = _IMAGE.sub(lambda m: m.group(1), text)
    text = _LINK.sub(lambda m: m.group(1), text)
    text = _HEADER.sub("", text)
    text = _EMPHASIS.sub(lambda m: m.group(2), text)
    text = _BLOCKQUOTE.sub("", text)
    text = _HORIZONTAL_RULE.sub("", text)
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip()


async def extract_markdown(path: str) -> dict[str, str]:
    """Extract plain text from a Markdown file.

    Args:
        path: Filesystem path to the Markdown file.

    Returns:
        A dict with the extracted ``text`` (Markdown syntax stripped).

    Raises:
        FileNotFoundError: If ``path`` doesn't exist.
    """
    logger.debug("extract_markdown: path=%r", path)
    raw = await asyncio.to_thread(Path(path).read_text)
    text = _strip_markdown(raw)
    logger.debug("extract_markdown: path=%r extracted %d chars", path, len(text))
    return {"text": text}
