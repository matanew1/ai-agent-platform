"""Unit tests for shared.prompt_formatters - pure text formatting, no mocking needed."""

from __future__ import annotations

from shared.prompt_formatters import format_history
from shared.types import ChatMessage


def test_format_history_renders_role_and_content_for_each_turn() -> None:
    history = [
        ChatMessage(role="user", content="hi there"),
        ChatMessage(role="assistant", content="hello!"),
    ]

    assert format_history(history) == "user: hi there\nassistant: hello!"


def test_format_history_returns_a_placeholder_for_no_history() -> None:
    assert format_history([]) == "(none)"


def test_format_history_neutralizes_artifact_links_from_past_turns() -> None:
    # A prior assistant turn's saved content can contain a real download
    # link (the model was instructed to state one when a file was
    # generated). Replaying it verbatim into a later prompt gives the model
    # a copyable "/artifacts/document-N.pdf" precedent it can extrapolate
    # into a *new*, never-generated filename on a turn where no
    # file-generation tool ran - confirmed live, and what this guards
    # against: the download link text must not survive into the formatted
    # history, only a neutral placeholder.
    history = [
        ChatMessage(
            role="assistant",
            content=(
                "The file was created and can be downloaded from the following "
                "link: /artifacts/document-3.pdf"
            ),
        ),
    ]

    formatted = format_history(history)

    assert "/artifacts/document-3.pdf" not in formatted
    assert "The file was created" in formatted
    assert "[link omitted from history]" in formatted
