"""PostgreSQL persistence for agents."""

from __future__ import annotations

from agent.models import AgentRecord
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared.types import Agent


class AgentRepository:
    """Persist versioned, owner-scoped agents in PostgreSQL.

    No ``Protocol`` port: this is the only implementation, and every
    consumer imports it directly - see ``.claude/rules/architecture.md``'s
    "Avoiding over-engineering". ``Agent`` and
    ``AgentRecord`` share the same field names by design, so
    conversion is plain ``model_dump``/``model_validate`` rather than a
    hand-maintained mapper.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, definition: Agent) -> Agent:
        async with self._session_factory() as session:
            session.add(AgentRecord(**definition.model_dump()))
            await session.commit()
        return definition

    async def get(self, owner_id: str, agent_id: str) -> Agent | None:
        statement = select(AgentRecord).where(
            AgentRecord.id == agent_id,
            AgentRecord.owner_id == owner_id,
        )
        async with self._session_factory() as session:
            record = (await session.scalars(statement)).one_or_none()
        return Agent.model_validate(record, from_attributes=True) if record else None

    async def list(self, owner_id: str) -> list[Agent]:
        statement = (
            select(AgentRecord)
            .where(AgentRecord.owner_id == owner_id)
            .order_by(AgentRecord.updated_at.desc())
        )
        async with self._session_factory() as session:
            records = (await session.scalars(statement)).all()
        return [Agent.model_validate(record, from_attributes=True) for record in records]

    async def save(self, definition: Agent) -> bool:
        statement = (
            update(AgentRecord)
            .where(
                AgentRecord.id == definition.id,
                AgentRecord.owner_id == definition.owner_id,
            )
            .values(**definition.model_dump(exclude={"created_at"}))
        )
        async with self._session_factory() as session:
            result = await session.execute(statement)
            await session.commit()
        return result.rowcount > 0

    async def delete(self, owner_id: str, agent_id: str) -> bool:
        statement = delete(AgentRecord).where(
            AgentRecord.id == agent_id,
            AgentRecord.owner_id == owner_id,
        )
        async with self._session_factory() as session:
            result = await session.execute(statement)
            await session.commit()
        return result.rowcount > 0


__all__ = ["AgentRepository"]
