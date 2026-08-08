"""Unit tests for infrastructure.llm's empty-completion guard.

``_require_content`` is a pure function over a provider's already-returned
text, so it needs neither a live LLM nor a mocked SDK internal to test - the
provider classes around it still have no committed test (they'd need a real
Ollama/Mistral call, see .claude/rules/testing.md).

Regression coverage for a real bug: a reasoning-capable model with thinking
enabled spent the whole ``_TOOL_CALL_MAX_TOKENS`` budget on reasoning
tokens, so Ollama returned ``done_reason="length"`` with empty content. That
empty string parsed into zero tool calls, and the agent answered "no tool
results were available" without a single error being raised anywhere.
"""

from __future__ import annotations

import pytest

from infrastructure.llm import LLMError, _require_content


def test_content_passes_through_unchanged() -> None:
    assert _require_content('[{"name": "fetch"}]', "qwen3:8b", "stop") == '[{"name": "fetch"}]'


@pytest.mark.parametrize("empty", ["", "   ", "\n\t "])
def test_empty_completion_raises_instead_of_being_returned(empty: str) -> None:
    with pytest.raises(LLMError):
        _require_content(empty, "qwen3:8b", "stop")


def test_truncated_completion_explains_the_token_cap() -> None:
    """done_reason="length" is the reasoning-tokens-ate-the-budget case."""
    with pytest.raises(LLMError) as exc_info:
        _require_content("", "qwen3:8b", "length")

    message = str(exc_info.value)
    assert "qwen3:8b" in message
    assert "OLLAMA_REASONING=false" in message


def test_error_names_the_model_when_there_is_no_stop_reason() -> None:
    with pytest.raises(LLMError, match="mistral-small-latest"):
        _require_content("", "mistral-small-latest", None)
