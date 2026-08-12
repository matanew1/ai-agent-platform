"""Unit tests for PostgreSQL connection startup behavior."""

from __future__ import annotations

import pytest

from infrastructure.database.postgres import PostgresDatabase
from infrastructure.errors import DatabaseError


class _Connection:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.statements: list[str] = []

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, statement: object) -> None:
        self.statements.append(str(statement))
        if self.failure is not None:
            raise self.failure


class _Engine:
    def __init__(self, failure: Exception | None = None) -> None:
        self.connection = _Connection(failure)
        self.disposed = False

    def connect(self) -> _Connection:
        return self.connection

    async def dispose(self) -> None:
        self.disposed = True


async def test_connect_runs_a_postgresql_health_query(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _Engine()
    monkeypatch.setattr(
        "infrastructure.database.postgres.create_async_engine", lambda *_args, **_kwargs: engine
    )
    database = PostgresDatabase("postgresql+asyncpg://localhost/platform")

    await database.connect()
    await database.close()

    assert engine.connection.statements == ["SELECT 1"]
    assert engine.disposed is True


async def test_connect_translates_postgresql_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _Engine(RuntimeError("connection refused"))
    monkeypatch.setattr(
        "infrastructure.database.postgres.create_async_engine", lambda *_args, **_kwargs: engine
    )
    database = PostgresDatabase("postgresql+asyncpg://localhost/platform")

    with pytest.raises(DatabaseError, match="Failed to connect to PostgreSQL"):
        await database.connect()

    assert engine.disposed is True
