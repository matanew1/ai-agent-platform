"""Tests for Mongo-backed generated-artifact ownership."""

from __future__ import annotations

from infrastructure.artifacts import MongoArtifactAccessRepository
from shared.types import ArtifactReference


class _Database:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, object]] = {}
        self.indexes: list[tuple[object, bool, str | None]] = []

    async def create_index(self, _collection, keys, *, unique=False, name=None):
        self.indexes.append((keys, unique, name))
        return name or "index"

    async def replace_one(self, _collection, query, document, *, upsert=False):
        assert upsert is True
        self.documents[query["filename"]] = document
        return True

    async def find_one(self, _collection, query):
        document = self.documents.get(query["filename"])
        return document if document and document["user_id"] == query["user_id"] else None


async def test_artifact_manifest_indexes_grants_and_isolates_users() -> None:
    database = _Database()
    repository = MongoArtifactAccessRepository(database)
    artifact = ArtifactReference(
        filename="report.pdf",
        download_url="/artifacts/report.pdf",
    )

    await repository.ensure_indexes()
    await repository.grant("user-1", [artifact])

    assert database.indexes[0] == ("filename", True, "artifact_filename_unique")
    assert await repository.can_download("user-1", artifact.filename) is True
    assert await repository.can_download("user-2", artifact.filename) is False
