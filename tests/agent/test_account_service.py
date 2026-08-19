"""Unit tests for authentication.account_service.AccountService.

Lives alongside the other agent-adjacent unit tests (see tests/agent/) since
it's the same fake-per-port shape as agent.draft_service's tests, just
composing more of them - no real PostgreSQL/Redis/Qdrant involved.
"""

from __future__ import annotations

from datetime import UTC, datetime

from authentication.account_service import AccountService
from automation.schemas import AgentSchedule

from shared.types import Agent, SessionCheckpoint

_NEXT_RUN = datetime(2026, 1, 1, tzinfo=UTC)


class FakeAgentService:
    def __init__(self, agents: list[Agent]) -> None:
        self._agents = {agent.id: agent for agent in agents}
        self.deleted: list[tuple[str, str]] = []

    async def list(self, owner_id: str) -> list[Agent]:
        return [agent for agent in self._agents.values() if agent.owner_id == owner_id]

    async def delete(self, owner_id: str, agent_id: str) -> bool:
        self.deleted.append((owner_id, agent_id))
        existed = agent_id in self._agents
        self._agents.pop(agent_id, None)
        return existed


class FakeSessionMemory:
    def __init__(self, checkpoints: list[SessionCheckpoint]) -> None:
        self._checkpoints = {checkpoint.session_id: checkpoint for checkpoint in checkpoints}
        self.deleted: list[str] = []

    async def list_checkpoints(self, session_prefix: str) -> list[SessionCheckpoint]:
        return [
            checkpoint
            for session_id, checkpoint in self._checkpoints.items()
            if session_id.startswith(session_prefix)
        ]

    async def delete_checkpoint(self, session_id: str) -> bool:
        self.deleted.append(session_id)
        return self._checkpoints.pop(session_id, None) is not None


class FakeRagService:
    def __init__(self) -> None:
        self.deleted_filters: list[dict[str, str]] = []

    async def delete_document(self, metadata_filter: dict[str, str]) -> bool:
        self.deleted_filters.append(metadata_filter)
        return True


class FakeScheduleService:
    def __init__(self, schedules: list[AgentSchedule]) -> None:
        self._schedules = {schedule.id: schedule for schedule in schedules}
        self.deleted: list[tuple[str, str]] = []

    async def list_for_agent(self, owner_id: str, agent_id: str) -> list[AgentSchedule]:
        return [
            schedule
            for schedule in self._schedules.values()
            if schedule.owner_id == owner_id and schedule.agent_id == agent_id
        ]

    async def delete(self, owner_id: str, schedule_id: str) -> bool:
        self.deleted.append((owner_id, schedule_id))
        existed = schedule_id in self._schedules
        self._schedules.pop(schedule_id, None)
        return existed


async def test_delete_all_owned_data_scopes_to_the_owner_s_own_agents() -> None:
    mine = Agent(id="a1", owner_id="owner-1", name="Mine", system_prompt="hi")
    someone_elses = Agent(id="a2", owner_id="owner-2", name="Not mine", system_prompt="hi")
    agent_service = FakeAgentService([mine, someone_elses])
    session_memory = FakeSessionMemory(
        [
            SessionCheckpoint(session_id="owner-1:a1:s1"),
            SessionCheckpoint(session_id="owner-1:a1:s2"),
            SessionCheckpoint(session_id="owner-2:a2:s1"),
        ]
    )
    rag_service = FakeRagService()
    schedule_service = FakeScheduleService(
        [
            AgentSchedule(
                id="sched-1",
                owner_id="owner-1",
                agent_id="a1",
                title="Daily digest",
                cron_expression="0 8 * * *",
                trigger_message="hi",
                next_run_at=_NEXT_RUN,
            ),
            AgentSchedule(
                id="sched-2",
                owner_id="owner-2",
                agent_id="a2",
                title="Daily digest",
                cron_expression="0 8 * * *",
                trigger_message="hi",
                next_run_at=_NEXT_RUN,
            ),
        ]
    )
    service = AccountService(agent_service, session_memory, rag_service, schedule_service)

    await service.delete_all_owned_data("owner-1")

    assert agent_service.deleted == [("owner-1", "a1")]
    assert sorted(session_memory.deleted) == ["owner-1:a1:s1", "owner-1:a1:s2"]
    assert schedule_service.deleted == [("owner-1", "sched-1")]
    assert rag_service.deleted_filters == [{"owner_id": "owner-1"}]


async def test_delete_all_owned_data_is_a_no_op_for_an_owner_with_nothing() -> None:
    agent_service = FakeAgentService([])
    session_memory = FakeSessionMemory([])
    rag_service = FakeRagService()
    schedule_service = FakeScheduleService([])
    service = AccountService(agent_service, session_memory, rag_service, schedule_service)

    await service.delete_all_owned_data("owner-1")

    assert agent_service.deleted == []
    assert session_memory.deleted == []
    assert schedule_service.deleted == []
    assert rag_service.deleted_filters == [{"owner_id": "owner-1"}]
