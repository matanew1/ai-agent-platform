"""Ports (abstractions) that the rag module depends on.

``infrastructure/qdrant.py`` structurally satisfies ``VectorStore`` without
importing or inheriting from it. See ``.claude/rules/architecture.md``.
"""

from __future__ import annotations

from typing import Protocol

from shared.types import Chunk


class Embedder(Protocol):
    """Converts text into vectors for semantic search."""

    async def embed(self, text: str) -> list[float]:
        """Return an embedding for one piece of text."""
        ...


class LLMProvider(Protocol):
    """Generates text completions - used here to rerank retrieved chunks.

    A narrow duplicate of ``agent.internal.ports.LLMProvider``'s
    ``generate`` shape (``rag`` can't import ``agent``'s internal port -
    see ``.claude/rules/architecture.md``'s "Module-internal layout").
    ``infrastructure.llm.OllamaProvider``/``MistralProvider`` - the same
    instance built once in ``app/lifespan.py`` for ``AgentService`` -
    structurally satisfy this too, without changing shape or adding a
    method: only ``generate`` is needed here, so only ``generate`` is
    declared (``generate_stream`` is agent's alone to need).
    """

    async def generate(self, prompt: str, max_tokens: int | None = None) -> str:
        """Generate a completion for a prompt.

        Args:
            prompt: Fully-rendered prompt text.
            max_tokens: Cap on the number of tokens to generate.

        Returns:
            The model's response text.
        """
        ...


class VectorStore(Protocol):
    """A vector store capable of similarity search and indexing."""

    async def search(self, embedding: list[float], top_k: int = 5) -> list[Chunk]:
        """Find the most similar chunks to a query embedding.

        Args:
            embedding: Query vector.
            top_k: Maximum number of results to return.

        Returns:
            Chunks ordered by descending similarity.
        """
        ...

    async def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        """Write chunks and their embeddings into the store.

        Args:
            chunks: Chunks to store.
            embeddings: Embedding vectors, aligned by index with ``chunks``.
        """
        ...

    async def ensure_collection(self, vector_size: int) -> None:
        """Ensure the store can accept vectors with the given size."""
        ...
