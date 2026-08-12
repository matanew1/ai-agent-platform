"""Local tools for extracting, generating, and safely extending PDF files.

Generated PDFs render Markdown by default (headers, bold/italic, bullet
lists, links, horizontal rules) rather than dumping the raw syntax onto the
page - the previous hand-rolled, dependency-free PDF writer (single
Helvetica run of fixed-width-wrapped text, one big `Tj` block per line) had
no notion of formatting at all, so `**bold**`/`### Header`/`[text](url)`
came out as literal characters, and its Latin-1-only text encoding silently
replaced anything outside that range (an en dash, a curly quote, ...) with
"?". Confirmed live against a real generated resume before this rewrite -
see the git history on this file for the exact garbled output.

Deliberately regex-based Markdown parsing rather than a full CommonMark
library, the same call `tool.tools.local.markdown`'s stripper already
makes: this only needs to *render* the common constructs, not handle every
edge case a general-purpose Markdown parser would.
"""

from __future__ import annotations

import asyncio
import logging
import re
from io import BytesIO
from pathlib import Path

from artifact.service import ArtifactService
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

from shared.types import ToolDefinition

_CONTENT_TYPE = "application/pdf"

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
        "Create a downloadable, formatted PDF artifact from Markdown text. Supports #/##/### "
        "headers, **bold**, *italic*, `code`, [link](url), bullet lists (lines starting with "
        "'- ' or '* '), and horizontal rules (---) - use these to structure the document "
        "instead of writing plain unformatted prose. Use this when the user asks to generate, "
        "create, export, or download a PDF (e.g. a resume, report, or letter). Returns its "
        "filename, download URL, and page count."
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
            "text": {
                "type": "string",
                "description": "Markdown-formatted content to render into the PDF.",
            },
        },
        "required": ["text"],
    },
)

