"""Authenticated HTTP contract coverage for owner-scoped agent schedules."""

from __future__ import annotations

from datetime import datetime

from authentication.repository import SESSION_COOKIE_NAME, SessionResult
from automation.controller import router
from automation.repository import ScheduleRepository
from automation.schemas import AgentSchedule
from automation.service import ScheduleService
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.auth import AuthenticatedUser, AuthenticationError
from shared.types import Agent


class _Authenticator:
    async def authenticate_session(self, sealed_session: str | None) -> SessionResult:
        if sealed_session is None:
            raise AuthenticationError("No session cookie was provided.")
        return SessionResult(
            user=AuthenticatedUser(id=sealed_session), sealed_session=sealed_session
        )


class _AgentService:
    def __init__(self) -> None:
        self.agents: dict[str, Agent] = {}

    async def get(self, owner_id: str, agent_id: str) -> Agent | None:
        agent = self.agents.get(agent_id)
        return agent if agent is not None and agent.owner_id == owner_id else None


class _ScheduleRepository(ScheduleRepository):
    """In-memory stand-in satisfying the same interface as the real repository."""

    def __init__(self) -> None:
        self.by_id: dict[str, AgentSchedule] = {}

    async def create(self, schedule: AgentSchedule) -> AgentSchedule:
        self.by_id[schedule.id] = schedule
        return schedule

    async def get(self, owner_id: str, schedule_id: str) -> AgentSchedule | None:
        schedule = self.by_id.get(schedule_id)
        return schedule if schedule is not None and schedule.owner_id == owner_id else None

    async def list_for_agent(self, owner_id: str, agent_id: str) -> list[AgentSchedule]:
        return [
            schedule
            for schedule in self.by_id.values()
            if schedule.owner_id == owner_id and schedule.agent_id == agent_id
        ]

    async def save(self, schedule: AgentSchedule) -> bool:
        if schedule.id not in self.by_id:
            return False
        self.by_id[schedule.id] = schedule
        return True

    async def delete(self, owner_id: str, schedule_id: str) -> bool:
        if await self.get(owner_id, schedule_id) is None:
            return False
        del self.by_id[schedule_id]
        return True

    async def due(self, now: datetime) -> list[AgentSchedule]:
        return []


def _client() -> tuple[TestClient, _AgentService, dict[str, str]]:
    app = FastAPI()
    agent_service = _AgentService()
    agent = Agent(
        id="agent-1",
        owner_id="owner-1",
        name="Daily Digest",
        system_prompt="Summarize.",
        allowed_tools=["fetch", "extract_pdf"],
    )
    other_owner_agent = Agent(
        id="agent-2", owner_id="owner-2", name="Someone else's", system_prompt="Summarize."
    )
    agent_service.agents = {agent.id: agent, other_owner_agent.id: other_owner_agent}
    app.state.agent_service = agent_service
    app.state.schedule_service = ScheduleService(repository=_ScheduleRepository())
    app.state.authenticator = _Authenticator()
    app.include_router(router)
    ids = {"owned": agent.id, "not_owned": other_owner_agent.id, "missing": "no-such-agent"}
    return TestClient(app, cookies={SESSION_COOKIE_NAME: "owner-1"}), agent_service, ids


def test_schedule_routes_require_a_session_cookie() -> None:
    app = FastAPI()
    app.state.agent_service = _AgentService()
    app.state.schedule_service = ScheduleService(repository=_ScheduleRepository())
    app.state.authenticator = _Authenticator()
    app.include_router(router)
    anonymous = TestClient(app)

    assert anonymous.get("/agents/agent-1/schedules").status_code == 401


def test_schedule_routes_404_for_an_agent_the_caller_does_not_own() -> None:
    client, _agent_service, ids = _client()
    valid_create_body = {
        "title": "Daily digest",
        "cron_expression": "0 8 * * *",
        "trigger_message": "hi",
    }

    for path, method, body in (
        ("", "GET", {}),
        ("", "POST", valid_create_body),
        ("/missing-id", "GET", {}),
        ("/missing-id", "PATCH", {"enabled": False}),
        ("/missing-id", "DELETE", {}),
    ):
        for agent_id in (ids["not_owned"], ids["missing"]):
            response = client.request(method, f"/agents/{agent_id}/schedules{path}", json=body)
            assert response.status_code == 404, f"{method} {agent_id}{path}"


