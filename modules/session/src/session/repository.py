"""PostgreSQL persistence for durable chat session checkpoints."""

from __future__ import annotations

from session.models import SessionCheckpointRecord
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared.types import SessionCheckpoint


class SessionRepository:
    """Persist complete, scoped session checkpoints in PostgreSQL.

    No ``Protocol`` port: this and ``session.service.HybridSessionStore``
    are each the only implementation of their shape - see
    ``.claude/rules/architecture.md``'s "Avoiding over-engineering".
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_checkpoint(self, session_id: str) -> SessionCheckpoint | None:
        statement = select(SessionCheckpointRecord).where(
            SessionCheckpointRecord.session_id == session_id
        )
        async with self._session_factory() as session:
            record = (await session.scalars(statement)).one_or_none()
        return _to_checkpoint(record) if record is not None else None

    async def save_checkpoint(self, checkpoint: SessionCheckpoint) -> None:
        values = _checkpoint_values(checkpoint)
        statement = (
            insert(SessionCheckpointRecord)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[SessionCheckpointRecord.session_id],
                set_={"history": values["history"], "updated_at": values["updated_at"]},
            )
        )
        async with self._session_factory() as session:
            await session.execute(statement)
            await session.commit()

    async def list_checkpoints(self, session_prefix: str) -> list[SessionCheckpoint]:
        statement = (
            select(SessionCheckpointRecord)
            .where(SessionCheckpointRecord.session_id.startswith(session_prefix, autoescape=True))
            .order_by(SessionCheckpointRecord.updated_at.desc())
        )
        async with self._session_factory() as session:
            records = (await session.scalars(statement)).all()
        return [_to_checkpoint(record) for record in records]

    async def delete_checkpoint(self, session_id: str) -> bool:
        statement = delete(SessionCheckpointRecord).where(
            SessionCheckpointRecord.session_id == session_id
        )
        async with self._session_factory() as session:
            result = await session.execute(statement)
            await session.commit()
        return result.rowcount > 0


def _checkpoint_values(checkpoint: SessionCheckpoint) -> dict[str, object]:
    return {
        "session_id": checkpoint.session_id,
        "history": [message.model_dump(mode="json") for message in checkpoint.history],
        "updated_at": checkpoint.updated_at,
    }


def _to_checkpoint(record: SessionCheckpointRecord) -> SessionCheckpoint:
    return SessionCheckpoint(
        session_id=record.session_id,
        history=record.history,
        updated_at=record.updated_at,
    )


__all__ = ["SessionRepository"]
