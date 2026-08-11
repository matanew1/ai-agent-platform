"""Unit tests for the local tools in tool.tools.

Real files, real extraction - no mocking, since neither tool has an
external dependency (network, DB, ...) to fake out.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfReader
from tool.tools.markdown import EDIT_DEFINITION as EDIT_MARKDOWN_DEFINITION
from tool.tools.markdown import (
    GENERATE_DEFINITION as GENERATE_MARKDOWN_DEFINITION,
)
from tool.tools.markdown import edit_markdown, extract_markdown, generate_markdown
from tool.tools.pdf import EDIT_DEFINITION as EDIT_PDF_DEFINITION
from tool.tools.pdf import GENERATE_DEFINITION as GENERATE_PDF_DEFINITION
from tool.tools.pdf import edit_pdf, extract_pdf, generate_pdf

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


@pytest.fixture
def artifacts_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep generated tool output isolated from the repository."""
    directory = tmp_path / "artifacts"
    monkeypatch.setenv("ARTIFACTS_DIR", str(directory))
    return directory


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
    artifacts_dir: Path,
) -> None:
    result = await generate_pdf("Hello generated PDF", path="../../generated.pdf")
    pdf_path = artifacts_dir / result["filename"]

    assert result == {
        "filename": "generated.pdf",
        "download_url": "/artifacts/generated.pdf",
        "pages": 1,
    }
    assert pdf_path.parent == artifacts_dir
    assert "Hello generated PDF" in "\n".join(
        page.extract_text() or "" for page in PdfReader(pdf_path).pages
    )


async def test_generate_pdf_uses_a_default_name_and_avoids_collisions(
    artifacts_dir: Path,
) -> None:
    first = await generate_pdf("first")
    second = await generate_pdf("second")

    assert first["filename"] == "document.pdf"
    assert second["filename"] == "document-2.pdf"
    assert (artifacts_dir / "document.pdf").exists()
    assert (artifacts_dir / "document-2.pdf").exists()


async def test_edit_pdf_accepts_a_legacy_absolute_source_without_changing_it(
    tmp_path: Path,
    artifacts_dir: Path,
) -> None:
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(_MINIMAL_PDF)

    result = await edit_pdf(
        str(source_path),
        "Appended page",
        str(tmp_path / "requested output.pdf"),
    )
    edited_path = artifacts_dir / result["filename"]

    assert result == {
        "filename": "requested output.pdf",
        "download_url": "/artifacts/requested%20output.pdf",
        "pages": 2,
    }
    assert len(PdfReader(source_path).pages) == 1
    assert "Appended page" in "\n".join(
        page.extract_text() or "" for page in PdfReader(edited_path).pages
    )


async def test_edit_pdf_accepts_artifact_urls_and_avoids_output_collisions(
    artifacts_dir: Path,
) -> None:
    generated = await generate_pdf("Original page", path="profile.pdf")

    first = await edit_pdf(generated["download_url"], "First appendix")
    second = await edit_pdf(generated["filename"], "Second appendix")

    assert first["filename"] == "profile-edited.pdf"
    assert first["download_url"] == "/artifacts/profile-edited.pdf"
    assert first["pages"] == 2
    assert second["filename"] == "profile-edited-2.pdf"
    assert len(PdfReader(artifacts_dir / generated["filename"]).pages) == 1
    assert len(PdfReader(artifacts_dir / first["filename"]).pages) == 2


async def test_edit_pdf_rejects_traversal_and_symlink_sources(tmp_path: Path) -> None:
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(_MINIMAL_PDF)
    symlink_path = tmp_path / "source-link.pdf"
    symlink_path.symlink_to(source_path)

    with pytest.raises(ValueError, match="safe filename"):
        await edit_pdf("/artifacts/%2e%2e%2fsource.pdf", "No traversal")
    with pytest.raises(ValueError, match="symbolic link"):
        await edit_pdf(str(symlink_path), "No symlinks")


async def test_generate_and_edit_markdown(artifacts_dir: Path) -> None:
    generated = await generate_markdown("# Initial", path="folder/../generated.md")
    appended = await edit_markdown(generated["download_url"], "More content", "append")
    replaced = await edit_markdown(
        appended["filename"],
        "# Replacement",
        "replace",
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
    assert (artifacts_dir / generated["filename"]).read_text() == "# Initial"
    assert (artifacts_dir / appended["filename"]).read_text() == "# Initial\nMore content"
    assert (artifacts_dir / replaced["filename"]).read_text() == "# Replacement"


async def test_generate_markdown_sanitizes_names_and_avoids_collisions(
    artifacts_dir: Path,
) -> None:
    first = await generate_markdown("first", path=r"..\..\My report?.txt")
    second = await generate_markdown("second", path=r"..\..\My report?.txt")

    assert first == {
        "filename": "My report.md",
        "download_url": "/artifacts/My%20report.md",
    }
    assert second == {
        "filename": "My report-2.md",
        "download_url": "/artifacts/My%20report-2.md",
    }
    assert (artifacts_dir / first["filename"]).read_text() == "first"
    assert (artifacts_dir / second["filename"]).read_text() == "second"


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
