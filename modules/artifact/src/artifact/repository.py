"""PostgreSQL persistence for generated artifacts: content bytes and ownership grants.

Two tables, one repository: ``artifact_content`` (written at generation
time, before an owner is known) and ``artifact_access`` (written once
``artifact.service.ArtifactService.grant`` records the owner). Kept as one
class since both are the artifact module's only persistence concern and
share the same ``filename`` key - splitting them added an extra
constructor argument everywhere without buying any real isolation.
"""

from __future__ import annotations

from datetime import UTC, datetime

from artifact.models import ArtifactAccessRecord, ArtifactContentRecord
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared.types import ArtifactReference


class ArtifactRepository:
    """Store generated-artifact bytes and their per-user download access."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def store(self, filename: str, content: bytes, content_type: str) -> None:
        """Insert new content under ``filename``.

        A plain insert, not an upsert: ``ArtifactService.store`` relies on
        the primary-key violation this raises on a name collision to retry
        under a different, suffixed filename - the DB-backed equivalent of
        the atomic ``O_CREAT | O_EXCL`` local-file write this replaced.

        Raises:
            sqlalchemy.exc.IntegrityError: If ``filename`` already exists.
        """
        async with self._session_factory() as session:
            session.add(
                ArtifactContentRecord(
                    filename=filename,
                    content=content,
                    content_type=content_type,
                    created_at=datetime.now(UTC),
                )
            )
            await session.commit()

    async def read(self, filename: str) -> tuple[bytes, str] | None:
        """Return ``(content, content_type)``, or ``None`` if not found."""
        statement = select(ArtifactContentRecord.content, ArtifactContentRecord.content_type).where(
            ArtifactContentRecord.filename == filename
        )
        async with self._session_factory() as session:
            row = (await session.execute(statement)).first()
        return (row.content, row.content_type) if row is not None else None

    async def grant(self, user_id: str, artifacts: list[ArtifactReference]) -> None:
        """Record ownership so ``can_download`` will authorize this user for these filenames."""
        async with self._session_factory() as session:
            for artifact in artifacts:
                values = {
                    "filename": artifact.filename,
                    "download_url": artifact.download_url,
                    "user_id": user_id,
                    "created_at": datetime.now(UTC),
                }
                statement = (
                    insert(ArtifactAccessRecord)
                    .values(**values)
                    .on_conflict_do_update(
                        index_elements=[ArtifactAccessRecord.filename],
                        set_=values,
                    )
                )
                await session.execute(statement)
            await session.commit()

    async def can_download(self, user_id: str, filename: str) -> bool:
        statement = select(ArtifactAccessRecord.filename).where(
            ArtifactAccessRecord.filename == filename,
            ArtifactAccessRecord.user_id == user_id,
        )
        async with self._session_factory() as session:
            return await session.scalar(statement) is not None


__all__ = ["ArtifactRepository"]
