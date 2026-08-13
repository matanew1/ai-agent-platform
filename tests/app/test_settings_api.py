"""Authenticated HTTP contract coverage for owner-scoped workspace settings."""

from __future__ import annotations

from datetime import UTC, datetime

from authentication.repository import SESSION_COOKIE_NAME, SessionResult
from fastapi import FastAPI
from fastapi.testclient import TestClient
from settings.controller import router

from shared.auth import AuthenticatedUser, AuthenticationError


class _Authenticator:
    async def authenticate_session(self, sealed_session: str | None) -> SessionResult:
        if sealed_session is None:
            raise AuthenticationError("No session cookie was provided.")
        return SessionResult(
            user=AuthenticatedUser(id=sealed_session), sealed_session=sealed_session
        )


class _SettingsService:
    def __init__(self) -> None:
        self.by_owner: dict[str, dict[str, object]] = {}

    async def get(self, owner_id: str) -> dict[str, object]:
        return self.by_owner.get(
            owner_id,
            {
                "theme": "dark",
                "locale": "en",
                "compact": False,
                "reduce_motion": False,
                "show_sources": True,
                "show_tool_activity": True,
            },
        )

    async def save(self, owner_id: str, settings: object) -> dict[str, object]:
        value = settings.model_dump()
        value["updated_at"] = datetime.now(UTC)
        self.by_owner[owner_id] = value
        return value


def _client(authenticated: bool = True) -> tuple[TestClient, _SettingsService]:
    app = FastAPI()
    service = _SettingsService()
    app.state.settings_service = service
    app.state.authenticator = _Authenticator()
    app.include_router(router)
    cookies = {SESSION_COOKIE_NAME: "owner-1"} if authenticated else None
    return TestClient(app, cookies=cookies), service


def test_settings_are_authenticated_owner_scoped_and_validate_payloads() -> None:
    anonymous, _ = _client(authenticated=False)
    client, service = _client()

    assert anonymous.get("/settings").status_code == 401
    saved = client.put(
        "/settings",
        json={
            "theme": "light",
            "locale": "he",
            "compact": True,
            "reduce_motion": False,
            "show_sources": True,
            "show_tool_activity": False,
        },
    )

    assert saved.status_code == 200
    assert saved.json()["locale"] == "he"
    assert service.by_owner["owner-1"]["theme"] == "light"
    assert (
        client.get("/settings", cookies={SESSION_COOKIE_NAME: "owner-2"}).json()["locale"] == "en"
    )
    assert client.put("/settings", json={"unknown": True}).status_code == 422
