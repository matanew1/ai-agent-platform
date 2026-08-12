"""Unit tests for the local tools in tool.tools.local.

Real PDF/Markdown extraction/generation logic - no mocking there, since
neither has an external dependency (network, DB, ...) to fake out. Storage
goes through a real ``ArtifactService`` backed by in-memory fake
repositories (no PostgreSQL involved) - see ``.claude/rules/testing.md``.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from artifact.service import ArtifactService
from pypdf import PdfReader
from sqlalchemy.exc import IntegrityError
from tool.tools.local.markdown import EDIT_DEFINITION as EDIT_MARKDOWN_DEFINITION
from tool.tools.local.markdown import (
    GENERATE_DEFINITION as GENERATE_MARKDOWN_DEFINITION,
)
from tool.tools.local.markdown import edit_markdown, extract_markdown, generate_markdown
from tool.tools.local.pdf import EDIT_DEFINITION as EDIT_PDF_DEFINITION
from tool.tools.local.pdf import GENERATE_DEFINITION as GENERATE_PDF_DEFINITION
from tool.tools.local.pdf import edit_pdf, extract_pdf, generate_pdf

from shared.types import ArtifactReference

# A minimal, hand-built single-page PDF containing the text "Hello PDF World" -
# avoids depending on a PDF-writing library just to test the reader.
_MINIMAL_PDF = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >>
   /MediaBox [0 0 200 100] /Contents 5 0 R >>
endobj
4 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
5 0 obj
<< /Length 55 >>
stream
BT /F1 12 Tf 10 50 Td (Hello PDF World) Tj ET
endstream
endobj
xref
0 6
0000000000 65535 f
trailer
<< /Size 6 /Root 1 0 R >>
startxref
0
%%EOF"""


class _FakeRepository:
    """In-memory stand-in for artifact.repository.ArtifactRepository."""

    def __init__(self) -> None:
        self.records: dict[str, tuple[bytes, str]] = {}

    async def store(self, filename: str, content: bytes, content_type: str) -> None:
        if filename in self.records:
            raise IntegrityError("duplicate artifact filename", {}, Exception("duplicate"))
        self.records[filename] = (content, content_type)

    async def read(self, filename: str) -> tuple[bytes, str] | None:
        return self.records.get(filename)

    async def grant(self, user_id: str, artifacts: list[ArtifactReference]) -> None:
        pass  # unused by these tests - ArtifactService just requires the method to exist

    async def can_download(self, user_id: str, filename: str) -> bool:
        return False  # unused by these tests


@pytest.fixture
def artifact_service() -> ArtifactService:
    """A real ArtifactService over an in-memory fake repository."""
    return ArtifactService(_FakeRepository())


def _stored_bytes(artifact_service: ArtifactService, filename: str) -> bytes:
    repository = artifact_service._repository  # type: ignore[attr-defined]
    content, _content_type = repository.records[filename]
    return content


async def test_extract_pdf_returns_the_page_text(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(_MINIMAL_PDF)

    result = await extract_pdf(str(pdf_path))

    assert "Hello PDF World" in result["text"]


async def test_extract_markdown_strips_common_syntax(tmp_path: Path) -> None:
    md_path = tmp_path / "sample.md"
    md_path.write_text(
        "# Title\n\n"
        "Some **bold** and *italic* text with a [link](https://example.com) "
        "and `inline code`.\n\n"
        "> a quote\n\n"
        "```\ncode block content\n```\n\n"
        "---\n\n"
        "Final paragraph.\n"
    )

    result = await extract_markdown(str(md_path))
    text = result["text"]

    assert "# " not in text
    assert "**" not in text
    assert "Title" in text
    assert "bold" in text
    assert "link" in text
    assert "https://example.com" not in text
    assert "inline code" in text
    assert "code block content" in text
    assert "Final paragraph." in text


async def test_generate_pdf_creates_a_downloadable_readable_pdf(
    artifact_service: ArtifactService,
) -> None:
    result = await generate_pdf("Hello generated PDF", artifact_service, path="../../generated.pdf")

    assert result == {
        "filename": "generated.pdf",
        "download_url": "/artifacts/generated.pdf",
        "pages": 1,
    }
    stored = _stored_bytes(artifact_service, result["filename"])
    assert "Hello generated PDF" in "\n".join(
        page.extract_text() or "" for page in PdfReader(BytesIO(stored)).pages
    )


async def test_generate_pdf_renders_markdown_instead_of_literal_syntax(
    artifact_service: ArtifactService,
) -> None:
    markdown_text = (
        "# Jane Doe\n"
        "\n"
        "## Experience\n"
        "\n"
        "Led the **payments** migration and improved *reliability* 2015–2020.\n"
        "\n"
        "- Shipped the [agent platform](https://example.com) to 50+ teams.\n"
        "- Mentored engineers.\n"
        "\n"
        "---\n"
        "\n"
        "See `README.md` for details.\n"
    )

    result = await generate_pdf(markdown_text, artifact_service, path="resume.pdf")

    stored = _stored_bytes(artifact_service, result["filename"])
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(stored)).pages)

    # The rendered content is present as plain words, not raw markdown
    # source - a header/bold/bullet/link marker would mean it fell back to
    # dumping the literal syntax onto the page (the bug being fixed here).
    assert "Jane Doe" in text
    assert "Experience" in text
    assert "payments" in text
    assert "reliability" in text
    assert "agent platform" in text
    assert "Shipped the" in text
    assert "Mentored engineers." in text
    assert "README.md" in text
    assert "#" not in text
    assert "**" not in text
    assert "[agent platform]" not in text
    assert "(https://example.com)" not in text
    # The old hand-rolled writer's Latin-1-only encoding silently replaced
    # anything outside that range (an en dash, here) with "?".
    assert "2015–2020" in text
    assert "?" not in text


