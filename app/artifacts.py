"""Authenticated, owner-scoped downloads for generated artifacts."""

from __future__ import annotations

from pathlib import Path

from agent.api.auth import CurrentUser
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse

from shared.artifacts import (
    ARTIFACTS_URL_PATH,
    ArtifactAccessRepository,
    get_artifacts_directory,
    safe_artifact_filename,
)

router = APIRouter(prefix=ARTIFACTS_URL_PATH, tags=["artifacts"])

_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".md": "text/markdown; charset=utf-8",
    ".markdown": "text/markdown; charset=utf-8",
}


@router.get("/{filename}", response_class=FileResponse)
async def download_artifact(
    filename: str,
    request: Request,
    current_user: CurrentUser,
) -> FileResponse:
    """Download a generated file only when it belongs to the verified user."""
    extension = Path(filename).suffix.lower()
    if extension not in _MEDIA_TYPES or filename != safe_artifact_filename(
        filename,
        default_stem="artifact",
        extension=extension,
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found.")

    access: ArtifactAccessRepository = request.app.state.artifact_access
    if not await access.can_download(current_user.id, filename):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found.")

    root = get_artifacts_directory()
    candidate = root / filename
    if candidate.is_symlink():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found.")
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artifact not found.",
        ) from exc
    if resolved.parent != root or not resolved.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found.")

    return FileResponse(
        resolved,
        media_type=_MEDIA_TYPES[extension],
        filename=filename,
    )
