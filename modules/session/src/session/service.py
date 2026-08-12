"""Session service: the module's public entry point.

Shared by ``agent.controller`` (session browsing routes) and
``chat.service.ChatService`` (turn execution needs ``memory`` for history
load/save and per-session locking) - the reason this lives in its own
module rather than inside either.
"""

from __future__ import annotations

import logging
from contextlib import AbstractAsyncContextManager

from session.repository import SessionRepository

from infrastructure.cache.protocol import Cache
from shared.types import SessionCheckpoint

logger = logging.getLogger(__name__)

_SESSION_KEY_PREFIX = "agent_session:"
_SESSION_LOCK_PREFIX = "agent_session_lock:"
_SESSION_TTL_SECONDS = 7 * 24 * 60 * 60


class HybridSessionStore:
    """Durable session memory with a cache for hot reads and locking."""

    def __init__(self, durable: SessionRepository, hot: Cache) -> None:
        self._durable = durable
        self._hot = hot

    async def migrate_hot_checkpoints(self) -> int:
        """Copy legacy cache entries into the durable store once at startup."""
        migrated = 0
        keys = await self._hot.scan(_SESSION_KEY_PREFIX)
        for _key, raw in zip(keys, await self._hot.mget(keys), strict=True):
            if raw is None:
                continue
            checkpoint = SessionCheckpoint.model_validate_json(raw)
            if await self._durable.get_checkpoint(checkpoint.session_id) is not None:
                continue
            await self._durable.save_checkpoint(checkpoint)
            migrated += 1
        if migrated:
            logger.info("Migrated %d legacy session checkpoint(s) to PostgreSQL", migrated)
        return migrated

    async def get_checkpoint(self, session_id: str) -> SessionCheckpoint | None:
        try:
            raw = await self._hot.get(_SESSION_KEY_PREFIX + session_id)
        except Exception as exc:
            logger.warning("Session cache read failed; falling back to PostgreSQL: %s", exc)
            raw = None
        if raw is not None:
            return SessionCheckpoint.model_validate_json(raw)

        checkpoint = await self._durable.get_checkpoint(session_id)
        if checkpoint is not None:
            await self._cache_best_effort(checkpoint)
        return checkpoint

    async def save_checkpoint(self, checkpoint: SessionCheckpoint) -> None:
        await self._hot.delete(_SESSION_KEY_PREFIX + checkpoint.session_id)
        await self._durable.save_checkpoint(checkpoint)
        await self._cache_best_effort(checkpoint)

    async def list_checkpoints(self, session_prefix: str) -> list[SessionCheckpoint]:
        return await self._durable.list_checkpoints(session_prefix)

    async def delete_checkpoint(self, session_id: str) -> bool:
        async with self.session_lock(session_id):
            await self._hot.delete(_SESSION_KEY_PREFIX + session_id)
            return await self._durable.delete_checkpoint(session_id)

    def session_lock(self, session_id: str) -> AbstractAsyncContextManager[None]:
        return self._hot.lock(_SESSION_LOCK_PREFIX + session_id)

    async def _cache_best_effort(self, checkpoint: SessionCheckpoint) -> None:
        try:
            await self._hot.set(
                _SESSION_KEY_PREFIX + checkpoint.session_id,
                checkpoint.model_dump_json(),
                ttl_seconds=_SESSION_TTL_SECONDS,
            )
        except Exception as exc:
            logger.warning("Session cache write failed; PostgreSQL remains authoritative: %s", exc)


__all__ = ["HybridSessionStore"]
