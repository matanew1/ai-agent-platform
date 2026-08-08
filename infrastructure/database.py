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

_SERVER_SELECTION_TIMEOUT_MS = 5_000


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
        """Open and verify the connection pool at application startup.

        Motor connects lazily by default.  Explicitly pinging here turns an
        invalid URI or unavailable MongoDB instance into a clear startup
        failure instead of deferring it to the first agent-definition call.
        """
        client = AsyncIOMotorClient(
            self._connection_uri,
            serverSelectionTimeoutMS=_SERVER_SELECTION_TIMEOUT_MS,
        )
        try:
            await client.admin.command("ping")
        except Exception as exc:
            client.close()
            raise DatabaseError(f"Failed to connect to MongoDB: {exc}") from exc
        self._client = client
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
        # Filter keys, not values - a filter value can be a lookup on
        # sensitive data (email, user id, ...).
        logger.debug("find_one: collection=%r query_keys=%s", collection, list(query.keys()))
        try:
            return await self._db[collection].find_one(query)
        except Exception as exc:
            raise DatabaseError(f"Failed to fetch document from {collection!r}: {exc}") from exc

    async def insert_one(self, collection: str, document: dict[str, Any]) -> str:
        """Insert a single document.

        Args:
            collection: Collection name.
            document: Document to insert.

        Returns:
            The inserted document's id, as a string.
        """
        logger.debug("insert_one: collection=%r", collection)
        try:
            result = await self._db[collection].insert_one(document)
        except Exception as exc:
            raise DatabaseError(f"Failed to insert document into {collection!r}: {exc}") from exc
        return str(result.inserted_id)

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
        logger.debug("update_one: collection=%r query_keys=%s", collection, list(query.keys()))
        try:
            result = await self._db[collection].update_one(query, update)
        except Exception as exc:
            raise DatabaseError(f"Failed to update document in {collection!r}: {exc}") from exc
        return result.matched_count > 0

    async def find_many(self, collection: str, query: dict[str, Any]) -> list[dict[str, Any]]:
        """Fetch every document matching a filter.

        Args:
            collection: Collection name.
            query: MongoDB filter document.

        Returns:
            Matching documents in the collection's natural order.
        """
        logger.debug("find_many: collection=%r query_keys=%s", collection, list(query.keys()))
        try:
            return await self._db[collection].find(query).to_list(length=None)
        except Exception as exc:
            raise DatabaseError(f"Failed to list documents from {collection!r}: {exc}") from exc

    async def delete_one(self, collection: str, query: dict[str, Any]) -> bool:
        """Delete one document matching a filter.

        Args:
            collection: Collection name.
            query: MongoDB filter document.

        Returns:
            ``True`` when a document was deleted, otherwise ``False``.
        """
        logger.debug("delete_one: collection=%r query_keys=%s", collection, list(query.keys()))
        try:
            result = await self._db[collection].delete_one(query)
        except Exception as exc:
            raise DatabaseError(f"Failed to delete document from {collection!r}: {exc}") from exc
        return result.deleted_count > 0
