"""Reusable text utilities."""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_HEADING = re.compile(r"^#{1,6}\s+.+$")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def _split_long_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Split an oversized sentence at word boundaries."""
    if len(text) <= chunk_size:
        return [text]
    words = text.split()
    chunks: list[str] = []
    current = ""
    for word in words:
        if len(word) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(
                word[start : start + chunk_size]
                for start in range(0, len(word), chunk_size - chunk_overlap)
            )
            if len(chunks) > 1 and len(chunks[-1]) <= chunk_overlap:
                chunks.pop()
            continue
        if current and len(current) + len(word) + 1 > chunk_size:
            chunks.append(current)
            current = word
        elif current:
            current = f"{current} {word}"
        else:
            current = word
    if current:
        chunks.append(current)
    return chunks


def _structured_segments(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Split text into heading-aware sentences that fit within a chunk."""
    segments: list[str] = []
    heading: str | None = None
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        nonlocal heading
        if not paragraph:
            return
        sentences = _SENTENCE_BOUNDARY.split(" ".join(paragraph))
        if heading:
            sentences[0] = f"{heading}\n{sentences[0]}"
            heading = None
        for sentence in sentences:
            segments.extend(_split_long_text(sentence.strip(), chunk_size, chunk_overlap))
        paragraph.clear()

    for line in text.splitlines():
        line = line.strip()
        if not line:
            flush_paragraph()
        elif _HEADING.match(line):
            flush_paragraph()
            if heading:
                segments.append(heading)
            heading = line
        else:
            paragraph.append(line)
    flush_paragraph()
    if heading:
        segments.append(heading)
    return segments


def chunk_text(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> list[str]:
    """Split text by headings, paragraphs, and sentences with overlap."""
    if chunk_size <= 0 or not 0 <= chunk_overlap < chunk_size:
        raise ValueError(
            "chunk_size must be positive and chunk_overlap must be smaller than chunk_size"
        )
    logger.debug("chunk_text() called: len(text)=%d, chunk_size=%d", len(text), chunk_size)
    chunks: list[str] = []
    current: list[str] = []

    for segment in _structured_segments(text, chunk_size, chunk_overlap):
        candidate = " ".join([*current, segment])
        if current and len(candidate) > chunk_size:
            chunks.append(" ".join(current))
            overlap: list[str] = []
            for previous in reversed(current):
                if len(" ".join([previous, *overlap])) > chunk_overlap:
                    break
                overlap.insert(0, previous)
            current = overlap
            while current and len(" ".join([*current, segment])) > chunk_size:
                current.pop(0)
        current.append(segment)

    if current:
        chunks.append(" ".join(current))
    return chunks
