"""HTTP contract tests for the unauthenticated agent-definition routes."""

from __future__ import annotations

from agents.api.router import router
from agents.service import AgentDefinitionService
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.types import AgentDefinition, ToolDefinition


class _Repository:
    def __init__(self) -> None:
        self.items: dict[str, AgentDefinition] = {}

    async def create(self, definition: AgentDefinition) -> AgentDefinition:
        self.items[definition.id] = definition
        return definition

    async def get(self, owner_id: str, agent_id: str) -> AgentDefinition | None:
        item = self.items.get(agent_id)
        return item if item is not None and item.owner_id == owner_id else None

    async def list(self, owner_id: str) -> list[AgentDefinition]:
        return [item for item in self.items.values() if item.owner_id == owner_id]

    async def save(self, definition: AgentDefinition) -> bool:
        self.items[definition.id] = definition
        return True

    async def delete(self, owner_id: str, agent_id: str) -> bool:
        if await self.get(owner_id, agent_id) is None:
            return False
        del self.items[agent_id]
        return True


class _ToolRegistry:
    def get_tools(self) -> list[ToolDefinition]:
        return [ToolDefinition(name="fetch", description="Fetches a URL.")]


def _client() -> TestClient:
    app = FastAPI()
    app.state.agent_definition_service = AgentDefinitionService(_Repository(), _ToolRegistry())
    app.include_router(router)
    return TestClient(app)


def test_agent_routes_require_owner_id_but_no_bearer_token() -> None:
    client = _client()

    missing_owner = client.get("/agents")
    created = client.post(
        "/agents",
        json={"owner_id": "local-dev", "name": "Researcher", "allowed_tools": ["fetch"]},
    )
    listed = client.get("/agents", params={"owner_id": "local-dev"})

    assert missing_owner.status_code == 422
    assert created.status_code == 201
    assert listed.status_code == 200
    assert [agent["name"] for agent in listed.json()] == ["Researcher"]
