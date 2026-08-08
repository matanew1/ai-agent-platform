"""Ports owned by the public customizable-agent module."""

from __future__ import annotations

from typing import Protocol

from shared.types import AgentDefinition


class AgentDefinitionRepository(Protocol):
    """Persistence for caller-scoped agent definitions."""

    async def create(self, definition: AgentDefinition) -> AgentDefinition:
        """Persist a new agent definition."""
        ...

    async def get(self, owner_id: str, agent_id: str) -> AgentDefinition | None:
        """Fetch one definition only when it belongs to ``owner_id``."""
        ...

    async def list(self, owner_id: str) -> list[AgentDefinition]:
        """List definitions belonging to one owner scope."""
        ...

    async def save(self, definition: AgentDefinition) -> bool:
        """Persist an updated definition, matched by owner and id."""
        ...

    async def delete(self, owner_id: str, agent_id: str) -> bool:
        """Delete one definition belonging to the owner scope."""
        ...
