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

from infrastructure.llm import (
    LLMError,
    MistralProvider,
    OllamaProvider,
    _require_content,
    _supports_chat_model,
)
from shared.types import ModelCatalogSnapshot


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


@pytest.mark.parametrize(
    ("provider", "model"),
    [
        (OllamaProvider(base_url="http://localhost:11434", model="qwen3:8b"), "qwen3:14b"),
        (
            MistralProvider(api_key="test-key", model="mistral-small-latest"),
            "mistral-medium-latest",
        ),
    ],
)
def test_generation_options_clone_provider_without_mutating_base(
    provider: object, model: str
) -> None:
    configured = provider.with_options(model=model, temperature=0.3)

    assert configured is not provider
    assert configured._model == model
    assert configured._chat.model == model
    assert configured._chat.temperature == 0.3
    assert provider._model != model


@pytest.mark.parametrize(
    ("model", "capabilities", "expected"),
    [
        ("qwen3:8b", ["completion", "tools"], True),
        ("bge-m3:latest", ["embedding"], False),
        ("renamed-vector-model", ["embedding"], False),
        ("nomic-embed-text:latest", None, False),
        ("qwen3:8b", None, True),
    ],
)
def test_ollama_catalog_filters_embedding_only_models(
    model: str, capabilities: list[str] | None, expected: bool
) -> None:
    assert _supports_chat_model(model, "bge-m3", capabilities) is expected


async def test_ollama_catalog_caches_discovery_for_repeated_configuration_reads() -> None:
    provider = OllamaProvider(base_url="http://localhost:11434", model="qwen3:8b")
    calls = 0

    async def discover() -> ModelCatalogSnapshot:
        nonlocal calls
        calls += 1
        return ModelCatalogSnapshot(models=("qwen3:8b",), authoritative=True)

    provider._discover_models = discover

    first = await provider.available_models()
    second = await provider.available_models()

    assert first is second
    assert calls == 1


async def test_mistral_catalog_exposes_only_configured_model_without_discovery() -> None:
    provider = MistralProvider(api_key="test-key", model="mistral-small-latest")

    snapshot = await provider.available_models()

    assert provider.provider_name == "mistralai"
    assert provider.default_temperature == 0.3
    assert snapshot == ModelCatalogSnapshot(
        models=("mistral-small-latest",),
        authoritative=False,
    )
