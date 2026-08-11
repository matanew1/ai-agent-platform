"""MongoDB persistence for versioned user-owned agent definitions."""

from __future__ import annotations

from infrastructure.database import MongoDatabase
from shared.types import AgentDefinition

_COLLECTION = "agent_definitions"


class MongoAgentDefinitionRepository:
    """Persist agent definitions while always scoping mutations by owner."""

    def __init__(self, database: MongoDatabase) -> None:
        self._database = database

    async def create(self, definition: AgentDefinition) -> AgentDefinition:
        """Insert one complete agent definition."""
        await self._database.insert_one(_COLLECTION, definition.model_dump(mode="json"))
        return definition

    async def get(self, owner_id: str, agent_id: str) -> AgentDefinition | None:
        """Find one definition only if it belongs to ``owner_id``."""
        document = await self._database.find_one(
            _COLLECTION, {"id": agent_id, "owner_id": owner_id}
        )
        return _to_definition(document) if document else None

    async def list(self, owner_id: str) -> list[AgentDefinition]:
        """List every definition belonging to ``owner_id``."""
        documents = await self._database.find_many(_COLLECTION, {"owner_id": owner_id})
        return sorted(
            (_to_definition(document) for document in documents),
            key=lambda definition: definition.updated_at,
            reverse=True,
        )

    async def save(self, definition: AgentDefinition) -> bool:
        """Update a definition, matching both its id and owner."""
        update_fields = definition.model_dump(mode="json", exclude={"id", "owner_id", "created_at"})
        return await self._database.update_one(
            _COLLECTION,
            {"id": definition.id, "owner_id": definition.owner_id},
            {"$set": update_fields},
        )

    async def delete(self, owner_id: str, agent_id: str) -> bool:
        """Delete a definition only if it belongs to ``owner_id``."""
        return await self._database.delete_one(_COLLECTION, {"id": agent_id, "owner_id": owner_id})


def _to_definition(document: dict[str, object]) -> AgentDefinition:
    """Validate a Mongo document after removing its storage-only ``_id`` field."""
    definition_document = {key: value for key, value in document.items() if key != "_id"}
    return AgentDefinition.model_validate(definition_document)
