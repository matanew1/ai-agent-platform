"""Durable MongoDB sessions with Redis used only as a hot coordination layer.

MongoDB is the source of truth for conversation checkpoints and complete
history. Redis remains useful for two deliberately ephemeral concerns:

* a short-lived read-through cache for the active context; and
* the distributed per-session lock that serializes concurrent turns.

This split means Redis eviction/TTL no longer deletes a user's conversation,
while the hot chat path and multi-process locking retain Redis semantics.
"""

from __future__ import annotations

import logging
import re
from contextlib import AbstractAsyncContextManager

from infrastructure.database import MongoDatabase
from infrastructure.redis import RedisError, RedisSessionStore
from shared.types import SessionCheckpoint

logger = logging.getLogger(__name__)

_COLLECTION = "agent_sessions"


class MongoSessionRepository:
    """Persist complete, scoped session checkpoints in MongoDB."""

    def __init__(self, database: MongoDatabase) -> None:
        self._database = database

    async def ensure_indexes(self) -> None:
        """Create stable lookup/sort indexes once during application startup."""
        await self._database.create_index(
            _COLLECTION,
            "session_id",
            unique=True,
            name="session_id_unique",
        )
        await self._database.create_index(
            _COLLECTION,
            [("session_id", 1), ("updated_at", -1)],
            name="session_prefix_updated_at",
        )

    async def get_checkpoint(self, session_id: str) -> SessionCheckpoint | None:
        document = await self._database.find_one(_COLLECTION, {"session_id": session_id})
        return _to_checkpoint(document) if document else None

    async def save_checkpoint(self, checkpoint: SessionCheckpoint) -> None:
        await self._database.replace_one(
            _COLLECTION,
            {"session_id": checkpoint.session_id},
            checkpoint.model_dump(mode="json"),
            upsert=True,
        )

    async def list_checkpoints(self, session_prefix: str) -> list[SessionCheckpoint]:
        # Prefixes contain authenticated user/agent ids and must remain
        # literal rather than becoming caller-controlled Mongo regex syntax.
        documents = await self._database.find_many(
            _COLLECTION,
            {"session_id": {"$regex": f"^{re.escape(session_prefix)}"}},
        )
        return sorted(
            (_to_checkpoint(document) for document in documents),
            key=lambda checkpoint: checkpoint.updated_at,
            reverse=True,
        )

    async def delete_checkpoint(self, session_id: str) -> bool:
        return await self._database.delete_one(_COLLECTION, {"session_id": session_id})


class HybridSessionStore:
    """Memory-port adapter combining durable Mongo and ephemeral Redis.

    Redis cache invalidation happens before the Mongo write while the caller
    holds the Redis session lock. If repopulating the cache fails afterward,
    it stays empty and the next read safely falls back to Mongo instead of
    serving a stale checkpoint.
    """

    def __init__(
        self,
        durable: MongoSessionRepository,
        hot: RedisSessionStore,
    ) -> None:
        self._durable = durable
        self._hot = hot

    async def get_checkpoint(self, session_id: str) -> SessionCheckpoint | None:
        try:
            cached = await self._hot.get_checkpoint(session_id)
        except RedisError as exc:
            logger.warning("Session cache read failed; falling back to MongoDB: %s", exc)
            cached = None
        if cached is not None:
            return cached

        checkpoint = await self._durable.get_checkpoint(session_id)
        if checkpoint is not None:
            await self._cache_best_effort(checkpoint)
        return checkpoint

    async def save_checkpoint(self, checkpoint: SessionCheckpoint) -> None:
        # Invalidating first is essential: if Mongo succeeds but a later
        # Redis SET fails, an old cached history must not survive.
        await self._hot.delete_checkpoint(checkpoint.session_id)
        await self._durable.save_checkpoint(checkpoint)
        await self._cache_best_effort(checkpoint)

    async def list_checkpoints(self, session_prefix: str) -> list[SessionCheckpoint]:
        # Lists/history navigation are durable product data, never a view of
        # whichever hot keys happen not to have expired from Redis.
        return await self._durable.list_checkpoints(session_prefix)

    async def delete_checkpoint(self, session_id: str) -> bool:
        async with self.session_lock(session_id):
            await self._hot.delete_checkpoint(session_id)
            return await self._durable.delete_checkpoint(session_id)

    def session_lock(self, session_id: str) -> AbstractAsyncContextManager[None]:
        return self._hot.session_lock(session_id)

    async def _cache_best_effort(self, checkpoint: SessionCheckpoint) -> None:
        try:
            await self._hot.save_checkpoint(checkpoint)
        except RedisError as exc:
            # Mongo has the durable copy and the old cache entry was already
            # invalidated. A cache outage should not roll back a saved turn.
            logger.warning("Session cache write failed; MongoDB remains authoritative: %s", exc)


def _to_checkpoint(document: dict[str, object]) -> SessionCheckpoint:
    return SessionCheckpoint.model_validate(
        {key: value for key, value in document.items() if key != "_id"}
    )
