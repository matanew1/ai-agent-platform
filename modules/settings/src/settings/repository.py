from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from settings.models import UserSettingsRecord


class SettingsRepository:
    """Read and atomically upsert owner-scoped settings JSON."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(self, owner_id: str) -> UserSettingsRecord | None:
        async with self._session_factory() as session:
            statement = select(UserSettingsRecord).where(UserSettingsRecord.owner_id == owner_id)
            return (await session.scalars(statement)).one_or_none()

    async def save(self, owner_id: str, settings: dict[str, object], updated_at: datetime) -> None:
        statement = (
            insert(UserSettingsRecord)
            .values(owner_id=owner_id, settings=settings, updated_at=updated_at)
            .on_conflict_do_update(
                index_elements=[UserSettingsRecord.owner_id],
                set_={"settings": settings, "updated_at": updated_at},
            )
        )
        async with self._session_factory() as session:
            await session.execute(statement)
            await session.commit()
