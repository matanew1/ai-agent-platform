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
