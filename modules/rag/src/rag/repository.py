"""RAG vector-store adapter."""

from __future__ import annotations

from typing import cast

from infrastructure.vector_database.protocol import VectorDatabase
from shared.types import Chunk


class RagRepository:
    """Map generic vector-database records to the RAG ``Chunk`` model."""

    def __init__(self, database: VectorDatabase) -> None:
        self._database = database

    async def search(
        self,
        embedding: list[float],
        top_k: int = 5,
        metadata_filter: dict[str, str] | None = None,
    ) -> list[Chunk]:
        records = await self._database.search(embedding, top_k, metadata_filter)
        return [_to_chunk(record) for record in records]

    async def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        records = [
            {"id": chunk.id, "text": chunk.text, "metadata": chunk.metadata} for chunk in chunks
        ]
        await self._database.upsert(records, embeddings)

    async def list_chunks(self, metadata_filter: dict[str, str]) -> list[Chunk]:
        records = await self._database.list_records(metadata_filter)
        return [_to_chunk(record) for record in records]

    async def delete_chunks(self, metadata_filter: dict[str, str]) -> int:
        return await self._database.delete_records(metadata_filter)

    async def ensure_collection(self, vector_size: int) -> None:
        await self._database.ensure_collection(vector_size)


def _to_chunk(record: dict[str, object]) -> Chunk:
    metadata = record.get("metadata", {})
    return Chunk(
        id=str(record.get("id", "")),
        text=str(record.get("text", "")),
        score=float(record.get("score", 0.0)),
        metadata=cast(dict[str, str], metadata) if isinstance(metadata, dict) else {},
    )


__all__ = ["RagRepository"]
