"""Reusable text utilities."""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_HEADING = re.compile(r"^#{1,6}\s+.+$")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
_CODE_FENCE = re.compile(r"^```")


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


def _trailing_words(text: str, limit: int) -> str:
    """Longest word-bounded suffix of ``text`` that fits within ``limit``.

    Used to carry overlap forward a segment at a time when no *whole*
    segment fits the overlap budget - see ``chunk_text``. Prefers a word
    boundary the same way ``_split_long_text`` prefers one for an oversized
    segment; falls back to a hard character cut only if a single word is
    already longer than ``limit``.
    """
    words = text.split()
    kept: list[str] = []
    length = 0
    for word in reversed(words):
        added = len(word) + (1 if kept else 0)
        if length + added > limit:
            break
        kept.insert(0, word)
        length += added
    if kept:
        return " ".join(kept)
    return text[-limit:] if words else ""


def _structured_segments(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Split text into heading-aware sentences that fit within a chunk.

    A fenced code block (```` ``` ````...```` ``` ````) is kept as one
    atomic segment rather than sentence-split - splitting on every ``.``
    inside code tears the fence markers away from their content and cuts
    expressions mid-token (see the module's tests for a worked example).
    """
    segments: list[str] = []
    heading: str | None = None
    paragraph: list[str] = []
    fence: list[str] | None = None

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

    def flush_fence() -> None:
        nonlocal heading, fence
        if fence is None:
            return
        block = "\n".join(fence)
        if heading:
            block = f"{heading}\n{block}"
            heading = None
        segments.extend(_split_long_text(block, chunk_size, chunk_overlap))
        fence = None

    for raw_line in text.splitlines():
        if fence is not None:
            fence.append(raw_line)
            if _CODE_FENCE.match(raw_line.strip()):
                flush_fence()
            continue
        line = raw_line.strip()
        if _CODE_FENCE.match(line):
            flush_paragraph()
            fence = [raw_line]
        elif not line:
            flush_paragraph()
        elif _HEADING.match(line):
            flush_paragraph()
            if heading:
                segments.append(heading)
            heading = line
        else:
            paragraph.append(line)
    flush_paragraph()
    flush_fence()  # unterminated fence (malformed input) - flush, don't drop
    if heading:
        segments.append(heading)
    return segments


def chunk_text(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> list[str]:
    """Split text by headings, paragraphs, and sentences with overlap.

    ``chunk_overlap`` carries whole trailing segments (sentences, headings,
    fenced code blocks) forward into the next chunk where they fit; if none
    fit whole - e.g. every sentence is longer than the overlap budget - the
    tail characters of the last one are carried instead (skipped for a
    multi-line segment, to avoid mangling a fenced code block's line
    breaks), so a configured overlap is never silently dropped to zero.

    Every chunk this returns is at most ``chunk_size`` characters, with one
    deliberate exception: a final chunk smaller than a quarter of
    ``chunk_size`` is merged into the one before it rather than left as a
    near-empty, low-signal entry, even when that merge pushes the result
    past ``chunk_size`` - bounded by the same quarter-``chunk_size``
    threshold that triggers it, so the overshoot is small and predictable.
    """
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
            if not overlap and chunk_overlap > 0 and "\n" not in current[-1]:
                # The newline check excludes multi-line atomic segments
                # (fenced code blocks) - _trailing_words works word-by-word
                # and would collapse their line breaks into a mangled
                # fragment, undoing _structured_segments' whole point in
                # keeping them intact. Losing overlap there is the safer
                # failure: the next chunk starts clean instead of with a
                # torn-up shard of code.
                tail = _trailing_words(current[-1], chunk_overlap)
                if tail:
                    overlap = [tail]
            current = overlap
            while current and len(" ".join([*current, segment])) > chunk_size:
                current.pop(0)
        current.append(segment)

    if current:
        chunks.append(" ".join(current))

    if len(chunks) > 1 and len(chunks[-1]) < chunk_size // 4:
        # A tiny trailing chunk carries almost no retrieval signal of its
        # own, so it's folded into the one before it - unconditionally,
        # not only when the merge still fits chunk_size. A tiny remainder
        # almost always follows a chunk that's already nearly full (that
        # fullness is *why* the last segment overflowed into its own
        # chunk), so requiring the merge to stay within chunk_size would
        # veto it in exactly the case this exists to handle. The overshoot
        # this can introduce is bounded by the same threshold that
        # triggers it - at most chunk_size // 4 characters over.
        chunks[-2:] = [f"{chunks[-2]} {chunks[-1]}"]

    return chunks
