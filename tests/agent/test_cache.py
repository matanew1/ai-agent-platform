"""Unit tests for generic cache key scanning."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from infrastructure.cache.redis import RedisCache
from infrastructure.errors import CacheError
from shared.types import SessionCheckpoint


class _RedisClient:
    def __init__(self, values: dict[str, str], failure: Exception | None = None) -> None:
        self.values = values
        self.failure = failure
        self.patterns: list[tuple[str, int]] = []

    async def scan_iter(self, *, match: str, count: int):
        self.patterns.append((match, count))
        if self.failure is not None:
            raise self.failure
        literal_prefix = ""
        escaped = False
        for character in match.removesuffix("*"):
            if escaped:
                literal_prefix += character
                escaped = False
            elif character == chr(92):
                escaped = True
            else:
                literal_prefix += character
        for key in self.values:
            if key.startswith(literal_prefix):
                yield key

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [self.values.get(key) for key in keys]


async def test_list_checkpoints_scans_prefix_and_sorts_newest_first() -> None:
    older = SessionCheckpoint(
        session_id="owner:agent:older",
        updated_at=datetime(2026, 8, 9, tzinfo=UTC),
    )
    newer = SessionCheckpoint(
        session_id="owner:agent:newer",
        updated_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    client = _RedisClient(
        {
            "agent_session:owner:agent:older": older.model_dump_json(),
            "agent_session:another:agent:hidden": older.model_dump_json(),
            "agent_session:owner:agent:newer": newer.model_dump_json(),
        }
    )
    store = RedisCache("redis://unused")
    store._client = client

    keys = await store.scan("agent_session:owner:agent:")
    checkpoints = [
        SessionCheckpoint.model_validate_json(value)
        for value in await store.mget(keys)
        if value is not None
    ]
    checkpoints.sort(key=lambda checkpoint: checkpoint.updated_at, reverse=True)

    assert [checkpoint.session_id for checkpoint in checkpoints] == [
        "owner:agent:newer",
        "owner:agent:older",
    ]
    assert client.patterns == [("agent_session:owner:agent:*", 100)]


async def test_list_checkpoints_translates_redis_failures() -> None:
    store = RedisCache("redis://unused")
    store._client = _RedisClient({}, failure=RuntimeError("connection lost"))

    with pytest.raises(CacheError, match="Failed to scan cache keys"):
        await store.scan("agent_session:owner:agent:")


async def test_list_checkpoints_escapes_glob_characters_in_the_prefix() -> None:
    checkpoint = SessionCheckpoint(session_id="owner*?:agent:session")
    client = _RedisClient({"agent_session:owner*?:agent:session": checkpoint.model_dump_json()})
    store = RedisCache("redis://unused")
    store._client = client

    keys = await store.scan("agent_session:owner*?:agent:")
    checkpoints = [
        SessionCheckpoint.model_validate_json(value)
        for value in await store.mget(keys)
        if value is not None
    ]

    assert [item.session_id for item in checkpoints] == ["owner*?:agent:session"]
    assert client.patterns == [(r"agent_session:owner\*\?:agent:*", 100)]
