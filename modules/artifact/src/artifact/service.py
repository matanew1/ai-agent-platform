"""Artifact storage and ownership: the module's public entry point.

Generated files (from ``tool``'s PDF/Markdown tools) live in PostgreSQL via
``artifact.repository.ArtifactRepository`` - not on local disk - so a
horizontally scaled deployment doesn't need shared storage. The same
repository separately tracks which authenticated user may download which
filename. ``ArtifactService`` is the only thing that talks to it; every
consumer (``app.artifacts``, ``agent.controller``, ``tool.controller``,
``tool.tools.local.pdf``/``tool.tools.local.markdown``) goes through it.
"""

from __future__ import annotations

import logging
from itertools import count
from pathlib import Path
from urllib.parse import quote, unquote

from artifact.helpers import StoredArtifact, read_local_file, safe_artifact_filename
from artifact.repository import ArtifactRepository
from sqlalchemy.exc import IntegrityError

from shared.types import ArtifactReference

logger = logging.getLogger(__name__)

ARTIFACTS_URL_PATH = "/artifacts"


class ArtifactService:
    """Generated-artifact storage and per-user download access."""

    def __init__(self, repository: ArtifactRepository) -> None:
        self._repository = repository

    async def store(
        self,
        content: bytes,
        *,
        requested_filename: str | None,
        default_stem: str,
        extension: str,
        content_type: str,
    ) -> StoredArtifact:
        """Store bytes under a unique, sanitized artifact filename."""
        safe_name = safe_artifact_filename(
            requested_filename, default_stem=default_stem, extension=extension
        )
        base = Path(safe_name)
        for collision_index in count(1):
            filename = (
                safe_name if collision_index == 1 else f"{base.stem}-{collision_index}{base.suffix}"
            )
            try:
                await self._repository.store(filename, content, content_type)
            except IntegrityError:
                continue
            logger.debug("ArtifactService.store filename=%r content_len=%d", filename, len(content))
            return StoredArtifact(
                filename=filename,
                download_url=f"{ARTIFACTS_URL_PATH}/{quote(filename, safe='')}",
            )
        raise RuntimeError("Unable to allocate a unique artifact filename.")  # pragma: no cover

    async def store_text(
        self,
        content: str,
        *,
        requested_filename: str | None,
        default_stem: str,
        extension: str,
        content_type: str,
    ) -> StoredArtifact:
        """Encode UTF-8 text and store it through the same atomic byte path."""
        return await self.store(
            content.encode("utf-8"),
            requested_filename=requested_filename,
            default_stem=default_stem,
            extension=extension,
            content_type=content_type,
        )

    async def read(self, reference: str, *, extension: str) -> tuple[bytes, str]:
        """Resolve a generated-artifact URL/filename, or a legacy absolute path.

        Returns:
            ``(content, filename)`` - ``filename`` is the resolved artifact's
            safe name (or the source file's own basename for the legacy
            absolute-path case), useful for deriving an edited copy's
            default filename stem.
        """
        value = reference.strip()
        if not value:
            raise ValueError("Artifact source cannot be empty.")

        artifact_prefix = f"{ARTIFACTS_URL_PATH}/"
        if value.startswith(artifact_prefix):
            filename = unquote(value.removeprefix(artifact_prefix))
        elif not Path(value).is_absolute():
            filename = value
        else:
            content = read_local_file(value, extension=extension)
            return content, Path(value).name

        expected_name = safe_artifact_filename(
            filename, default_stem="artifact", extension=extension
        )
        if filename != expected_name:
            raise ValueError("Artifact reference must be a safe filename of the expected type.")
        found = await self._repository.read(filename)
        if found is None:
            raise FileNotFoundError(f"Artifact source does not exist: {reference}")
        content, _content_type = found
        return content, filename

    async def download(self, user_id: str, filename: str) -> tuple[bytes, str] | None:
        """Return ``(content, content_type)`` only for an authorized owner."""
        if not await self._repository.can_download(user_id, filename):
            return None
        return await self._repository.read(filename)

    async def grant(self, user_id: str, artifacts: list[ArtifactReference]) -> None:
        """Record ownership so ``download`` will authorize this user for these filenames."""
        await self._repository.grant(user_id, artifacts)


__all__ = ["ArtifactService"]
