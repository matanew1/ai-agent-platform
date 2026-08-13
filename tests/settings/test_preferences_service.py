"""Unit coverage for durable settings with a best-effort Redis cache."""

from __future__ import annotations

from settings.schemas import WorkspaceSettings
from settings.service import SettingsService


class _Repository:
    def __init__(self) -> None:
        self.record = None

    async def get(self, _owner_id: str):
        return self.record

    async def save(self, owner_id: str, settings: dict[str, object], updated_at: object) -> None:
        self.record = type(
            "Record",
            (),
            {"owner_id": owner_id, "settings": settings, "updated_at": updated_at},
        )()


class _Cache:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None:
        self.values[key] = value


async def test_settings_save_to_postgres_and_redis() -> None:
    repository = _Repository()
    cache = _Cache()
    service = SettingsService(repository, cache)  # type: ignore[arg-type]

    saved = await service.save("owner-1", WorkspaceSettings(locale="he", theme="light"))

    assert saved.locale == "he"
    assert repository.record.settings["theme"] == "light"
    assert '"locale":"he"' in cache.values["user_settings:owner-1"]


async def test_settings_read_from_redis_before_postgres() -> None:
    repository = _Repository()
    cache = _Cache()
    cache.values["user_settings:owner-1"] = WorkspaceSettings(locale="he").model_dump_json()
    service = SettingsService(repository, cache)  # type: ignore[arg-type]

    assert (await service.get("owner-1")).locale == "he"
