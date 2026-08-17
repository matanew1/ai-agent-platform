"""Owner-scoped CRUD over agent schedules, plus cron-time computation.

Turn *execution* of a fired schedule lives in ``automation.runner`` - this
service owns configuration only, mirroring ``agent.service.AgentService``'s
own split between configuration and execution. Verifying that ``agent_id``
belongs to the caller, and that ``tools`` is a subset of the agent's own
``allowed_tools``, are the controller's job (the same "get the parent
resource, 404 if missing" pattern ``agent.controller``'s session routes and
``chat.controller`` already use for the same reason, extended to this
schedule-vs-agent check since the controller is the one place that already
has the agent loaded) - not this service's, so this service, unlike
``automation.runner``, never needs an ``AgentService`` dependency at all.
"""

from __future__ import annotations

from datetime import UTC, datetime

from croniter import CroniterBadCronError, croniter

from automation.repository import ScheduleRepository
from automation.schemas import AgentSchedule


class ScheduleError(Exception):
    """Base exception for the schedule module."""


class InvalidCronExpressionError(ScheduleError):
    """A supplied cron expression does not parse."""


class _UnsetType:
    """Sentinel distinguishing an omitted update from an explicit ``None``.

    Mirrors ``agent.service._UnsetType`` - ``description``/``tools`` are
    both legitimately clearable back to ``None`` (no description; fall back
    to the agent's own ``allowed_tools``), so a plain ``None`` default
    can't tell "clear this" apart from "leave it alone".
    """


_UNSET = _UnsetType()


class ScheduleService:
    """Manage cron schedules for agents owned by the authenticated user."""

    def __init__(self, repository: ScheduleRepository) -> None:
        self._repository = repository

    async def create(
        self,
        owner_id: str,
        agent_id: str,
        title: str,
        cron_expression: str,
        trigger_message: str,
        description: str | None = None,
        tools: list[str] | None = None,
    ) -> AgentSchedule:
        """Create a schedule after validating its cron expression."""
        return await self._repository.create(
            AgentSchedule(
                owner_id=owner_id,
                agent_id=agent_id,
                title=title,
                description=description,
                cron_expression=cron_expression,
                trigger_message=trigger_message,
                tools=tools,
                next_run_at=_next_run_at(cron_expression),
            )
        )

    async def get(self, owner_id: str, schedule_id: str) -> AgentSchedule | None:
        """Get a schedule only when it belongs to the supplied owner scope."""
        return await self._repository.get(owner_id, schedule_id)

    async def list_for_agent(self, owner_id: str, agent_id: str) -> list[AgentSchedule]:
        """List all schedules configured for one owned agent."""
        return await self._repository.list_for_agent(owner_id, agent_id)

    async def update(
        self,
        owner_id: str,
        schedule_id: str,
        *,
        agent_id: str | None = None,
        title: str | None = None,
        description: str | None | _UnsetType = _UNSET,
        cron_expression: str | None = None,
        trigger_message: str | None = None,
        tools: list[str] | None | _UnsetType = _UNSET,
        enabled: bool | None = None,
    ) -> AgentSchedule | None:
        """Apply a partial update, recomputing ``next_run_at`` on a cron change.

        ``agent_id``, if given, moves the schedule - the caller
        (``automation.controller``) has already verified both the current
        and target agent belong to ``owner_id`` and reconciled ``tools``
        against the target agent before this is called; this method just
        writes whatever it's given.
        """
        schedule = await self._repository.get(owner_id, schedule_id)
        if schedule is None:
            return None
        changes: dict[str, object] = {}
        if agent_id is not None:
            changes["agent_id"] = agent_id
        if title is not None:
            changes["title"] = title
        if description is not _UNSET:
            changes["description"] = description
        if cron_expression is not None:
            changes["cron_expression"] = cron_expression
            changes["next_run_at"] = _next_run_at(cron_expression)
        if trigger_message is not None:
            changes["trigger_message"] = trigger_message
        if tools is not _UNSET:
            changes["tools"] = tools
        if enabled is not None:
            changes["enabled"] = enabled
        if not changes:
            return schedule
        updated = schedule.model_copy(update={**changes, "updated_at": datetime.now(UTC)})
        await self._repository.save(updated)
        return updated

    async def delete(self, owner_id: str, schedule_id: str) -> bool:
        """Delete a schedule only when it belongs to the supplied owner scope."""
        return await self._repository.delete(owner_id, schedule_id)

    async def due(self, now: datetime) -> list[AgentSchedule]:
        """List every enabled schedule ready to fire - used only by the runner."""
        return await self._repository.due(now)

    async def record_run(
        self, schedule: AgentSchedule, session_id: str, ran_at: datetime
    ) -> AgentSchedule:
        """Advance a fired schedule's bookkeeping to its next occurrence."""
        updated = schedule.model_copy(
            update={
                "last_run_at": ran_at,
                "last_run_session_id": session_id,
                "next_run_at": _next_run_at(schedule.cron_expression, start=ran_at),
                "updated_at": ran_at,
            }
        )
        await self._repository.save(updated)
        return updated


def _next_run_at(cron_expression: str, start: datetime | None = None) -> datetime:
    """Compute the next occurrence of a cron expression strictly after ``start``."""
    try:
        return croniter(cron_expression, start or datetime.now(UTC)).get_next(datetime)
    except (CroniterBadCronError, ValueError, KeyError) as exc:
        raise InvalidCronExpressionError(
            f"Invalid cron expression {cron_expression!r}: {exc}"
        ) from exc


__all__ = ["InvalidCronExpressionError", "ScheduleError", "ScheduleService"]