async def test_generate_pdf_uses_a_default_name_and_avoids_collisions(
    artifact_service: ArtifactService,
) -> None:
    first = await generate_pdf("first", artifact_service)
    second = await generate_pdf("second", artifact_service)

    assert first["filename"] == "document.pdf"
    assert second["filename"] == "document-2.pdf"


async def test_edit_pdf_accepts_a_legacy_absolute_source_without_changing_it(
    tmp_path: Path,
    artifact_service: ArtifactService,
) -> None:
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(_MINIMAL_PDF)

    result = await edit_pdf(
        str(source_path),
        "Appended page",
        artifact_service,
        str(tmp_path / "requested output.pdf"),
    )

    assert result == {
        "filename": "requested output.pdf",
        "download_url": "/artifacts/requested%20output.pdf",
        "pages": 2,
    }
    assert len(PdfReader(source_path).pages) == 1
    stored = _stored_bytes(artifact_service, result["filename"])
    assert "Appended page" in "\n".join(
        page.extract_text() or "" for page in PdfReader(BytesIO(stored)).pages
    )


async def test_edit_pdf_accepts_artifact_urls_and_avoids_output_collisions(
    artifact_service: ArtifactService,
) -> None:
    generated = await generate_pdf("Original page", artifact_service, path="profile.pdf")

    first = await edit_pdf(generated["download_url"], "First appendix", artifact_service)
    second = await edit_pdf(generated["filename"], "Second appendix", artifact_service)

    assert first["filename"] == "profile-edited.pdf"
    assert first["download_url"] == "/artifacts/profile-edited.pdf"
    assert first["pages"] == 2
    assert second["filename"] == "profile-edited-2.pdf"
    original_pages = PdfReader(BytesIO(_stored_bytes(artifact_service, generated["filename"])))
    edited_pages = PdfReader(BytesIO(_stored_bytes(artifact_service, first["filename"])))
    assert len(original_pages.pages) == 1
    assert len(edited_pages.pages) == 2


async def test_edit_pdf_rejects_traversal_and_symlink_sources(
    tmp_path: Path, artifact_service: ArtifactService
) -> None:
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(_MINIMAL_PDF)
    symlink_path = tmp_path / "source-link.pdf"
    symlink_path.symlink_to(source_path)

    with pytest.raises(ValueError, match="safe filename"):
        await edit_pdf("/artifacts/%2e%2e%2fsource.pdf", "No traversal", artifact_service)
    with pytest.raises(ValueError, match="symbolic link"):
        await edit_pdf(str(symlink_path), "No symlinks", artifact_service)


async def test_generate_and_edit_markdown(artifact_service: ArtifactService) -> None:
    generated = await generate_markdown(
        "# Initial", artifact_service, path="folder/../generated.md"
    )
    appended = await edit_markdown(
        generated["download_url"], "More content", "append", artifact_service
    )
    replaced = await edit_markdown(
        appended["filename"],
        "# Replacement",
        "replace",
        artifact_service,
        output_path="../../final?.txt",
    )

    assert generated == {
        "filename": "generated.md",
        "download_url": "/artifacts/generated.md",
    }
    assert appended == {
        "filename": "generated-edited.md",
        "download_url": "/artifacts/generated-edited.md",
        "operation": "append",
    }
    assert replaced == {
        "filename": "final.md",
        "download_url": "/artifacts/final.md",
        "operation": "replace",
    }
    assert _stored_bytes(artifact_service, generated["filename"]) == b"# Initial"
    assert _stored_bytes(artifact_service, appended["filename"]) == b"# Initial\nMore content"
    assert _stored_bytes(artifact_service, replaced["filename"]) == b"# Replacement"


async def test_generate_markdown_sanitizes_names_and_avoids_collisions(
    artifact_service: ArtifactService,
) -> None:
    first = await generate_markdown("first", artifact_service, path=r"..\..\My report?.txt")
    second = await generate_markdown("second", artifact_service, path=r"..\..\My report?.txt")

    assert first == {
        "filename": "My report.md",
        "download_url": "/artifacts/My%20report.md",
    }
    assert second == {
        "filename": "My report-2.md",
        "download_url": "/artifacts/My%20report-2.md",
    }
    assert _stored_bytes(artifact_service, first["filename"]) == b"first"
    assert _stored_bytes(artifact_service, second["filename"]) == b"second"


def test_generation_tool_schemas_require_content_but_not_a_server_path() -> None:
    pdf_required = GENERATE_PDF_DEFINITION.parameters["required"]
    markdown_required = GENERATE_MARKDOWN_DEFINITION.parameters["required"]

    assert pdf_required == ["text"]
    assert markdown_required == ["content"]


def test_edit_tool_schemas_require_a_source_but_not_an_output_filename() -> None:
    pdf_required = EDIT_PDF_DEFINITION.parameters["required"]
    markdown_required = EDIT_MARKDOWN_DEFINITION.parameters["required"]

    assert pdf_required == ["path", "text"]
    assert markdown_required == ["path", "content", "operation"]
