"""Owner-scoped CRUD over agent schedules, plus cron-time computation.

Turn *execution* of a fired schedule lives in ``schedule.runner`` - this
service owns configuration only, mirroring ``agent.service.AgentService``'s
own split between configuration and execution. Verifying that ``agent_id``
belongs to the caller is the controller's job (the same "get the parent
resource, 404 if missing" pattern ``agent.controller``'s session routes and
``chat.controller`` already use for the same reason), not this service's -
so this service, unlike ``schedule.runner``, never needs an
``AgentService`` dependency at all.
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


class ScheduleService:
    """Manage cron schedules for agents owned by the authenticated user."""

    def __init__(self, repository: ScheduleRepository) -> None:
        self._repository = repository

    async def create(
        self, owner_id: str, agent_id: str, cron_expression: str, trigger_message: str
    ) -> AgentSchedule:
        """Create a schedule after validating its cron expression."""
        return await self._repository.create(
            AgentSchedule(
                owner_id=owner_id,
                agent_id=agent_id,
                cron_expression=cron_expression,
                trigger_message=trigger_message,
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
        cron_expression: str | None = None,
        trigger_message: str | None = None,
        enabled: bool | None = None,
    ) -> AgentSchedule | None:
        """Apply a partial update, recomputing ``next_run_at`` on a cron change."""
        schedule = await self._repository.get(owner_id, schedule_id)
        if schedule is None:
            return None
        changes: dict[str, object] = {}
        if cron_expression is not None:
            changes["cron_expression"] = cron_expression
            changes["next_run_at"] = _next_run_at(cron_expression)
        if trigger_message is not None:
            changes["trigger_message"] = trigger_message
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