EDIT_DEFINITION = ToolDefinition(
    name="edit_pdf",
    description=(
        "Create a downloadable edited copy of a PDF by appending supplied Markdown text as new, "
        "formatted page(s) (same Markdown support as generate_pdf). The source may be an "
        "/artifacts/<filename> download URL, an artifact filename, or a readable absolute PDF "
        "path. The source is never modified. Returns the new filename, download URL, and page "
        "count."
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
            "text": {
                "type": "string",
                "description": "Markdown-formatted content to append as new page(s).",
            },
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

_PAGE_MARGIN = 0.75 * inch

# --- Inline markup (applied within one block/line) -----------------------


# ReportLab's Paragraph text is itself a small XML-like markup language
# (<b>, <i>, <link>, ...), so any literal &/</> in the source must be
# escaped *before* the markdown-to-tag substitutions below run - otherwise
# either a stray "<" breaks Paragraph's parser, or (worse) user-supplied
# text containing "<b>" would be interpreted as real markup.
def _escape_xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_LINK = re.compile(r"\[([^\]]+)\]\((\S+?)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*(?!\s)([^*\n]+?)(?<!\s)\*(?!\*)")
_INLINE_CODE = re.compile(r"`([^`]+?)`")


def _inline_markup(text: str) -> str:
    """Convert one line's inline Markdown into ReportLab Paragraph markup."""
    text = _escape_xml(text)
    text = _LINK.sub(r'<link href="\2" color="#1a56db"><u>\1</u></link>', text)
    text = _BOLD.sub(r"<b>\1</b>", text)
    text = _ITALIC.sub(r"<i>\1</i>", text)
    text = _INLINE_CODE.sub(r'<font face="Courier" size="9">\1</font>', text)
    return text


# --- Block structure (one regex per line-level construct) ----------------

_HEADER = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^\s*[-*]\s+(.*)$")
_NUMBERED = re.compile(r"^\s*(\d+)\.\s+(.*)$")
_HORIZONTAL_RULE = re.compile(r"^(-{3,}|\*{3,}|_{3,})\s*$")


def _styles() -> dict[str, ParagraphStyle]:
    """Named paragraph styles for each block type - built fresh per call.

    ``getSampleStyleSheet()`` returns a shared, mutable ``StyleSheet1``;
    reusing one across concurrent PDF-generation calls would let one
    request's style tweaks leak into another's, so each build gets its own.
    """
    base = getSampleStyleSheet()
    return {
        "Body": ParagraphStyle(
            "ATSBody",
            parent=base["Normal"],
            fontSize=10,
            leading=14,
            spaceAfter=4,
            alignment=TA_LEFT,
        ),
        "Bullet": ParagraphStyle(
            "ATSBullet",
            parent=base["Normal"],
            fontSize=10,
            leading=14,
            spaceAfter=2,
            leftIndent=16,
            bulletIndent=4,
        ),
        "Heading1": ParagraphStyle(
            "ATSHeading1",
            parent=base["Heading1"],
            fontSize=20,
            leading=24,
            spaceAfter=6,
            textColor=colors.HexColor("#111827"),
        ),
        "Heading2": ParagraphStyle(
            "ATSHeading2",
            parent=base["Heading2"],
            fontSize=14,
            leading=18,
            spaceBefore=10,
            spaceAfter=6,
            textColor=colors.HexColor("#1f2937"),
        ),
        "Heading3": ParagraphStyle(
            "ATSHeading3",
            parent=base["Heading3"],
            fontSize=12,
            leading=16,
            spaceBefore=8,
            spaceAfter=4,
            textColor=colors.HexColor("#374151"),
        ),
    }


def _build_flowables(text: str, styles: dict[str, ParagraphStyle]) -> list[object]:
    """Turn Markdown text into ReportLab flowables, one per block line."""
    flowables: list[object] = []
    heading_style_by_level = {1: "Heading1", 2: "Heading2", 3: "Heading3"}
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            flowables.append(Spacer(1, 6))
            continue
        if _HORIZONTAL_RULE.match(line):
            flowables.append(
                HRFlowable(
                    width="100%",
                    thickness=0.75,
                    color=colors.HexColor("#d1d5db"),
                    spaceBefore=4,
                    spaceAfter=8,
                )
            )
            continue
        header_match = _HEADER.match(line)
        if header_match:
            level = min(len(header_match.group(1)), 3)
            style = styles[heading_style_by_level[level]]
            flowables.append(Paragraph(_inline_markup(header_match.group(2)), style))
            continue
        bullet_match = _BULLET.match(line)
        if bullet_match:
            flowables.append(
                Paragraph(f"•&nbsp;&nbsp;{_inline_markup(bullet_match.group(1))}", styles["Bullet"])
            )
            continue
        numbered_match = _NUMBERED.match(line)
        if numbered_match:
            flowables.append(
                Paragraph(
                    f"{numbered_match.group(1)}.&nbsp;&nbsp;{_inline_markup(numbered_match.group(2))}",
                    styles["Bullet"],
                )
            )
            continue
        flowables.append(Paragraph(_inline_markup(line), styles["Body"]))
    return flowables or [Paragraph("", styles["Body"])]


def _build_text_pdf(text: str) -> bytes:
    """Render Markdown text into a formatted PDF."""
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=_PAGE_MARGIN,
        rightMargin=_PAGE_MARGIN,
        topMargin=_PAGE_MARGIN,
        bottomMargin=_PAGE_MARGIN,
    )
    document.build(_build_flowables(text, _styles()))
    return buffer.getvalue()


def _build_text_pdf_and_count(text: str) -> tuple[bytes, int]:
    """Render Markdown text into a PDF and report its page count.

    Pagination depends on how flowables wrap, so the page count can only be
    known after the document is built - re-parsing it with ``PdfReader`` is
    itself non-trivial work, so it's done here, inside the same
    ``asyncio.to_thread`` call as the build, rather than back on the event
    loop.
    """
    content = _build_text_pdf(text)
    return content, len(PdfReader(BytesIO(content)).pages)


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


async def generate_pdf(
    text: str, artifact_service: ArtifactService, path: str | None = None
) -> dict[str, str | int]:
    """Generate a downloadable, Markdown-rendered PDF, stored through ``ArtifactService``."""
    logger.debug("generate_pdf: requested_filename=%r text_len=%d", path, len(text))
    content, pages = await asyncio.to_thread(_build_text_pdf_and_count, text)
    artifact = await artifact_service.store(
        content,
        requested_filename=path,
        default_stem="document",
        extension=".pdf",
        content_type=_CONTENT_TYPE,
    )
    return {
        "filename": artifact.filename,
        "download_url": artifact.download_url,
        "pages": pages,
    }


def _build_edited_pdf(content: bytes, text: str) -> tuple[bytes, int]:
    """Copy a PDF and append Markdown-rendered pages in memory."""
    writer = PdfWriter()
    writer.append(PdfReader(BytesIO(content)))
    generated = PdfReader(BytesIO(_build_text_pdf(text)))
    writer.append(generated)
    output = BytesIO()
    writer.write(output)
    return output.getvalue(), len(writer.pages)


async def edit_pdf(
    path: str,
    text: str,
    artifact_service: ArtifactService,
    output_path: str | None = None,
) -> dict[str, str | int]:
    """Append Markdown-rendered pages and store a downloadable copy without changing the source."""
    logger.debug("edit_pdf: path=%r output_path=%r text_len=%d", path, output_path, len(text))
    source_content, source_filename = await artifact_service.read(path, extension=".pdf")
    content, pages = await asyncio.to_thread(_build_edited_pdf, source_content, text)
    artifact = await artifact_service.store(
        content,
        requested_filename=output_path,
        default_stem=f"{Path(source_filename).stem}-edited",
        extension=".pdf",
        content_type=_CONTENT_TYPE,
    )
    return {
        "filename": artifact.filename,
        "download_url": artifact.download_url,
        "pages": pages,
    }
