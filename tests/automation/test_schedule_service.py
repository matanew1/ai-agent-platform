"""Unit coverage for owner-scoped cron schedule configuration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from automation.schemas import AgentSchedule
from automation.service import InvalidCronExpressionError, ScheduleService


class _FakeScheduleRepository:
    """In-memory stand-in for ``automation.repository.ScheduleRepository``."""

    def __init__(self) -> None:
        self.by_id: dict[str, AgentSchedule] = {}

    async def create(self, schedule: AgentSchedule) -> AgentSchedule:
        self.by_id[schedule.id] = schedule
        return schedule

    async def get(self, owner_id: str, schedule_id: str) -> AgentSchedule | None:
        schedule = self.by_id.get(schedule_id)
        if schedule is None or schedule.owner_id != owner_id:
            return None
        return schedule

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
        schedule = self.by_id.get(schedule_id)
        if schedule is None or schedule.owner_id != owner_id:
            return False
        del self.by_id[schedule_id]
        return True

    async def due(self, now: datetime) -> list[AgentSchedule]:
        return [
            schedule
            for schedule in self.by_id.values()
            if schedule.enabled and schedule.next_run_at <= now
        ]


async def test_create_computes_next_run_at_from_cron_expression() -> None:
    service = ScheduleService(_FakeScheduleRepository())

    schedule = await service.create(
        owner_id="owner-1",
        agent_id="agent-1",
        title="Daily digest",
        cron_expression="*/5 * * * *",
        trigger_message="Summarize yesterday's activity.",
    )

    assert schedule.next_run_at > datetime.now(UTC)
    assert schedule.next_run_at <= datetime.now(UTC) + timedelta(minutes=5)


async def test_create_stores_description_and_tools() -> None:
    service = ScheduleService(_FakeScheduleRepository())

    schedule = await service.create(
        owner_id="owner-1",
        agent_id="agent-1",
        title="Daily digest",
        cron_expression="0 8 * * *",
        trigger_message="hi",
        description="Summarizes yesterday's tickets every morning.",
        tools=["extract_pdf"],
    )

    assert schedule.description == "Summarizes yesterday's tickets every morning."
    assert schedule.tools == ["extract_pdf"]


async def test_create_rejects_an_invalid_cron_expression() -> None:
    service = ScheduleService(_FakeScheduleRepository())

    with pytest.raises(InvalidCronExpressionError):
        await service.create(
            owner_id="owner-1",
            agent_id="agent-1",
            title="Daily digest",
            cron_expression="not a cron expression",
            trigger_message="hi",
        )


async def test_update_recomputes_next_run_at_only_on_a_cron_change() -> None:
    repository = _FakeScheduleRepository()
    service = ScheduleService(repository)
    schedule = await service.create(
        owner_id="owner-1",
        agent_id="agent-1",
        title="Daily digest",
        cron_expression="0 8 * * *",
        trigger_message="hi",
    )
    original_next_run_at = schedule.next_run_at

    unchanged = await service.update("owner-1", schedule.id, trigger_message="a different message")
    assert unchanged is not None
    assert unchanged.next_run_at == original_next_run_at
    assert unchanged.trigger_message == "a different message"

    changed = await service.update("owner-1", schedule.id, cron_expression="0 9 * * *")
    assert changed is not None
    assert changed.next_run_at != original_next_run_at


async def test_update_can_clear_description_and_tools_back_to_unset() -> None:
    repository = _FakeScheduleRepository()
    service = ScheduleService(repository)
    schedule = await service.create(
        owner_id="owner-1",
        agent_id="agent-1",
        title="Daily digest",
        cron_expression="0 8 * * *",
        trigger_message="hi",
        description="Some description",
        tools=["extract_pdf"],
    )

    # Omitting description/tools entirely leaves them untouched.
    untouched = await service.update("owner-1", schedule.id, title="Renamed digest")
    assert untouched is not None
    assert untouched.description == "Some description"
    assert untouched.tools == ["extract_pdf"]

    # Explicitly passing None clears them back to "unset".
    cleared = await service.update("owner-1", schedule.id, description=None, tools=None)
    assert cleared is not None
    assert cleared.description is None
    assert cleared.tools is None


async def test_update_returns_none_for_an_unknown_schedule() -> None:
    service = ScheduleService(_FakeScheduleRepository())

    assert await service.update("owner-1", "missing", trigger_message="hi") is None


async def test_due_only_returns_enabled_schedules_whose_time_has_arrived() -> None:
    repository = _FakeScheduleRepository()
    service = ScheduleService(repository)
    now = datetime.now(UTC)
    due_schedule = AgentSchedule(
        owner_id="owner-1",
        agent_id="agent-1",
        title="Due",
        cron_expression="* * * * *",
        trigger_message="hi",
        next_run_at=now - timedelta(minutes=1),
    )
    future_schedule = AgentSchedule(
        owner_id="owner-1",
        agent_id="agent-1",
        title="Future",
        cron_expression="* * * * *",
        trigger_message="hi",
        next_run_at=now + timedelta(hours=1),
    )
    disabled_schedule = AgentSchedule(
        owner_id="owner-1",
        agent_id="agent-1",
        title="Disabled",
        cron_expression="* * * * *",
        trigger_message="hi",
        enabled=False,
        next_run_at=now - timedelta(minutes=1),
    )
    for schedule in (due_schedule, future_schedule, disabled_schedule):
        await repository.create(schedule)

    due = await service.due(now)

    assert [schedule.id for schedule in due] == [due_schedule.id]


async def test_record_run_advances_bookkeeping_and_next_run_at() -> None:
    repository = _FakeScheduleRepository()
    service = ScheduleService(repository)
    schedule = await service.create(
        owner_id="owner-1",
        agent_id="agent-1",
        title="Daily digest",
        cron_expression="*/5 * * * *",
        trigger_message="hi",
    )
    ran_at = datetime.now(UTC)

    updated = await service.record_run(
        schedule, session_id="owner-1:agent-1:scheduled-x", ran_at=ran_at
    )

    assert updated.last_run_at == ran_at
    assert updated.last_run_session_id == "owner-1:agent-1:scheduled-x"
    assert updated.next_run_at > ran_at
