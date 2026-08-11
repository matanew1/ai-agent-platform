"""MongoDB ownership manifest for generated PDF/Markdown artifacts."""

from __future__ import annotations

from datetime import UTC, datetime

from infrastructure.database import MongoDatabase
from shared.types import ArtifactReference

_COLLECTION = "artifact_access"


class MongoArtifactAccessRepository:
    """Authorize artifact downloads without exposing the filesystem publicly."""

    def __init__(self, database: MongoDatabase) -> None:
        self._database = database

    async def ensure_indexes(self) -> None:
        await self._database.create_index(
            _COLLECTION,
            "filename",
            unique=True,
            name="artifact_filename_unique",
        )
        await self._database.create_index(
            _COLLECTION,
            [("user_id", 1), ("created_at", -1)],
            name="artifact_user_created_at",
        )

    async def grant(self, user_id: str, artifacts: list[ArtifactReference]) -> None:
        for artifact in artifacts:
            await self._database.replace_one(
                _COLLECTION,
                {"filename": artifact.filename},
                {
                    "filename": artifact.filename,
                    "download_url": artifact.download_url,
                    "user_id": user_id,
                    "created_at": datetime.now(UTC),
                },
                upsert=True,
            )

    async def can_download(self, user_id: str, filename: str) -> bool:
        document = await self._database.find_one(
            _COLLECTION,
            {"filename": filename, "user_id": user_id},
        )
        return document is not None
