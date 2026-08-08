"""Versioned customizable-agent definition service."""

from __future__ import annotations

from datetime import UTC, datetime

from tool.registry import ToolRegistry

from agents.internal.ports import AgentDefinitionRepository
from shared.types import AgentDefinition


class AgentDefinitionService:
    """Manage versioned agent configurations in caller-provided owner scopes."""

    def __init__(self, repository: AgentDefinitionRepository, tool_registry: ToolRegistry) -> None:
        self._repository = repository
        self._tool_registry = tool_registry

    async def create(
        self, owner_id: str, name: str, system_prompt: str, allowed_tools: list[str]
    ) -> AgentDefinition:
        """Create an agent definition after validating its tool allowlist."""
        self._validate_tools(allowed_tools)
        return await self._repository.create(
            AgentDefinition(
                owner_id=owner_id,
                name=name,
                system_prompt=system_prompt,
                allowed_tools=allowed_tools,
            )
        )

    async def get(self, owner_id: str, agent_id: str) -> AgentDefinition | None:
        """Get a definition only when it belongs to the supplied owner scope."""
        return await self._repository.get(owner_id, agent_id)

    async def list(self, owner_id: str) -> list[AgentDefinition]:
        """List all definitions belonging to one owner scope."""
        return await self._repository.list(owner_id)

    async def update(
        self,
        owner_id: str,
        agent_id: str,
        *,
        name: str | None = None,
        system_prompt: str | None = None,
        allowed_tools: list[str] | None = None,
    ) -> AgentDefinition | None:
        """Apply a partial update and increment the definition version."""
        definition = await self._repository.get(owner_id, agent_id)
        if definition is None:
            return None
        if allowed_tools is not None:
            self._validate_tools(allowed_tools)

        changes = {
            key: value
            for key, value in {
                "name": name,
                "system_prompt": system_prompt,
                "allowed_tools": allowed_tools,
            }.items()
            if value is not None
        }
        if not changes:
            return definition
        updated = definition.model_copy(
            update={
                **changes,
                "version": definition.version + 1,
                "updated_at": datetime.now(UTC),
            }
        )
        await self._repository.save(updated)
        return updated

    async def delete(self, owner_id: str, agent_id: str) -> bool:
        """Delete a definition only when it belongs to the supplied owner scope."""
        return await self._repository.delete(owner_id, agent_id)

    def _validate_tools(self, allowed_tools: list[str]) -> None:
        """Reject duplicate and unavailable tools before saving configuration."""
        duplicates = {name for name in allowed_tools if allowed_tools.count(name) > 1}
        if duplicates:
            raise ValueError(f"Duplicate tool names are not allowed: {sorted(duplicates)}")
        registered_tools = {tool.name for tool in self._tool_registry.get_tools()}
        unknown_tools = sorted(set(allowed_tools) - registered_tools)
        if unknown_tools:
            raise ValueError(f"Unknown tool names: {unknown_tools}")
