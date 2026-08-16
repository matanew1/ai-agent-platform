"""PostgreSQL persistence for agent schedules."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from automation.models import AgentScheduleRecord
from automation.schemas import AgentSchedule


class ScheduleRepository:
    """Persist owner-and-agent-scoped cron schedules in PostgreSQL.

    No ``Protocol`` port: this is the only implementation, and every
    consumer imports it directly - see ``.claude/rules/architecture.md``.
    ``AgentSchedule`` and ``AgentScheduleRecord`` share field names by
    design, so conversion is plain ``model_dump``/``model_validate``,
    mirroring ``agent.repository.AgentRepository``.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, schedule: AgentSchedule) -> AgentSchedule:
        async with self._session_factory() as session:
            session.add(AgentScheduleRecord(**schedule.model_dump()))
            await session.commit()
        return schedule

    async def get(self, owner_id: str, schedule_id: str) -> AgentSchedule | None:
        statement = select(AgentScheduleRecord).where(
            AgentScheduleRecord.id == schedule_id,
            AgentScheduleRecord.owner_id == owner_id,
        )
        async with self._session_factory() as session:
            record = (await session.scalars(statement)).one_or_none()
        return AgentSchedule.model_validate(record, from_attributes=True) if record else None

    async def list_for_agent(self, owner_id: str, agent_id: str) -> list[AgentSchedule]:
        statement = (
            select(AgentScheduleRecord)
            .where(
                AgentScheduleRecord.owner_id == owner_id,
                AgentScheduleRecord.agent_id == agent_id,
            )
            .order_by(AgentScheduleRecord.created_at.desc())
        )
        async with self._session_factory() as session:
            records = (await session.scalars(statement)).all()
        return [AgentSchedule.model_validate(record, from_attributes=True) for record in records]

    async def save(self, schedule: AgentSchedule) -> bool:
        statement = (
            update(AgentScheduleRecord)
            .where(
                AgentScheduleRecord.id == schedule.id,
                AgentScheduleRecord.owner_id == schedule.owner_id,
            )
            .values(**schedule.model_dump(exclude={"created_at"}))
        )
        async with self._session_factory() as session:
            result = await session.execute(statement)
            await session.commit()
        return result.rowcount > 0

    async def delete(self, owner_id: str, schedule_id: str) -> bool:
        statement = delete(AgentScheduleRecord).where(
            AgentScheduleRecord.id == schedule_id,
            AgentScheduleRecord.owner_id == owner_id,
        )
        async with self._session_factory() as session:
            result = await session.execute(statement)
            await session.commit()
        return result.rowcount > 0

    async def due(self, now: datetime) -> list[AgentSchedule]:
        """List every enabled schedule whose next run has arrived, across owners.

        Not owner-scoped - ``automation.runner.ScheduleRunner`` is the one
        caller, and it operates process-wide rather than inside a single
        authenticated-user's request scope.
        """
        statement = select(AgentScheduleRecord).where(
            AgentScheduleRecord.enabled.is_(True),
            AgentScheduleRecord.next_run_at <= now,
        )
        async with self._session_factory() as session:
            records = (await session.scalars(statement)).all()
        return [AgentSchedule.model_validate(record, from_attributes=True) for record in records]


__all__ = ["ScheduleRepository"]