def test_create_schedule_rejects_an_invalid_cron_expression() -> None:
    client, _agent_service, ids = _client()

    response = client.post(
        f"/agents/{ids['owned']}/schedules",
        json={"title": "Daily digest", "cron_expression": "not a cron", "trigger_message": "hi"},
    )

    assert response.status_code == 422


def test_create_schedule_rejects_a_tool_the_agent_is_not_allowed() -> None:
    client, _agent_service, ids = _client()

    response = client.post(
        f"/agents/{ids['owned']}/schedules",
        json={
            "title": "Daily digest",
            "cron_expression": "0 8 * * *",
            "trigger_message": "hi",
            "tools": ["fetch", "shell_exec"],
        },
    )

    assert response.status_code == 422
    assert "shell_exec" in response.json()["detail"]


def test_schedule_tools_are_unrestricted_for_an_agent_with_no_tool_allowlist() -> None:
    # An agent's own empty allowed_tools means "no restriction" (see
    # graph.graph._execute_tools's `if state.allowed_tools:` falsy-skip) -
    # a schedule narrowing tools for such an agent has no fixed universe to
    # be a "subset" of, so any selection is valid.
    client, agent_service, _ids = _client()
    unrestricted_agent = Agent(
        id="agent-unrestricted", owner_id="owner-1", name="Unrestricted", system_prompt="Go."
    )
    agent_service.agents[unrestricted_agent.id] = unrestricted_agent

    response = client.post(
        f"/agents/{unrestricted_agent.id}/schedules",
        json={
            "title": "Daily digest",
            "cron_expression": "0 8 * * *",
            "trigger_message": "hi",
            "tools": ["anything_at_all"],
        },
    )

    assert response.status_code == 201


def test_create_list_update_and_delete_a_schedule_round_trip() -> None:
    client, _agent_service, ids = _client()
    agent_id = ids["owned"]

    created = client.post(
        f"/agents/{agent_id}/schedules",
        json={
            "title": "Daily digest",
            "description": "Summarizes yesterday's activity every morning.",
            "cron_expression": "0 8 * * *",
            "trigger_message": "Summarize yesterday.",
            "tools": ["fetch"],
        },
    )
    assert created.status_code == 201
    schedule_id = created.json()["id"]
    assert created.json()["enabled"] is True
    assert created.json()["title"] == "Daily digest"
    assert created.json()["description"] == "Summarizes yesterday's activity every morning."
    assert created.json()["tools"] == ["fetch"]

    listed = client.get(f"/agents/{agent_id}/schedules")
    assert [item["id"] for item in listed.json()] == [schedule_id]

    fetched = client.get(f"/agents/{agent_id}/schedules/{schedule_id}")
    assert fetched.status_code == 200
    assert fetched.json()["cron_expression"] == "0 8 * * *"

    updated = client.patch(
        f"/agents/{agent_id}/schedules/{schedule_id}",
        json={"enabled": False, "title": "Daily digest (paused)"},
    )
    assert updated.status_code == 200
    assert updated.json()["enabled"] is False
    assert updated.json()["title"] == "Daily digest (paused)"

    cleared = client.patch(
        f"/agents/{agent_id}/schedules/{schedule_id}", json={"tools": None, "description": None}
    )
    assert cleared.status_code == 200
    assert cleared.json()["tools"] is None
    assert cleared.json()["description"] is None

    rejected = client.patch(
        f"/agents/{agent_id}/schedules/{schedule_id}", json={"tools": ["shell_exec"]}
    )
    assert rejected.status_code == 422

    deleted = client.delete(f"/agents/{agent_id}/schedules/{schedule_id}")
    assert deleted.status_code == 204
    assert client.get(f"/agents/{agent_id}/schedules/{schedule_id}").status_code == 404


