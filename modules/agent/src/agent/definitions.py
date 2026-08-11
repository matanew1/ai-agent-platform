"""Versioned, owner-scoped agent-definition management.

Separate from ``agent.service`` (turn *execution*) on purpose - this is
turn *configuration*: create/read/update/delete the prompt/tool-allowlist
that ``agent.runtime.AgentRuntimeFactory`` turns into a running
``AgentService`` per definition. Two responsibilities, two files (SRP).
"""

from __future__ import annotations

from datetime import UTC, datetime

from agent.ports import AgentDefinitionRepository, ModelCatalog, ToolRegistry
from shared.types import AgentDefinition


class _UnsetType:
    """Sentinel distinguishing an omitted update from an explicit ``None``."""


_UNSET = _UnsetType()


class AgentDefinitionService:
    """Manage versioned agent configurations in authenticated-user scopes."""

    def __init__(
        self,
        repository: AgentDefinitionRepository,
        tool_registry: ToolRegistry,
        model_catalog: ModelCatalog | None = None,
    ) -> None:
        self._repository = repository
        self._tool_registry = tool_registry
        self._model_catalog = model_catalog

    async def create(
        self,
        owner_id: str,
        name: str,
        system_prompt: str,
        allowed_tools: list[str],
        description: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
    ) -> AgentDefinition:
        """Create an agent definition after validating its tool allowlist."""
        self._validate_tools(allowed_tools)
        await self._validate_model(model)
        return await self._repository.create(
            AgentDefinition(
                owner_id=owner_id,
                name=name,
                description=description,
                system_prompt=system_prompt,
                allowed_tools=allowed_tools,
                model=model,
                temperature=temperature,
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
        description: str | None | _UnsetType = _UNSET,
        system_prompt: str | None = None,
        allowed_tools: list[str] | None = None,
        model: str | None | _UnsetType = _UNSET,
        temperature: float | None | _UnsetType = _UNSET,
    ) -> AgentDefinition | None:
        """Apply a partial update and increment the definition version."""
        definition = await self._repository.get(owner_id, agent_id)
        if definition is None:
            return None
        if allowed_tools is not None:
            self._validate_tools(allowed_tools)
        # An existing definition can outlive a locally installed model while
        # an operator swaps Ollama images. Do not reject an unrelated edit
        # merely because a client round-trips that unchanged model value.
        if model is not _UNSET and model != definition.model:
            await self._validate_model(model)

        changes: dict[str, object] = {
            key: value
            for key, value in {
                "name": name,
                "system_prompt": system_prompt,
                "allowed_tools": allowed_tools,
            }.items()
            if value is not None
        }
        if description is not _UNSET:
            changes["description"] = description
        if model is not _UNSET:
            changes["model"] = model
        if temperature is not _UNSET:
            changes["temperature"] = temperature
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

    async def _validate_model(self, model: str | None | _UnsetType) -> None:
        if model is None or model is _UNSET or self._model_catalog is None:
            return
        snapshot = await self._model_catalog.available_models()
        if snapshot.authoritative and model not in snapshot.models:
            available = ", ".join(snapshot.models) or "none"
            raise ValueError(
                f"Model {model!r} is not an available {self._model_catalog.provider_name} "
                f"chat model. Available models: {available}."
            )
