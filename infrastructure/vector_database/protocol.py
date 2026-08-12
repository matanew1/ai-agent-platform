"""Structural vector-database contract for RAG repositories."""

from __future__ import annotations

from typing import Protocol


class VectorDatabase(Protocol):
    """Primitive vector-record operations exposed to RAG repositories."""

    async def search(
        self,
        embedding: list[float],
        top_k: int = 5,
        metadata_filter: dict[str, str] | None = None,
    ) -> list[dict[str, object]]: ...

    async def upsert(
        self, records: list[dict[str, object]], embeddings: list[list[float]]
    ) -> None: ...

    async def list_records(self, metadata_filter: dict[str, str]) -> list[dict[str, object]]: ...

    async def delete_records(self, metadata_filter: dict[str, str]) -> int: ...

    async def ensure_collection(self, vector_size: int) -> None: ...


__all__ = ["VectorDatabase"]
