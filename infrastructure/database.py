"""MongoDB adapter: connection lifecycle and basic document operations.

Wraps ``motor`` (the async MongoDB driver) behind a small, module-agnostic
interface. No business logic lives here - callers get back plain dicts and
decide what to do with them.
"""

from __future__ import annotations

import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from shared.types import PlatformError

logger = logging.getLogger(__name__)


class DatabaseError(PlatformError):
    """Raised when a MongoDB operation fails."""


class MongoDatabase:
    """Async MongoDB connection and basic CRUD operations.

    Args:
        connection_uri: MongoDB connection string
            (e.g. ``mongodb://localhost:27017``).
        database_name: Name of the database to operate against.
    """

    def __init__(self, connection_uri: str, database_name: str) -> None:
        self._connection_uri = connection_uri
        self._database_name = database_name
        self._client: AsyncIOMotorClient | None = None

    @property
    def _db(self) -> AsyncIOMotorDatabase:
        if self._client is None:
            raise DatabaseError("MongoDatabase.connect() was not called before use.")
        return self._client[self._database_name]

    async def connect(self) -> None:
        """Open the connection pool. Call once at app startup."""
        # TODO: add server-selection timeout + ping-on-connect health check.
        self._client = AsyncIOMotorClient(self._connection_uri)
        logger.debug("MongoDatabase connected: database=%r", self._database_name)

    async def close(self) -> None:
        """Close the connection pool. Call once at app shutdown."""
        if self._client is not None:
            self._client.close()
            self._client = None
            logger.debug("MongoDatabase connection closed")

    async def find_one(self, collection: str, query: dict[str, Any]) -> dict[str, Any] | None:
        """Fetch a single document.

        Args:
            collection: Collection name.
            query: MongoDB filter document.

        Returns:
            The matching document, or ``None`` if no document matches.
        """
        # TODO: implement once a real collection schema exists.
        # Filter keys, not values - a filter value can be a lookup on
        # sensitive data (email, user id, ...).
        logger.debug("find_one: collection=%r query_keys=%s", collection, list(query.keys()))
        raise NotImplementedError

    async def insert_one(self, collection: str, document: dict[str, Any]) -> str:
        """Insert a single document.

        Args:
            collection: Collection name.
            document: Document to insert.

        Returns:
            The inserted document's id, as a string.
        """
        # TODO: implement once a real collection schema exists.
        logger.debug("insert_one: collection=%r", collection)
        raise NotImplementedError

    async def update_one(
        self, collection: str, query: dict[str, Any], update: dict[str, Any]
    ) -> bool:
        """Update a single document.

        Args:
            collection: Collection name.
            query: MongoDB filter document identifying the target.
            update: MongoDB update document (e.g. ``{"$set": {...}}``).

        Returns:
            ``True`` if a document was matched and updated, else ``False``.
        """
        # TODO: implement once a real collection schema exists.
        logger.debug("update_one: collection=%r query_keys=%s", collection, list(query.keys()))
        raise NotImplementedError
