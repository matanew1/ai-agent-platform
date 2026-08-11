"""Local tools for extracting, generating, and editing Markdown files."""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from artifact.service import ArtifactService

from shared.types import ToolDefinition

_CONTENT_TYPE = "text/markdown; charset=utf-8"

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

GENERATE_DEFINITION = ToolDefinition(
    name="generate_markdown",
    description=(
        "Create a downloadable Markdown artifact containing the supplied content. Use this when "
        "the user asks to generate, create, export, or download a Markdown file. Returns its "
        "filename and download URL."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Optional output filename only, such as notes.md; directory components are "
                    "discarded. Defaults to document.md."
                ),
            },
            "content": {"type": "string", "description": "Markdown content to write."},
        },
        "required": ["content"],
    },
)

EDIT_DEFINITION = ToolDefinition(
    name="edit_markdown",
    description=(
        "Create a downloadable edited copy of a Markdown file by appending content or replacing "
        "all content. The source may be an /artifacts/<filename> download URL, artifact filename, "
        "or readable absolute Markdown path and is never modified. Use operation 'append' or "
        "'replace'. Returns the new filename, download URL, and operation."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Existing Markdown as an /artifacts/<filename> URL, safe artifact filename, "
                    "or readable absolute .md path."
                ),
            },
            "content": {
                "type": "string",
                "description": "Markdown content to append or use as replacement.",
            },
            "operation": {
                "type": "string",
                "enum": ["append", "replace"],
                "description": "Edit mode.",
            },
            "output_path": {
                "type": "string",
                "description": (
                    "Optional output filename only. Defaults to <source>-edited.md; directory "
                    "components are discarded."
                ),
            },
        },
        "required": ["path", "content", "operation"],
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


async def generate_markdown(
    content: str, artifact_service: ArtifactService, path: str | None = None
) -> dict[str, str]:
    """Generate downloadable Markdown, stored through ``ArtifactService``."""
    logger.debug("generate_markdown: requested_filename=%r content_len=%d", path, len(content))
    artifact = await artifact_service.store_text(
        content,
        requested_filename=path,
        default_stem="document",
        extension=".md",
        content_type=_CONTENT_TYPE,
    )
    return {"filename": artifact.filename, "download_url": artifact.download_url}


async def edit_markdown(
    path: str,
    content: str,
    operation: str,
    artifact_service: ArtifactService,
    output_path: str | None = None,
) -> dict[str, str]:
    """Append or replace content and store a downloadable copy."""
    if operation not in {"append", "replace"}:
        raise ValueError("operation must be either 'append' or 'replace'.")
    logger.debug(
        "edit_markdown: path=%r output_path=%r operation=%r content_len=%d",
        path,
        output_path,
        operation,
        len(content),
    )
    source_content, source_filename = await artifact_service.read(path, extension=".md")
    existing = source_content.decode("utf-8")
    if operation == "append":
        separator = "" if not existing or existing.endswith("\n") else "\n"
        edited_content = f"{existing}{separator}{content}"
    else:
        edited_content = content
    artifact = await artifact_service.store_text(
        edited_content,
        requested_filename=output_path,
        default_stem=f"{Path(source_filename).stem}-edited",
        extension=".md",
        content_type=_CONTENT_TYPE,
    )
    return {
        "filename": artifact.filename,
        "download_url": artifact.download_url,
        "operation": operation,
    }