def test_update_can_move_a_schedule_to_a_different_owned_agent() -> None:
    client, agent_service, ids = _client()
    source_agent_id = ids["owned"]
    target_agent = Agent(
        id="agent-target",
        owner_id="owner-1",
        name="Target agent",
        system_prompt="Go.",
        allowed_tools=["fetch"],
    )
    agent_service.agents[target_agent.id] = target_agent

    created = client.post(
        f"/agents/{source_agent_id}/schedules",
        json={"title": "Daily digest", "cron_expression": "0 8 * * *", "trigger_message": "hi"},
    )
    schedule_id = created.json()["id"]

    moved = client.patch(
        f"/agents/{source_agent_id}/schedules/{schedule_id}",
        json={"agent_id": target_agent.id},
    )

    assert moved.status_code == 200
    assert moved.json()["agent_id"] == target_agent.id
    # No longer reachable under the old agent...
    assert client.get(f"/agents/{source_agent_id}/schedules/{schedule_id}").status_code == 404
    assert client.get(f"/agents/{source_agent_id}/schedules").json() == []
    # ...but is under the new one.
    assert client.get(f"/agents/{target_agent.id}/schedules/{schedule_id}").status_code == 200
    assert [item["id"] for item in client.get(f"/agents/{target_agent.id}/schedules").json()] == [
        schedule_id
    ]


def test_update_rejects_moving_a_schedule_to_an_agent_the_caller_does_not_own() -> None:
    client, _agent_service, ids = _client()
    created = client.post(
        f"/agents/{ids['owned']}/schedules",
        json={"title": "Daily digest", "cron_expression": "0 8 * * *", "trigger_message": "hi"},
    )
    schedule_id = created.json()["id"]

    response = client.patch(
        f"/agents/{ids['owned']}/schedules/{schedule_id}",
        json={"agent_id": ids["not_owned"]},
    )

    assert response.status_code == 404
    # The schedule wasn't moved.
    assert client.get(f"/agents/{ids['owned']}/schedules/{schedule_id}").status_code == 200


def test_update_resets_incompatible_tools_instead_of_blocking_a_move() -> None:
    client, agent_service, ids = _client()
    source_agent_id = ids["owned"]  # allowed_tools=["fetch", "extract_pdf"]
    restrictive_agent = Agent(
        id="agent-restrictive",
        owner_id="owner-1",
        name="Restrictive",
        system_prompt="Go.",
        allowed_tools=["extract_pdf"],  # doesn't include "fetch"
    )
    agent_service.agents[restrictive_agent.id] = restrictive_agent

    created = client.post(
        f"/agents/{source_agent_id}/schedules",
        json={
            "title": "Daily digest",
            "cron_expression": "0 8 * * *",
            "trigger_message": "hi",
            "tools": ["fetch"],
        },
    )
    schedule_id = created.json()["id"]

    moved = client.patch(
        f"/agents/{source_agent_id}/schedules/{schedule_id}",
        json={"agent_id": restrictive_agent.id},
    )

    assert moved.status_code == 200
    assert moved.json()["agent_id"] == restrictive_agent.id
    assert moved.json()["tools"] is None


def test_a_schedule_is_not_reachable_through_a_sibling_agent_it_does_not_belong_to() -> None:
    client, agent_service, ids = _client()
    owned_agent_id = ids["owned"]
    # Give the caller a second, owned agent so the schedule's owner_id check
    # passes but its agent_id check must still catch the mismatch.
    second_agent = Agent(
        id="agent-3", owner_id="owner-1", name="Second agent", system_prompt="Summarize."
    )
    agent_service.agents[second_agent.id] = second_agent

    created = client.post(
        f"/agents/{owned_agent_id}/schedules",
        json={"title": "Daily digest", "cron_expression": "0 8 * * *", "trigger_message": "hi"},
    )
    schedule_id = created.json()["id"]

    for path, method in (("", "GET"), ("", "PATCH"), ("", "DELETE")):
        response = client.request(
            method, f"/agents/{second_agent.id}/schedules/{schedule_id}{path}", json={}
        )
        assert response.status_code == 404, f"{method} via sibling agent"
