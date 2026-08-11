"""Tests for Mongo-durable sessions backed by a Redis hot layer."""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from infrastructure.redis import RedisError
from infrastructure.sessions import HybridSessionStore, MongoSessionRepository
from shared.types import SessionCheckpoint


class _Database:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, object]] = {}
        self.queries: list[dict[str, object]] = []
        self.indexes: list[tuple[object, bool, str | None]] = []

    async def create_index(self, _collection, keys, *, unique=False, name=None):
        self.indexes.append((keys, unique, name))
        return name or "index"

    async def find_one(self, _collection, query):
        return self.documents.get(query["session_id"])

    async def replace_one(self, _collection, query, document, *, upsert=False):
        assert upsert is True
        self.documents[query["session_id"]] = document
        return True

    async def find_many(self, _collection, query):
        self.queries.append(query)
        pattern = query["session_id"]["$regex"]
        return [document for key, document in self.documents.items() if re.match(pattern, key)]

    async def delete_one(self, _collection, query):
        return self.documents.pop(query["session_id"], None) is not None


class _Hot:
    def __init__(self) -> None:
        self.items: dict[str, SessionCheckpoint] = {}
        self.events: list[str] = []
        self.fail_save = False

    async def get_checkpoint(self, session_id):
        self.events.append("hot:get")
        return self.items.get(session_id)

    async def save_checkpoint(self, checkpoint):
        self.events.append("hot:save")
        if self.fail_save:
            raise RedisError("offline")
        self.items[checkpoint.session_id] = checkpoint

    async def delete_checkpoint(self, session_id):
        self.events.append("hot:delete")
        return self.items.pop(session_id, None) is not None

    @asynccontextmanager
    async def session_lock(self, _session_id):
        self.events.append("lock:enter")
        yield
        self.events.append("lock:exit")


class _Durable:
    def __init__(self, checkpoint: SessionCheckpoint | None = None) -> None:
        self.checkpoint = checkpoint
        self.events: list[str] = []

    async def get_checkpoint(self, _session_id):
        self.events.append("mongo:get")
        return self.checkpoint

    async def save_checkpoint(self, checkpoint):
        self.events.append("mongo:save")
        self.checkpoint = checkpoint

    async def list_checkpoints(self, _prefix):
        self.events.append("mongo:list")
        return [self.checkpoint] if self.checkpoint else []

    async def delete_checkpoint(self, _session_id):
        self.events.append("mongo:delete")
        existed = self.checkpoint is not None
        self.checkpoint = None
        return existed


async def test_mongo_repository_persists_lists_and_deletes_literal_prefixes() -> None:
    database = _Database()
    repository = MongoSessionRepository(database)
    older = SessionCheckpoint(
        session_id="owner.*:agent:old",
        updated_at=datetime(2026, 8, 9, tzinfo=UTC),
    )
    newer = SessionCheckpoint(
        session_id="owner.*:agent:new",
        updated_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    hidden = SessionCheckpoint(session_id="owner-else:agent:hidden")

    await repository.ensure_indexes()
    for checkpoint in (older, newer, hidden):
        await repository.save_checkpoint(checkpoint)

    listed = await repository.list_checkpoints("owner.*:agent:")

    assert [item.session_id for item in listed] == [newer.session_id, older.session_id]
    assert database.queries == [{"session_id": {"$regex": r"^owner\.\*:agent:"}}]
    assert database.indexes[0] == ("session_id", True, "session_id_unique")
    assert await repository.delete_checkpoint(older.session_id) is True
    assert await repository.get_checkpoint(older.session_id) is None


async def test_hybrid_store_reads_hot_then_falls_back_to_mongo_and_repopulates() -> None:
    checkpoint = SessionCheckpoint(session_id="owner:agent:session")
    hot = _Hot()
    durable = _Durable(checkpoint)
    store = HybridSessionStore(durable, hot)

    assert await store.get_checkpoint(checkpoint.session_id) == checkpoint
    assert durable.events == ["mongo:get"]
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
    assert durable.events == ["mongo:save"]
    assert checkpoint.session_id not in hot.items
    assert durable.checkpoint == checkpoint


async def test_hybrid_lists_from_mongo_and_deletes_under_the_redis_lock() -> None:
    checkpoint = SessionCheckpoint(session_id="owner:agent:session")
    hot = _Hot()
    durable = _Durable(checkpoint)
    store = HybridSessionStore(durable, hot)

    assert await store.list_checkpoints("owner:agent:") == [checkpoint]
    assert await store.delete_checkpoint(checkpoint.session_id) is True
    assert durable.events == ["mongo:list", "mongo:delete"]
    assert hot.events == ["lock:enter", "hot:delete", "lock:exit"]
