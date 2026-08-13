from __future__ import annotations

from authentication.controller import current_user
from fastapi import APIRouter, Request

from settings.schemas import SettingsResponse, WorkspaceSettings
from settings.service import SettingsService
from shared.auth import AuthenticatedUser

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsResponse)
@current_user
async def get_settings(request: Request, current_user: AuthenticatedUser) -> SettingsResponse:
    """Read only the authenticated user's settings."""
    service: SettingsService = request.app.state.settings_service
    return await service.get(current_user.id)


@router.put("", response_model=SettingsResponse)
@current_user
async def save_settings(
    payload: WorkspaceSettings, request: Request, current_user: AuthenticatedUser
) -> SettingsResponse:
    """Replace only the authenticated user's settings."""
    service: SettingsService = request.app.state.settings_service
    return await service.save(current_user.id, payload)
