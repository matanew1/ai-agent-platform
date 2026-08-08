"""Tests for owner-scoped agent-definition management."""

from __future__ import annotations

from agents.service import AgentDefinitionService

from shared.types import AgentDefinition, ToolDefinition


class FakeRepository:
    """In-memory repository enforcing the same owner/id lookup semantics."""

    def __init__(self) -> None:
        self.definitions: dict[str, AgentDefinition] = {}

    async def create(self, definition: AgentDefinition) -> AgentDefinition:
        self.definitions[definition.id] = definition
        return definition

    async def get(self, owner_id: str, agent_id: str) -> AgentDefinition | None:
        definition = self.definitions.get(agent_id)
        return definition if definition and definition.owner_id == owner_id else None

    async def list(self, owner_id: str) -> list[AgentDefinition]:
        return [
            definition
            for definition in self.definitions.values()
            if definition.owner_id == owner_id
        ]

    async def save(self, definition: AgentDefinition) -> bool:
        if await self.get(definition.owner_id, definition.id) is None:
            return False
        self.definitions[definition.id] = definition
        return True

    async def delete(self, owner_id: str, agent_id: str) -> bool:
        if await self.get(owner_id, agent_id) is None:
            return False
        del self.definitions[agent_id]
        return True


class FakeToolRegistry:
    """Minimal tool catalogue used to validate configured allowlists."""

    def get_tools(self) -> list[ToolDefinition]:
        return [ToolDefinition(name="fetch", description="Fetches a URL.")]


def _service() -> AgentDefinitionService:
    """Build the service with isolated in-memory dependencies."""
    return AgentDefinitionService(repository=FakeRepository(), tool_registry=FakeToolRegistry())


async def test_create_definition_uses_owner_scope_and_validates_tools() -> None:
    """The caller cannot select tools that do not exist in the registry."""
    service = _service()

    definition = await service.create(
        owner_id="user-a",
        name="Researcher",
        system_prompt="Research carefully.",
        allowed_tools=["fetch"],
    )

    assert definition.owner_id == "user-a"
    assert definition.allowed_tools == ["fetch"]
    assert definition.version == 1


async def test_get_definition_does_not_leak_another_users_agent() -> None:
    """Owner scoping is applied by the service's repository calls."""
    service = _service()
    definition = await service.create("user-a", "Private", "Answer briefly.", [])

    assert await service.get("user-b", definition.id) is None


async def test_update_definition_increments_configuration_version() -> None:
    """Runtime cache keys can use the advanced version to avoid stale config."""
    service = _service()
    definition = await service.create("user-a", "Helper", "Be helpful.", [])

    updated = await service.update(
        "user-a", definition.id, name="Research helper", allowed_tools=["fetch"]
    )

    assert updated is not None
    assert updated.name == "Research helper"
    assert updated.allowed_tools == ["fetch"]
    assert updated.version == 2


async def test_unknown_tool_is_rejected_before_definition_is_saved() -> None:
    """A typo cannot become a silently unusable runtime configuration."""
    service = _service()

    try:
        await service.create("user-a", "Broken", "Be helpful.", ["does-not-exist"])
    except ValueError as exc:
        assert "Unknown tool names" in str(exc)
    else:
        raise AssertionError("Expected an unknown tool to be rejected")
