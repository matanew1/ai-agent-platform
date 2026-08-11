"""Vector-database client implementation.

The adapter exposes storage-shaped dictionaries only. Domain conversion (for
example, mapping a point to RAG's ``Chunk``) belongs to the consuming module.
"""

from __future__ import annotations

import logging
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import AsyncQdrantClient as AsyncVectorClient
from qdrant_client import models

from infrastructure.errors import VectorDatabaseError
from infrastructure.vector_database.protocol import VectorDatabase
from shared.implements import implements

logger = logging.getLogger(__name__)


@implements(VectorDatabase)
class QdrantVectorDatabase:
    """Async vector-database client for generic vector records."""

    def __init__(self, url: str, collection_name: str) -> None:
        self._collection_name = collection_name
        self._client = AsyncVectorClient(url=url)
        logger.debug("QdrantVectorDatabase configured: url=%r collection=%r", url, collection_name)

    async def search(
        self,
        embedding: list[float],
        top_k: int = 5,
        metadata_filter: dict[str, str] | None = None,
    ) -> list[dict[str, object]]:
        """Return matching records as primitive mappings."""
        try:
            if not await self._client.collection_exists(self._collection_name):
                return []
            response = await self._client.query_points(
                collection_name=self._collection_name,
                query=embedding,
                limit=top_k,
                with_payload=True,
                query_filter=_metadata_filter(metadata_filter),
            )
        except Exception as exc:
            raise VectorDatabaseError(
                f"Failed to search collection {self._collection_name!r}: {exc}"
            ) from exc
        return [_point_record(point) for point in response.points]

    async def upsert(self, records: list[dict[str, object]], embeddings: list[list[float]]) -> None:
        """Write records with aligned embeddings."""
        if len(records) != len(embeddings):
            raise ValueError("records and embeddings must have matching lengths")
        try:
            await self._client.upsert(
                collection_name=self._collection_name,
                points=[
                    models.PointStruct(
                        id=str(uuid5(NAMESPACE_URL, str(record["id"]))),
                        vector=embedding,
                        payload={
                            "record_id": str(record["id"]),
                            "text": str(record.get("text", "")),
                            "metadata": dict(record.get("metadata", {})),
                        },
                    )
                    for record, embedding in zip(records, embeddings, strict=True)
                ],
            )
        except Exception as exc:
            raise VectorDatabaseError(
                f"Failed to upsert collection {self._collection_name!r}: {exc}"
            ) from exc

    async def list_records(self, metadata_filter: dict[str, str]) -> list[dict[str, object]]:
        """List all records matching exact metadata values."""
        try:
            if not await self._client.collection_exists(self._collection_name):
                return []
            records: list[dict[str, object]] = []
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
                records.extend(_point_record(point) for point in points)
                if offset is None:
                    return records
        except Exception as exc:
            raise VectorDatabaseError(
                f"Failed to list collection {self._collection_name!r}: {exc}"
            ) from exc

    async def delete_records(self, metadata_filter: dict[str, str]) -> int:
        """Delete matching records, refusing an unbounded delete."""
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
            raise VectorDatabaseError(
                f"Failed to delete collection {self._collection_name!r}: {exc}"
            ) from exc

    async def ensure_collection(self, vector_size: int) -> None:
        """Create the configured collection when it does not exist."""
        try:
            if not await self._client.collection_exists(self._collection_name):
                await self._client.create_collection(
                    collection_name=self._collection_name,
                    vectors_config=models.VectorParams(
                        size=vector_size,
                        distance=models.Distance.COSINE,
                    ),
                )
        except Exception as exc:
            raise VectorDatabaseError(
                f"Failed to ensure collection {self._collection_name!r}: {exc}"
            ) from exc


def _point_record(point: object) -> dict[str, object]:
    payload = getattr(point, "payload", None) or {}
    metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
    return {
        "id": str(payload.get("record_id", payload.get("chunk_id", getattr(point, "id", "")))),
        "text": str(payload.get("text", "")),
        "score": float(getattr(point, "score", 0.0) or 0.0),
        "metadata": dict(metadata) if isinstance(metadata, dict) else {},
    }


def _metadata_filter(values: dict[str, str] | None) -> models.Filter | None:
    """Translate exact metadata requirements into a vector-database filter."""
    if not values:
        return None
    return models.Filter(
        must=[
            models.FieldCondition(key=f"metadata.{key}", match=models.MatchValue(value=value))
            for key, value in values.items()
        ]
    )


__all__ = ["QdrantVectorDatabase", "VectorDatabaseError"]
