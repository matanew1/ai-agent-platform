"""Lifecycle contract for the configured relational database."""

from __future__ import annotations

from typing import Protocol


class Database(Protocol):
    """Composition-root lifecycle boundary, not a leaky repository API."""

    async def connect(self) -> None: ...

    async def close(self) -> None: ...


__all__ = ["Database"]
