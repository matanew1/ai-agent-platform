"""Qdrant adapter: implements the ``rag`` module's ``VectorStore`` port.

This is the only place in the codebase that imports ``qdrant_client``. The
``rag`` module knows nothing about Qdrant - it only depends on the
``VectorStore`` protocol this class structurally satisfies.
"""

from __future__ import annotations

import logging
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import AsyncQdrantClient, models

from shared.types import Chunk, PlatformError

logger = logging.getLogger(__name__)


class QdrantError(PlatformError):
    """Raised when a Qdrant operation fails."""


class QdrantVectorStore:
    """Async Qdrant-backed vector store.

    Satisfies ``rag.ports.VectorStore`` structurally - no inheritance from
    that protocol is required.

    Args:
        url: Qdrant endpoint (e.g. ``http://localhost:6333``).
        collection_name: Name of the collection to search/write to.
    """

    def __init__(self, url: str, collection_name: str) -> None:
        self._url = url
        self._collection_name = collection_name
        self._client = AsyncQdrantClient(url=url)
        logger.debug("QdrantVectorStore configured: url=%r collection=%r", url, collection_name)

    async def search(
        self,
        embedding: list[float],
        top_k: int = 5,
        metadata_filter: dict[str, str] | None = None,
    ) -> list[Chunk]:
        """Find the most similar chunks to a query embedding.

        Args:
            embedding: Query vector, same dimensionality as the collection.
            top_k: Maximum number of results to return.

        Returns:
            Chunks ordered by descending similarity, or an empty list if
            the collection hasn't been created yet (nothing indexed via
            ``upsert``/``ensure_collection`` so far) - a fresh deployment
            with no documents ingested is a normal state, not a failure,
            so callers (``agent.graph.retrieve_context``) get
            "no context" rather than an error for it.
        """
        logger.debug("search: collection=%r top_k=%d", self._collection_name, top_k)
        try:
            if not await self._client.collection_exists(self._collection_name):
                logger.debug(
                    "search: collection=%r doesn't exist yet - returning no results",
                    self._collection_name,
                )
                return []
            response = await self._client.query_points(
                collection_name=self._collection_name,
                query=embedding,
                limit=top_k,
                with_payload=True,
                query_filter=_metadata_filter(metadata_filter),
            )
        except Exception as exc:
            raise QdrantError(
                f"Failed to search collection {self._collection_name!r}: {exc}"
            ) from exc

        return [
            Chunk(
                id=str(point.payload.get("chunk_id", point.id)),
                text=str(point.payload["text"]),
                score=point.score,
                metadata=dict(point.payload.get("metadata", {})),
            )
            for point in response.points
        ]

    async def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        """Write chunks and their embeddings into the collection.

        Args:
            chunks: Chunks to store (id, text, metadata).
            embeddings: Embedding vectors, aligned by index with ``chunks``.
        """
        logger.debug("upsert: collection=%r chunks=%d", self._collection_name, len(chunks))
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have matching lengths")
        try:
            await self._client.upsert(
                collection_name=self._collection_name,
                points=[
                    models.PointStruct(
                        id=str(uuid5(NAMESPACE_URL, chunk.id)),
                        vector=embedding,
                        payload={
                            "chunk_id": chunk.id,
                            "text": chunk.text,
                            "metadata": chunk.metadata,
                        },
                    )
                    for chunk, embedding in zip(chunks, embeddings, strict=True)
                ],
            )
        except Exception as exc:
            raise QdrantError(
                f"Failed to upsert into collection {self._collection_name!r}: {exc}"
            ) from exc

    async def list_chunks(self, metadata_filter: dict[str, str]) -> list[Chunk]:
        """List all chunks matching exact metadata values, without vectors."""
        try:
            if not await self._client.collection_exists(self._collection_name):
                return []

            chunks: list[Chunk] = []
            offset: models.ExtendedPointId | None = None
            while True:
                points, offset = await self._client.scroll(
                    collection_name=self._collection_name,
                    scroll_filter=_metadata_filter(metadata_filter),
                    limit=100,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                chunks.extend(
                    Chunk(
                        id=str(point.payload.get("chunk_id", point.id)),
                        text=str(point.payload.get("text", "")),
                        score=0.0,
                        metadata=dict(point.payload.get("metadata", {})),
                    )
                    for point in points
                )
                if offset is None:
                    return chunks
        except Exception as exc:
            raise QdrantError(
                f"Failed to list chunks in collection {self._collection_name!r}: {exc}"
            ) from exc

    async def delete_chunks(self, metadata_filter: dict[str, str]) -> int:
        """Delete chunks matching exact metadata values and return their count."""
        # A missing filter must never degrade into a collection-wide delete.
        if not metadata_filter:
            return 0
        try:
            if not await self._client.collection_exists(self._collection_name):
                return 0
            point_filter = _metadata_filter(metadata_filter)
            count = await self._client.count(
                collection_name=self._collection_name,
                count_filter=point_filter,
                exact=True,
            )
            if count.count == 0:
                return 0
            await self._client.delete(
                collection_name=self._collection_name,
                points_selector=point_filter,
                wait=True,
            )
            return count.count
        except Exception as exc:
            raise QdrantError(
                f"Failed to delete chunks from collection {self._collection_name!r}: {exc}"
            ) from exc

    async def ensure_collection(self, vector_size: int) -> None:
        """Create the collection if it doesn't exist yet.

        Args:
            vector_size: Dimensionality of the embeddings that will be
                stored (must match the embedding model in use).
        """
        logger.debug(
            "ensure_collection: collection=%r vector_size=%d", self._collection_name, vector_size
        )
        try:
            exists = await self._client.collection_exists(self._collection_name)
            if not exists:
                await self._client.create_collection(
                    collection_name=self._collection_name,
                    vectors_config=models.VectorParams(
                        size=vector_size,
                        distance=models.Distance.COSINE,
                    ),
                )
        except Exception as exc:
            raise QdrantError(
                f"Failed to ensure collection {self._collection_name!r}: {exc}"
            ) from exc


def _metadata_filter(values: dict[str, str] | None) -> models.Filter | None:
    """Translate exact chunk metadata requirements into a Qdrant filter."""
    if not values:
        return None
    return models.Filter(
        must=[
            models.FieldCondition(key=f"metadata.{key}", match=models.MatchValue(value=value))
            for key, value in values.items()
        ]
    )
