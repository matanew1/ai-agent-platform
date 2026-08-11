"""Structural cache contract for module repositories."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol


class Cache(Protocol):
    """Primitive cache operations exposed to module repositories."""

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None: ...

    async def delete(self, key: str) -> bool: ...

    async def scan(self, prefix: str) -> list[str]: ...

    async def mget(self, keys: list[str]) -> list[str | None]: ...

    def lock(self, key: str) -> AbstractAsyncContextManager[None]: ...


__all__ = ["Cache"]
