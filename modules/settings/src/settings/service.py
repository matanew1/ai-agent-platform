from __future__ import annotations

import logging
from datetime import UTC, datetime

from infrastructure.cache.protocol import Cache
from settings.repository import SettingsRepository
from settings.schemas import SettingsResponse, WorkspaceSettings

logger = logging.getLogger(__name__)
_CACHE_PREFIX = "user_settings:"


class SettingsService:
    """PostgreSQL-authoritative settings with a Redis hot cache."""

    def __init__(self, repository: SettingsRepository, cache: Cache) -> None:
        self._repository = repository
        self._cache = cache

    async def get(self, owner_id: str) -> SettingsResponse:
        try:
            cached = await self._cache.get(_CACHE_PREFIX + owner_id)
            if cached is not None:
                return SettingsResponse.model_validate_json(cached)
        except Exception as exc:
            logger.warning("Settings cache read failed; using PostgreSQL: %s", exc)
        record = await self._repository.get(owner_id)
        result = SettingsResponse.model_validate(record.settings) if record else SettingsResponse()
        if record:
            result.updated_at = record.updated_at
            await self._cache_best_effort(owner_id, result)
        return result

    async def save(self, owner_id: str, settings: WorkspaceSettings) -> SettingsResponse:
        result = SettingsResponse(**settings.model_dump(), updated_at=datetime.now(UTC))
        await self._repository.save(owner_id, settings.model_dump(mode="json"), result.updated_at)
        await self._cache_best_effort(owner_id, result)
        return result

    async def _cache_best_effort(self, owner_id: str, settings: SettingsResponse) -> None:
        try:
            await self._cache.set(_CACHE_PREFIX + owner_id, settings.model_dump_json())
        except Exception as exc:
            logger.warning("Settings cache write failed; PostgreSQL remains authoritative: %s", exc)
