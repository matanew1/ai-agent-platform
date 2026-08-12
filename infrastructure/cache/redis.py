"""Redis cache client implementation.

This module owns only the cache connection and primitive operations.
Session serialization, key namespaces, TTL policy, and distributed-lock
semantics belong to the module that uses the cache (currently ``agent``).
"""

from __future__ import annotations

import logging
from contextlib import AbstractAsyncContextManager

from redis.asyncio import Redis as AsyncCacheClient
from redis.asyncio.lock import Lock as DistributedLock

from infrastructure.cache.protocol import Cache
from infrastructure.errors import CacheError
from shared.implements import implements

logger = logging.getLogger(__name__)


class _CacheLock(AbstractAsyncContextManager[None]):
    """Translate a distributed cache lock into the adapter's error contract."""

    def __init__(self, lock: DistributedLock) -> None:
        self._lock = lock

    async def __aenter__(self) -> None:
        try:
            acquired = await self._lock.acquire()
        except Exception as exc:
            raise CacheError(f"Failed to acquire cache lock: {exc}") from exc
        if not acquired:
            raise CacheError("Timed out waiting for the cache lock.")

    async def __aexit__(self, *exc_info: object) -> None:
        try:
            await self._lock.release()
        except Exception as exc:
            # Releasing is best effort. Raising here could mask an exception
            # from the caller's critical section.
            logger.warning("Failed to release cache lock: %s", exc)


@implements(Cache)
class RedisCache:
    """Async cache with no knowledge of application/entity objects.

    Callers choose their own key namespace, serialization, TTL, and lock
    policy. This keeps the adapter reusable by every module in the monorepo.
    """

    def __init__(
        self,
        redis_url: str,
        *,
        lock_timeout_seconds: int = 120,
        lock_blocking_timeout_seconds: int = 60,
    ) -> None:
        self._redis_url = redis_url
        self._lock_timeout_seconds = lock_timeout_seconds
        self._lock_blocking_timeout_seconds = lock_blocking_timeout_seconds
        self._client: AsyncCacheClient | None = None

    async def connect(self) -> None:
        """Open the cache connection pool."""
        self._client = AsyncCacheClient.from_url(self._redis_url, decode_responses=True)
        logger.debug("RedisCache connected")

    async def close(self) -> None:
        """Close the cache connection pool."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.debug("RedisCache connection closed")

    @property
    def _backend(self) -> AsyncCacheClient:
        if self._client is None:
            raise CacheError("RedisCache.connect() was not called before use.")
        return self._client

    async def get(self, key: str) -> str | None:
        """Read one serialized value."""
        try:
            return await self._backend.get(key)
        except Exception as exc:
            raise CacheError(f"Failed to read cache key {key!r}: {exc}") from exc

    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None:
        """Write one serialized value, optionally with an expiry."""
        try:
            await self._backend.set(key, value, ex=ttl_seconds)
        except Exception as exc:
            raise CacheError(f"Failed to write cache key {key!r}: {exc}") from exc

    async def delete(self, key: str) -> bool:
        """Delete one key and report whether it existed."""
        try:
            return bool(await self._backend.delete(key))
        except Exception as exc:
            raise CacheError(f"Failed to delete cache key {key!r}: {exc}") from exc

    async def scan(self, prefix: str) -> list[str]:
        """Return keys with a literal prefix using non-blocking SCAN."""
        pattern = f"{_escape_scan_match(prefix)}*"
        try:
            return [key async for key in self._backend.scan_iter(match=pattern, count=100)]
        except Exception as exc:
            raise CacheError(f"Failed to scan cache keys for prefix {prefix!r}: {exc}") from exc

    async def mget(self, keys: list[str]) -> list[str | None]:
        """Read multiple serialized values in one cache request."""
        if not keys:
            return []
        try:
            return await self._backend.mget(keys)
        except Exception as exc:
            raise CacheError(f"Failed to read cache keys: {exc}") from exc

    def lock(self, key: str) -> AbstractAsyncContextManager[None]:
        """Return a bounded distributed lock for a caller-owned key."""
        return _CacheLock(
            self._backend.lock(
                key,
                timeout=self._lock_timeout_seconds,
                blocking_timeout=self._lock_blocking_timeout_seconds,
            )
        )


def _escape_scan_match(value: str) -> str:
    """Escape cache-backend glob metacharacters so prefixes remain literal."""
    return "".join(f"\\{character}" if character in "\\*?[]" else character for character in value)


__all__ = ["CacheError", "RedisCache"]
