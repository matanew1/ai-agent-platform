"""Unit tests for MongoDatabase connection startup behavior."""

from __future__ import annotations

import pytest

from infrastructure.database import DatabaseError, MongoDatabase


class _Admin:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.commands: list[str] = []

    async def command(self, command: str) -> dict[str, int]:
        self.commands.append(command)
        if self.failure is not None:
            raise self.failure
        return {"ok": 1}


class _Client:
    def __init__(self, failure: Exception | None = None) -> None:
        self.admin = _Admin(failure)
        self.closed = False

    def close(self) -> None:
        self.closed = True


async def test_connect_pings_mongodb_before_marking_the_database_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client()
    captured: dict[str, object] = {}

    def build_client(uri: str, **kwargs: object) -> _Client:
        captured.update(uri=uri, **kwargs)
        return client

    monkeypatch.setattr("infrastructure.database.AsyncIOMotorClient", build_client)
    database = MongoDatabase("mongodb://localhost:27017", "platform")

    await database.connect()

    assert client.admin.commands == ["ping"]
    assert captured["serverSelectionTimeoutMS"] == 5_000
    assert database._client is client


async def test_connect_closes_client_and_raises_domain_error_when_ping_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client(RuntimeError("connection refused"))
    monkeypatch.setattr(
        "infrastructure.database.AsyncIOMotorClient", lambda *_args, **_kwargs: client
    )
    database = MongoDatabase("mongodb://localhost:27017", "platform")

    with pytest.raises(DatabaseError, match="Failed to connect to MongoDB"):
        await database.connect()

    assert client.closed is True
    assert database._client is None
