"""Tests for owner-scoped agent-definition management."""

from __future__ import annotations

from agent.definitions import AgentDefinitionService

from shared.types import AgentDefinition, ModelCatalogSnapshot, ToolDefinition


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


class FakeModelCatalog:
    """Configurable model inventory for definition-validation tests."""

    provider_name = "ollama"
    default_model = "qwen3:8b"
    default_temperature = 0.3

    def __init__(self, models: tuple[str, ...], *, authoritative: bool) -> None:
        self._snapshot = ModelCatalogSnapshot(models=models, authoritative=authoritative)

    async def available_models(self) -> ModelCatalogSnapshot:
        return self._snapshot


def _service(model_catalog: FakeModelCatalog | None = None) -> AgentDefinitionService:
    """Build the service with isolated in-memory dependencies."""
    return AgentDefinitionService(
        repository=FakeRepository(),
        tool_registry=FakeToolRegistry(),
        model_catalog=model_catalog,
    )


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


async def test_model_options_are_persisted_and_can_be_cleared() -> None:
    """Per-agent generation overrides participate in definition versioning."""
    service = _service()
    definition = await service.create(
        "user-a",
        "Helper",
        "Be helpful.",
        [],
        description="Answers technical questions.",
        model="qwen3:14b",
        temperature=0.3,
    )

    assert definition.description == "Answers technical questions."
    assert definition.model == "qwen3:14b"
    assert definition.temperature == 0.3

    updated = await service.update(
        "user-a",
        definition.id,
        description=None,
        model=None,
        temperature=None,
    )

    assert updated is not None
    assert updated.description is None
    assert updated.model is None
    assert updated.temperature is None
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


async def test_authoritative_catalog_rejects_an_unavailable_model() -> None:
    service = _service(FakeModelCatalog(("qwen3:8b",), authoritative=True))

    try:
        await service.create(
            "user-a",
            "Broken",
            "Be helpful.",
            [],
            model="not-installed:latest",
        )
    except ValueError as exc:
        assert "not an available ollama chat model" in str(exc)
        assert "qwen3:8b" in str(exc)
    else:
        raise AssertionError("Expected an unavailable model to be rejected")


async def test_authoritative_empty_catalog_rejects_even_the_configured_default() -> None:
    service = _service(FakeModelCatalog((), authoritative=True))

    try:
        await service.create(
            "user-a",
            "Missing model",
            "Be helpful.",
            [],
            model="qwen3:8b",
        )
    except ValueError as exc:
        assert "Available models: none" in str(exc)
    else:
        raise AssertionError("Expected an uninstalled default model to be rejected")


async def test_non_authoritative_fallback_does_not_block_agent_updates() -> None:
    service = _service(FakeModelCatalog(("qwen3:8b",), authoritative=False))
    definition = await service.create("user-a", "Helper", "Be helpful.", [])

    updated = await service.update(
        "user-a",
        definition.id,
        model="another-provider-native-model",
    )

    assert updated is not None
    assert updated.model == "another-provider-native-model"


async def test_unrelated_update_keeps_an_existing_model_removed_from_catalog() -> None:
    catalog = FakeModelCatalog(("qwen3:8b", "legacy:8b"), authoritative=True)
    service = _service(catalog)
    definition = await service.create(
        "user-a",
        "Helper",
        "Be helpful.",
        [],
        model="legacy:8b",
    )
    catalog._snapshot = ModelCatalogSnapshot(models=("qwen3:8b",), authoritative=True)

    updated = await service.update(
        "user-a",
        definition.id,
        system_prompt="Be concise.",
        model="legacy:8b",
    )

    assert updated is not None
    assert updated.model == "legacy:8b"
    assert updated.system_prompt == "Be concise."
