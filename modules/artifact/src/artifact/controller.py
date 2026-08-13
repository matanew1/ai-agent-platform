"""Authenticated, owner-scoped downloads for generated artifacts.

Mounted from ``app/main.py``.
"""

from __future__ import annotations

from pathlib import Path

from artifact.helpers import safe_artifact_filename
from artifact.service import ARTIFACTS_URL_PATH, ArtifactService
from authentication.controller import current_user
from fastapi import APIRouter, HTTPException, Request, Response, status

from shared.auth import AuthenticatedUser

router = APIRouter(prefix=ARTIFACTS_URL_PATH, tags=["artifacts"])

_ALLOWED_EXTENSIONS = {".pdf", ".md", ".markdown"}


@router.get("/{filename}")
@current_user
async def download_artifact(
    filename: str,
    request: Request,
    current_user: AuthenticatedUser,
) -> Response:
    """Download a generated file only when it belongs to the verified user."""
    extension = Path(filename).suffix.lower()
    if extension not in _ALLOWED_EXTENSIONS or filename != safe_artifact_filename(
        filename,
        default_stem="artifact",
        extension=extension,
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found.")

    artifact_service: ArtifactService = request.app.state.artifact_service
    downloaded = await artifact_service.download(current_user.id, filename)
    if downloaded is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found.")

    content, content_type = downloaded
    return Response(
        content=content,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
