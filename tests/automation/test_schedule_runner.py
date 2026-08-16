"""Unit coverage for the background schedule-firing loop.

Fakes ``schedules``/``agents``/``chat_service_factory``/``cache`` at their
port boundaries (see .claude/rules/testing.md) rather than exercising real
cron math or a real chat turn - ``test_service.py`` already covers
``ScheduleService.due``/``record_run`` directly.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

from automation.runner import ScheduleRunner
from automation.schemas import AgentSchedule

from infrastructure.errors import CacheError
from shared.types import Agent


def _schedule(schedule_id: str, *, agent_id: str = "agent-1") -> AgentSchedule:
    return AgentSchedule(
        id=schedule_id,
        owner_id="owner-1",
        agent_id=agent_id,
        cron_expression="*/5 * * * *",
        trigger_message="Summarize yesterday's activity.",
        next_run_at=datetime.now(UTC) - timedelta(minutes=1),
    )


def _agent(agent_id: str = "agent-1") -> Agent:
    return Agent(
        id=agent_id,
        owner_id="owner-1",
        name="Daily Summarizer",
        system_prompt="You summarize things.",
        allowed_tools=[],
    )


class _FakeSchedules:
    """Minimal stand-in isolating runner logic from real cron math."""

    def __init__(self, due: list[AgentSchedule]) -> None:
        self._due = due
        self.recorded_runs: list[tuple[str, str]] = []  # (schedule_id, session_id)

    async def due(self, _now: datetime) -> list[AgentSchedule]:
        return list(self._due)

    async def record_run(
        self, schedule: AgentSchedule, session_id: str, ran_at: datetime
    ) -> AgentSchedule:
        self.recorded_runs.append((schedule.id, session_id))
        return schedule.model_copy(
            update={"last_run_at": ran_at, "last_run_session_id": session_id}
        )


class _FakeAgents:
    def __init__(self, agents: dict[str, Agent]) -> None:
        self._agents = agents

    async def get(self, _owner_id: str, agent_id: str) -> Agent | None:
        return self._agents.get(agent_id)


class _FakeStream:
    """A minimal async-iterable of chunks, mirroring run_stream's second return value."""

    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks

    def __aiter__(self):
        return self._generator()

    async def _generator(self):
        for chunk in self._chunks:
            yield chunk


class _FakeChatService:
    def __init__(self, run_stream_error: Exception | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self._run_stream_error = run_stream_error

    async def run_stream(self, *, session_id: str, message: str, tools: list[str]):
        self.calls.append({"session_id": session_id, "message": message, "tools": tools})
        if self._run_stream_error is not None:
            raise self._run_stream_error
        return object(), _FakeStream(["Hello", " world"])


class _NoOpLock(AbstractAsyncContextManager[None]):
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc_info: object) -> None:
        return None


class _FailingLock(AbstractAsyncContextManager[None]):
    async def __aenter__(self) -> None:
        raise CacheError("lock unavailable")

    async def __aexit__(self, *exc_info: object) -> None:
        return None


class _FakeCache:
    """Locks every key successfully unless it's in ``contended_keys``."""

    def __init__(self, contended_keys: set[str] | None = None) -> None:
        self._contended_keys = contended_keys or set()

    def lock(self, key: str) -> AbstractAsyncContextManager[None]:
        if key in self._contended_keys:
            return _FailingLock()
        return _NoOpLock()


async def test_fire_due_runs_a_turn_and_records_it() -> None:
    schedule = _schedule("sched-1")
    schedules = _FakeSchedules(due=[schedule])
    chat_service = _FakeChatService()
    runner = ScheduleRunner(
        schedules=schedules,  # type: ignore[arg-type]
        agents=_FakeAgents({"agent-1": _agent()}),  # type: ignore[arg-type]
        chat_service_factory=lambda agent: chat_service,
        cache=_FakeCache(),  # type: ignore[arg-type]
    )

    await runner._fire_due()

    assert len(chat_service.calls) == 1
    call = chat_service.calls[0]
    assert call["message"] == schedule.trigger_message
    assert call["session_id"].startswith("owner-1:agent-1:scheduled-sched-1-")
    assert schedules.recorded_runs == [("sched-1", call["session_id"])]


async def test_fire_due_skips_a_schedule_whose_agent_was_deleted() -> None:
    schedules = _FakeSchedules(due=[_schedule("sched-1")])
    chat_service = _FakeChatService()
    runner = ScheduleRunner(
        schedules=schedules,  # type: ignore[arg-type]
        agents=_FakeAgents({}),  # type: ignore[arg-type]
        chat_service_factory=lambda agent: chat_service,
        cache=_FakeCache(),  # type: ignore[arg-type]
    )

    await runner._fire_due()

    assert chat_service.calls == []
    assert schedules.recorded_runs == []


async def test_fire_due_skips_a_schedule_whose_lock_is_contended() -> None:
    schedules = _FakeSchedules(due=[_schedule("sched-1")])
    chat_service = _FakeChatService()
    runner = ScheduleRunner(
        schedules=schedules,  # type: ignore[arg-type]
        agents=_FakeAgents({"agent-1": _agent()}),  # type: ignore[arg-type]
        chat_service_factory=lambda agent: chat_service,
        cache=_FakeCache(contended_keys={"schedule_run:sched-1"}),  # type: ignore[arg-type]
    )

    await runner._fire_due()

    assert chat_service.calls == []
    assert schedules.recorded_runs == []


async def test_one_failing_schedule_does_not_block_the_rest_of_the_tick() -> None:
    failing_schedule = _schedule("sched-fail", agent_id="agent-1")
    ok_schedule = _schedule("sched-ok", agent_id="agent-2")
    schedules = _FakeSchedules(due=[failing_schedule, ok_schedule])
    failing_chat_service = _FakeChatService(run_stream_error=RuntimeError("boom"))
    ok_chat_service = _FakeChatService()

    def factory(agent: Agent):
        return failing_chat_service if agent.id == "agent-1" else ok_chat_service

    runner = ScheduleRunner(
        schedules=schedules,  # type: ignore[arg-type]
        agents=_FakeAgents({"agent-1": _agent("agent-1"), "agent-2": _agent("agent-2")}),  # type: ignore[arg-type]
        chat_service_factory=factory,
        cache=_FakeCache(),  # type: ignore[arg-type]
    )

    await runner._fire_due()

    assert len(failing_chat_service.calls) == 1
    assert len(ok_chat_service.calls) == 1
    assert schedules.recorded_runs == [("sched-ok", ok_chat_service.calls[0]["session_id"])]
