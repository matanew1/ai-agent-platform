"""Unit tests for Redis session checkpoint listing."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from infrastructure.redis import RedisError, RedisSessionStore
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
    store = RedisSessionStore("redis://unused")
    store._client = client

    checkpoints = await store.list_checkpoints("owner:agent:")

    assert [checkpoint.session_id for checkpoint in checkpoints] == [
        "owner:agent:newer",
        "owner:agent:older",
    ]
    assert client.patterns == [("agent_session:owner:agent:*", 100)]


async def test_list_checkpoints_translates_redis_failures() -> None:
    store = RedisSessionStore("redis://unused")
    store._client = _RedisClient({}, failure=RuntimeError("connection lost"))

    with pytest.raises(RedisError, match="Failed to list checkpoints"):
        await store.list_checkpoints("owner:agent:")


async def test_list_checkpoints_escapes_glob_characters_in_the_prefix() -> None:
    checkpoint = SessionCheckpoint(session_id="owner*?:agent:session")
    client = _RedisClient({"agent_session:owner*?:agent:session": checkpoint.model_dump_json()})
    store = RedisSessionStore("redis://unused")
    store._client = client

    checkpoints = await store.list_checkpoints("owner*?:agent:")

    assert [item.session_id for item in checkpoints] == ["owner*?:agent:session"]
    assert client.patterns == [(r"agent_session:owner\*\?:agent:*", 100)]
