"""Redis adapter: agent session memory.

Stores conversation history per session as
``agent_session:{session_id} -> SessionCheckpoint`` (JSON), with a TTL
refreshed on every write so an active conversation never expires mid-use
but an abandoned one eventually does - see ``RedisSessionStore``.
Structurally satisfies the ``Memory`` port defined in
``modules/agent/src/agent/ports.py``.
"""

from __future__ import annotations

import logging
from contextlib import AbstractAsyncContextManager

from redis.asyncio import Redis
from redis.asyncio.lock import Lock

from shared.types import PlatformError, SessionCheckpoint

logger = logging.getLogger(__name__)

_SESSION_KEY_PREFIX = "agent_session:"
_SESSION_LOCK_PREFIX = "agent_session_lock:"

# Auto-expiry on the lock itself, independent of blocking_timeout below -
# a safety net so a crashed/hung process can never leave a session locked
# forever. Set generously above realistic worst-case turn latency (a slow
# local model can genuinely take tens of seconds - see
# .claude/rules/architecture.md's performance notes).
_SESSION_LOCK_TIMEOUT_SECONDS = 120
# How long a second request on the same session waits for the first to
# finish before giving up with a clear error, rather than hanging
# indefinitely on a stuck lock.
_SESSION_LOCK_BLOCKING_TIMEOUT_SECONDS = 60
# How long an idle session's checkpoint survives before Redis evicts it.
# Refreshed on every save_checkpoint, so an active conversation never
# expires mid-use.
_SESSION_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days


def _escape_scan_match(value: str) -> str:
    """Escape Redis glob metacharacters so a session prefix stays literal."""
    return "".join(f"\\{character}" if character in "\\*?[]" else character for character in value)


class RedisError(PlatformError):
    """Raised when a Redis operation fails."""


class _SessionLock(AbstractAsyncContextManager[None]):
    """Wraps a ``redis.asyncio`` ``Lock`` so nothing outside this module
    ever sees a raw redis exception or the redis-specific ``Lock`` type -
    just ``RedisError``, the same failure mode as every other
    ``RedisSessionStore`` method. Not exposed directly; only returned by
    ``RedisSessionStore.session_lock``.
    """

    def __init__(self, lock: Lock) -> None:
        self._lock = lock

    async def __aenter__(self) -> None:
        try:
            acquired = await self._lock.acquire()
        except Exception as exc:
            raise RedisError(f"Failed to acquire session lock: {exc}") from exc
        if not acquired:
            raise RedisError(
                "Timed out waiting for another in-flight request on this session to finish."
            )

    async def __aexit__(self, *exc_info: object) -> None:
        # Deliberately non-fatal: by the time __aexit__ runs, the caller's
        # checkpoint save has already happened (see AgentService.run/
        # run_stream) - a failed release (e.g. the lock's own timeout
        # already expired) only means the exclusivity window ended early,
        # not that anything was lost. Raising here would also risk masking
        # a real exception already propagating out of the `async with`
        # block's body.
        try:
            await self._lock.release()
        except Exception as exc:
            logger.warning("Failed to release session lock (likely already expired): %s", exc)


class RedisSessionStore:
    """Async Redis-backed store for agent session checkpoints.

    Args:
        redis_url: Redis connection URL (e.g. ``redis://localhost:6379/0``).
    """

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._client: Redis | None = None

    async def connect(self) -> None:
        """Open the connection. Call once at app startup."""
        self._client = Redis.from_url(self._redis_url, decode_responses=True)
        logger.debug("RedisSessionStore connected")

    async def close(self) -> None:
        """Close the connection. Call once at app shutdown."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.debug("RedisSessionStore connection closed")

    async def get_checkpoint(self, session_id: str) -> SessionCheckpoint | None:
        """Fetch the stored checkpoint for a session.

        Args:
            session_id: Conversation/session identifier.

        Returns:
            The stored checkpoint, or ``None`` if the session has no
            checkpoint yet.

        Raises:
            RedisError: If the Redis operation fails.
        """
        try:
            raw = await self._client.get(_SESSION_KEY_PREFIX + session_id)
        except Exception as exc:
            raise RedisError(
                f"Failed to fetch checkpoint for session {session_id!r}: {exc}"
            ) from exc
        if raw is None:
            logger.debug("get_checkpoint: no checkpoint for session_id=%r", session_id)
            return None
        logger.debug("get_checkpoint: found checkpoint for session_id=%r", session_id)
        return SessionCheckpoint.model_validate_json(raw)

    async def save_checkpoint(self, checkpoint: SessionCheckpoint) -> None:
        """Persist a session checkpoint.

        Args:
            checkpoint: Checkpoint to store, keyed by its ``session_id``.

        Raises:
            RedisError: If the Redis operation fails.
        """
        try:
            await self._client.set(
                _SESSION_KEY_PREFIX + checkpoint.session_id,
                checkpoint.model_dump_json(),
                ex=_SESSION_TTL_SECONDS,
            )
        except Exception as exc:
            raise RedisError(
                f"Failed to save checkpoint for session {checkpoint.session_id!r}: {exc}"
            ) from exc
        logger.debug("save_checkpoint: session_id=%r", checkpoint.session_id)

    async def delete_checkpoint(self, session_id: str) -> bool:
        """Invalidate one hot checkpoint without touching durable history."""
        try:
            deleted = await self._client.delete(_SESSION_KEY_PREFIX + session_id)
        except Exception as exc:
            raise RedisError(
                f"Failed to invalidate checkpoint for session {session_id!r}: {exc}"
            ) from exc
        return bool(deleted)

    async def list_checkpoints(self, session_prefix: str) -> list[SessionCheckpoint]:
        """List checkpoints under one already-scoped session-id prefix.

        Redis ``SCAN`` is used instead of ``KEYS`` so listing sessions does
        not block the server when the keyspace grows. Locks have their own
        prefix and therefore cannot appear in these results.
        """
        key_pattern = f"{_SESSION_KEY_PREFIX}{_escape_scan_match(session_prefix)}*"
        try:
            keys = [key async for key in self._client.scan_iter(match=key_pattern, count=100)]
            if not keys:
                return []
            values = await self._client.mget(keys)
            checkpoints = [
                SessionCheckpoint.model_validate_json(value)
                for value in values
                if value is not None
            ]
        except Exception as exc:
            raise RedisError(
                f"Failed to list checkpoints for prefix {session_prefix!r}: {exc}"
            ) from exc
        return sorted(checkpoints, key=lambda checkpoint: checkpoint.updated_at, reverse=True)

    def session_lock(self, session_id: str) -> AbstractAsyncContextManager[None]:
        """Exclusive lock over one session's checkpoint, for the caller to
        hold across a load -> modify -> save sequence.

        Guards against two concurrent requests on the same session_id
        racing each other: both reading the same starting checkpoint, then
        both saving, with whichever save lands last silently discarding the
        other's turn. See ``agent.service.AgentService.run``/``run_stream``,
        the only callers.

        Args:
            session_id: Conversation/session identifier.

        Returns:
            An async context manager. Entering it blocks (up to
            ``_SESSION_LOCK_BLOCKING_TIMEOUT_SECONDS``) until the lock is
            acquired; raises ``RedisError`` if that wait times out or the
            underlying Redis call fails.
        """
        lock = self._client.lock(
            _SESSION_LOCK_PREFIX + session_id,
            timeout=_SESSION_LOCK_TIMEOUT_SECONDS,
            blocking_timeout=_SESSION_LOCK_BLOCKING_TIMEOUT_SECONDS,
        )
        return _SessionLock(lock)
