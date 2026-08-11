"""Shared SQLAlchemy PostgreSQL engine, sessions, and metadata."""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from infrastructure.database.protocol import Database
from infrastructure.errors import DatabaseError
from shared.implements import implements

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Common SQLAlchemy metadata registry used by Alembic migrations."""


@implements(Database)
class PostgresDatabase:
    """Create a pooled PostgreSQL engine and sessions for module repositories."""

    def __init__(self, database_url: str) -> None:
        self._engine = create_async_engine(database_url, pool_pre_ping=True)
        self.session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def connect(self) -> None:
        """Verify PostgreSQL availability during application startup."""
        try:
            async with self._engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception as exc:
            raise DatabaseError(f"Failed to connect to PostgreSQL: {exc}") from exc
        logger.debug("PostgreSQL connection pool is ready")

    async def close(self) -> None:
        """Dispose all pooled PostgreSQL connections at shutdown."""
        await self._engine.dispose()
        logger.debug("PostgreSQL connection pool closed")


__all__ = ["AsyncSession", "Base", "PostgresDatabase", "async_sessionmaker"]
