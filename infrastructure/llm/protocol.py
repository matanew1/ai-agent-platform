"""Provider-neutral language-model and embedding client contracts.

The concrete adapters live beside these client shapes in the LLM
infrastructure capability.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from shared.types import ModelCatalogSnapshot


class LanguageModelClient(Protocol):
    """Generic language-model client."""

    provider_name: str
    default_model: str
    default_temperature: float

    def with_options(
        self, *, model: str | None = None, temperature: float | None = None
    ) -> LanguageModelClient:
        """Return a configured view without opening a new connection."""
        ...

    async def generate(self, prompt: str, max_tokens: int | None = None) -> str:
        """Generate a complete response."""
        ...

    def generate_stream(self, prompt: str) -> AsyncIterator[str]:
        """Generate a response incrementally."""
        ...

    async def available_models(self) -> ModelCatalogSnapshot:
        """Return provider model metadata."""
        ...


class EmbeddingClient(Protocol):
    """Generic embedding client."""

    async def embed(self, text: str) -> list[float]:
        """Embed one text value."""
        ...


__all__ = ["EmbeddingClient", "LanguageModelClient"]
