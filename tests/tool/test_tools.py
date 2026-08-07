"""Unit tests for the local tools in tool.tools.

Real files, real extraction - no mocking, since neither tool has an
external dependency (network, DB, ...) to fake out.
"""

from __future__ import annotations

from pathlib import Path

from tool.tools.markdown import extract_markdown
from tool.tools.pdf import extract_pdf

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
