"""Unit tests for shared.text.chunk_text.

Pure function, no external dependency - real inputs, no mocking.
"""

from __future__ import annotations

import pytest

from shared.text import chunk_text


def test_splits_on_headings_paragraphs_and_sentences() -> None:
    text = "# Cats\nCats are small. They sleep a lot. They are popular pets. They purr softly.\n"

    chunks = chunk_text(text, chunk_size=40, chunk_overlap=25)

    assert chunks == [
        "# Cats\nCats are small. They sleep a lot.",
        "They sleep a lot. They are popular pets.",
        "They are popular pets. They purr softly.",
    ]


def test_no_chunk_exceeds_chunk_size_in_the_ordinary_case() -> None:
    text = " ".join(f"Sentence number {i} is here." for i in range(30))

    chunks = chunk_text(text, chunk_size=80, chunk_overlap=20)

    assert all(len(chunk) <= 80 for chunk in chunks)


class TestCodeFences:
    """Fix B: a fenced code block is one atomic segment, never sentence-split."""

    def test_a_fenced_code_block_survives_intact(self) -> None:
        text = (
            "Use this snippet:\n"
            "```python\n"
            "x = 1.5\n"
            'y = re.match(r"a.b.c", s)\n'
            "print(x, y)\n"
            "```\n"
            "That prints two values.\n"
        )

        chunks = chunk_text(text, chunk_size=60, chunk_overlap=10)

        assert '```python\nx = 1.5\ny = re.match(r"a.b.c", s)\nprint(x, y)\n```' in chunks
        # Regression: overlap must not reach into the fence and tear a
        # whitespace-collapsed shard of code into the following chunk.
        assert not any("```" in c and "That prints" in c for c in chunks)

    def test_a_heading_immediately_before_a_fence_stays_attached(self) -> None:
        text = "# Usage\n```\nrun_me()\n```\n"

        chunks = chunk_text(text, chunk_size=500, chunk_overlap=50)

        assert chunks == ["# Usage\n```\nrun_me()\n```"]

    def test_an_unterminated_fence_is_flushed_not_dropped(self) -> None:
        text = "Before.\n```python\nx = 1\n"

        chunks = chunk_text(text, chunk_size=500, chunk_overlap=50)

        assert any("```python\nx = 1" in c for c in chunks)

    def test_a_short_document_with_no_fence_is_unaffected(self) -> None:
        text = "Just a sentence. Another one."

        chunks = chunk_text(text, chunk_size=500, chunk_overlap=50)

        assert chunks == ["Just a sentence. Another one."]


class TestOverlapFallback:
    """Fix A: chunk_overlap carries a character tail forward when no whole
    segment fits the overlap budget, instead of silently becoming zero.
    """

    def test_overlap_is_not_silently_zero_when_every_sentence_exceeds_it(self) -> None:
        text = "Cats are small mammals. They sleep most of the day."

        chunks = chunk_text(text, chunk_size=45, chunk_overlap=10)

        assert chunks == ["Cats are small mammals.", "mammals. They sleep most of the day."]

    def test_the_fallback_tail_can_still_be_trimmed_away_if_chunk_size_has_no_room(self) -> None:
        """The pre-existing size safety net still wins when chunk_size is
        too tight to hold both a tail and the next full segment - the
        guarantee this fix adds is "a tail is attempted", not "overlap is
        never zero regardless of chunk_size".
        """
        text = "Cats are small mammals. They sleep most of the day."

        chunks = chunk_text(text, chunk_size=30, chunk_overlap=10)

        assert chunks == ["Cats are small mammals.", "They sleep most of the day."]

    def test_overlap_still_prefers_a_whole_segment_when_one_fits(self) -> None:
        text = (
            "# Cats\nCats are small. They sleep a lot. They are popular pets. They purr softly.\n"
        )

        chunks = chunk_text(text, chunk_size=40, chunk_overlap=25)

        assert chunks[1].startswith("They sleep a lot.")

    def test_overlap_fallback_does_not_reach_into_a_multiline_segment(self) -> None:
        """The interaction bug found while implementing this: taking a
        character/word tail of a fenced code block collapses its newlines
        and leaks a mangled fragment of code into the next chunk.
        """
        text = (
            "Use this snippet:\n"
            "```python\n"
            "x = 1.5\n"
            'y = re.match(r"a.b.c", s)\n'
            "print(x, y)\n"
            "```\n"
            "That prints two values.\n"
        )

        chunks = chunk_text(text, chunk_size=60, chunk_overlap=10)

        assert chunks[-1] == "That prints two values."


class TestTinyTrailingChunkMerge:
    """Fix C: a trailing chunk under chunk_size // 4 is folded into the
    previous chunk rather than left as a near-empty, low-signal entry.
    """

    def test_a_tiny_trailing_sentence_is_merged_into_the_previous_chunk(self) -> None:
        text = "This is a reasonably long sentence that fills most of a chunk on its own here. Ok."

        chunks = chunk_text(text, chunk_size=80, chunk_overlap=0)

        assert len(chunks) == 1
        assert chunks[0].endswith("Ok.")

    def test_the_merge_is_applied_even_when_it_exceeds_chunk_size(self) -> None:
        """A tiny remainder almost always follows a chunk that's already
        nearly full - requiring the merge to stay within chunk_size would
        veto it in exactly the case it exists to handle.
        """
        text = "This is a reasonably long sentence that fills most of a chunk on its own here. Ok."

        chunks = chunk_text(text, chunk_size=80, chunk_overlap=0)

        assert len(chunks[0]) > 80

    def test_a_trailing_chunk_above_the_floor_is_left_alone(self) -> None:
        text = "First sentence is here now. Second sentence also fills up quite a bit of room."

        chunks = chunk_text(text, chunk_size=40, chunk_overlap=0)

        # chunk_size // 4 == 10; the trailing chunk here is 12 chars - above
        # the floor, so it stays a separate chunk instead of being merged.
        assert chunks[-1] == "bit of room."
        assert len(chunks) == 3


def test_chunk_overlap_must_be_smaller_than_chunk_size() -> None:
    with pytest.raises(ValueError):
        chunk_text("hello", chunk_size=10, chunk_overlap=10)


def test_chunk_size_must_be_positive() -> None:
    with pytest.raises(ValueError):
        chunk_text("hello", chunk_size=0, chunk_overlap=0)


def test_empty_text_produces_no_chunks() -> None:
    assert chunk_text("") == []
