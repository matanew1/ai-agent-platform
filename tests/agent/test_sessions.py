"""Tests for PostgreSQL-durable sessions backed by a Redis hot layer."""

from __future__ import annotations

from contextlib import asynccontextmanager

from session.service import HybridSessionStore

from infrastructure.errors import CacheError
from shared.types import SessionCheckpoint


class _Hot:
    def __init__(self) -> None:
        self.items: dict[str, SessionCheckpoint] = {}
        self.events: list[str] = []
        self.fail_save = False

    async def get_checkpoint(self, session_id):
        self.events.append("hot:get")
        return self.items.get(session_id)

    async def get(self, key):
        return (
            (await self.get_checkpoint(key.removeprefix("agent_session:"))).model_dump_json()
            if await self.get_checkpoint(key.removeprefix("agent_session:"))
            else None
        )

    async def save_checkpoint(self, checkpoint):
        self.events.append("hot:save")
        if self.fail_save:
            raise CacheError("offline")
        self.items[checkpoint.session_id] = checkpoint

    async def set(self, key, value, *, ttl_seconds=None):
        self.events.append("hot:save")
        if self.fail_save:
            raise CacheError("offline")
        self.items[key.removeprefix("agent_session:")] = SessionCheckpoint.model_validate_json(
            value
        )

    async def delete_checkpoint(self, session_id):
        self.events.append("hot:delete")
        return self.items.pop(session_id, None) is not None

    async def delete(self, key):
        self.events.append("hot:delete")
        return self.items.pop(key.removeprefix("agent_session:"), None) is not None

    async def list_checkpoints(self, session_prefix):
        self.events.append("hot:list")
        return [
            checkpoint
            for session_id, checkpoint in self.items.items()
            if session_id.startswith(session_prefix)
        ]

    async def scan(self, prefix):
        self.events.append("hot:list")
        return [
            f"agent_session:{session_id}"
            for session_id in self.items
            if session_id.startswith(prefix.removeprefix("agent_session:"))
        ]

    async def mget(self, keys):
        return [self.items[key.removeprefix("agent_session:")].model_dump_json() for key in keys]

    @asynccontextmanager
    async def session_lock(self, _session_id):
        self.events.append("lock:enter")
        yield
        self.events.append("lock:exit")

    def lock(self, session_id):
        return self.session_lock(session_id)


class _Durable:
    def __init__(self, checkpoint: SessionCheckpoint | None = None) -> None:
        self.checkpoint = checkpoint
        self.events: list[str] = []

    async def get_checkpoint(self, _session_id):
        self.events.append("postgres:get")
        return self.checkpoint

    async def save_checkpoint(self, checkpoint):
        self.events.append("postgres:save")
        self.checkpoint = checkpoint

    async def list_checkpoints(self, _prefix, limit=None, offset=0):
        self.events.append("postgres:list")
        return [self.checkpoint] if self.checkpoint else []

    async def count_checkpoints(self, _prefix):
        self.events.append("postgres:count")
        return 1 if self.checkpoint else 0

    async def delete_checkpoint(self, _session_id):
        self.events.append("postgres:delete")
        existed = self.checkpoint is not None
        self.checkpoint = None
        return existed


async def test_hybrid_store_reads_hot_then_falls_back_to_postgresql_and_repopulates() -> None:
    checkpoint = SessionCheckpoint(session_id="owner:agent:session")
    hot = _Hot()
    durable = _Durable(checkpoint)
    store = HybridSessionStore(durable, hot)

    assert await store.get_checkpoint(checkpoint.session_id) == checkpoint
    assert durable.events == ["postgres:get"]
    assert hot.items[checkpoint.session_id] == checkpoint

    durable.events.clear()
    assert await store.get_checkpoint(checkpoint.session_id) == checkpoint
    assert durable.events == []


async def test_hybrid_save_invalidates_before_durable_write_and_tolerates_cache_outage() -> None:
    checkpoint = SessionCheckpoint(session_id="owner:agent:session")
    hot = _Hot()
    hot.items[checkpoint.session_id] = SessionCheckpoint(session_id=checkpoint.session_id)
    hot.fail_save = True
    durable = _Durable()
    store = HybridSessionStore(durable, hot)

    await store.save_checkpoint(checkpoint)

    assert hot.events == ["hot:delete", "hot:save"]
    assert durable.events == ["postgres:save"]
    assert checkpoint.session_id not in hot.items
    assert durable.checkpoint == checkpoint


async def test_hybrid_lists_from_postgresql_and_deletes_under_the_redis_lock() -> None:
    checkpoint = SessionCheckpoint(session_id="owner:agent:session")
    hot = _Hot()
    durable = _Durable(checkpoint)
    store = HybridSessionStore(durable, hot)

    assert await store.list_checkpoints("owner:agent:") == [checkpoint]
    assert await store.delete_checkpoint(checkpoint.session_id) is True
    assert durable.events == ["postgres:list", "postgres:delete"]
    assert hot.events == ["lock:enter", "hot:delete", "lock:exit"]


async def test_hybrid_migrates_only_legacy_redis_only_checkpoints() -> None:
    legacy = SessionCheckpoint(session_id="owner:agent:legacy")
    already_durable = SessionCheckpoint(session_id="owner:agent:durable")
    hot = _Hot()
    hot.items = {
        legacy.session_id: legacy,
        already_durable.session_id: already_durable,
    }

    class _ManyDurable(_Durable):
        def __init__(self):
            super().__init__()
            self.items = {already_durable.session_id: already_durable}

        async def get_checkpoint(self, session_id):
            return self.items.get(session_id)

        async def save_checkpoint(self, checkpoint):
            self.items[checkpoint.session_id] = checkpoint

    durable = _ManyDurable()
    store = HybridSessionStore(durable, hot)

    migrated = await store.migrate_hot_checkpoints()

    assert migrated == 1
    assert durable.items == {
        already_durable.session_id: already_durable,
        legacy.session_id: legacy,
    }
    assert hot.events == ["hot:list"]
