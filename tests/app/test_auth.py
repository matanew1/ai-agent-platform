"""Route-level tests for the /auth/* endpoints and the session dependency.

Unit tests, not integration tests: ``app.state.authenticator`` is a fake
satisfying ``authentication.repository``'s shape, so nothing here makes a
real network call - the equivalent of ``tests/app/test_agents_api.py``'s
``_Authenticator`` fake, applied to the routes that construct sessions
rather than just consume them.
"""

from __future__ import annotations

import json
from urllib.parse import quote, unquote

from authentication.controller import router as auth_router
from authentication.repository import (
    LOGIN_STATE_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    AuthSettings,
    SessionResult,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.auth import AuthenticatedUser, AuthenticationError

_SEALED = "sealed-session-value"


class _FakeAuthenticator:
    def __init__(self) -> None:
        self.exchanged_codes: list[str] = []

    def login_url(self, *, state: str, screen_hint: str | None = None) -> str:
        return f"https://workos.example/authorize?state={state}"

    async def exchange_code(self, code: str) -> SessionResult:
        self.exchanged_codes.append(code)
        if code == "bad-code":
            raise AuthenticationError("The sign-in code is invalid or expired.")
        return SessionResult(
            user=AuthenticatedUser(id="user_123", email="person@example.com"),
            sealed_session=_SEALED,
        )

    async def authenticate_session(self, sealed_session: str | None) -> SessionResult:
        if sealed_session != _SEALED:
            raise AuthenticationError("No session cookie was provided.")
        return SessionResult(
            user=AuthenticatedUser(id="user_123", email="person@example.com"),
            sealed_session=sealed_session,
        )

    async def logout_url(self, sealed_session: str | None, *, return_to: str) -> str:
        return f"https://workos.example/logout?return_to={return_to}"


def _app(*, app_environment: str = "production") -> tuple[FastAPI, _FakeAuthenticator]:
    app = FastAPI()
    authenticator = _FakeAuthenticator()
    app.state.authenticator = authenticator
    app.state.auth_settings = AuthSettings(
        mode="workos",
        app_environment=app_environment,
        workos_api_key="sk_test_x",
        workos_client_id="client_test",
        cookie_password="unused-in-these-tests",
        redirect_uri="https://api.example.com/auth/callback",
        frontend_url="https://app.example.com",
    )
    app.include_router(auth_router)
    return app, authenticator


def _set_cookie_lines(response) -> list[str]:  # noqa: ANN001 - httpx.Response, avoids import just for typing
    return response.headers.get_list("set-cookie")


def _login_state_cookie(*, state: str, return_to: str) -> str:
    """Match authentication.controller.login's URL-encoded cookie value."""
    return quote(json.dumps({"state": state, "return_to": return_to}), safe="")


# --- /auth/login ---------------------------------------------------------------


def test_login_sets_state_cookie_and_redirects() -> None:
    app, _ = _app()
    client = TestClient(app)

    response = client.get("/auth/login?return_to=/agents/foo", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://workos.example/authorize?state=")
    raw_cookie = response.cookies.get(LOGIN_STATE_COOKIE_NAME)
    assert raw_cookie is not None
    saved = json.loads(unquote(raw_cookie))
    assert saved["return_to"] == "/agents/foo"
    assert saved["state"]


def test_login_rejects_an_off_site_return_to() -> None:
    app, _ = _app()
    client = TestClient(app)

    response = client.get("/auth/login?return_to=//evil.example", follow_redirects=False)

    saved = json.loads(unquote(response.cookies.get(LOGIN_STATE_COOKIE_NAME)))
    assert saved["return_to"] == "/agents"


# --- /auth/callback --------------------------------------------------------------


def test_callback_rejects_a_state_mismatch_without_setting_a_session() -> None:
    app, authenticator = _app()
    client = TestClient(app)
    client.cookies.set(
        LOGIN_STATE_COOKIE_NAME, _login_state_cookie(state="expected", return_to="/agents")
    )

    response = client.get("/auth/callback?code=good-code&state=wrong-state", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "https://app.example.com/agents?auth_error=1"
    assert SESSION_COOKIE_NAME not in response.cookies
    assert authenticator.exchanged_codes == []


def test_callback_success_sets_the_session_cookie_and_redirects_to_return_to() -> None:
    app, authenticator = _app()
    client = TestClient(app)
    client.cookies.set(
        LOGIN_STATE_COOKIE_NAME, _login_state_cookie(state="expected", return_to="/agents/foo")
    )

    response = client.get("/auth/callback?code=good-code&state=expected", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "https://app.example.com/agents/foo"
    assert response.cookies.get(SESSION_COOKIE_NAME) == _SEALED
    assert authenticator.exchanged_codes == ["good-code"]


def test_callback_uses_secure_samesite_none_cookie_flags_outside_development() -> None:
    app, _ = _app(app_environment="production")
    client = TestClient(app)
    client.cookies.set(
        LOGIN_STATE_COOKIE_NAME, _login_state_cookie(state="expected", return_to="/agents")
    )

    response = client.get("/auth/callback?code=good-code&state=expected", follow_redirects=False)

    session_cookie_header = next(
        line for line in _set_cookie_lines(response) if line.startswith(f"{SESSION_COOKIE_NAME}=")
    )
    assert "samesite=none" in session_cookie_header.lower()
    assert "secure" in session_cookie_header.lower()


def test_callback_relaxes_cookie_flags_in_development() -> None:
    app, _ = _app(app_environment="development")
    client = TestClient(app)
    client.cookies.set(
        LOGIN_STATE_COOKIE_NAME, _login_state_cookie(state="expected", return_to="/agents")
    )

    response = client.get("/auth/callback?code=good-code&state=expected", follow_redirects=False)

    session_cookie_header = next(
        line for line in _set_cookie_lines(response) if line.startswith(f"{SESSION_COOKIE_NAME}=")
    )
    assert "samesite=lax" in session_cookie_header.lower()
    assert "secure" not in session_cookie_header.lower()


def test_callback_failed_exchange_redirects_with_auth_error() -> None:
    app, _ = _app()
    client = TestClient(app)
    client.cookies.set(
        LOGIN_STATE_COOKIE_NAME, _login_state_cookie(state="expected", return_to="/agents")
    )

    response = client.get("/auth/callback?code=bad-code&state=expected", follow_redirects=False)

    assert response.headers["location"] == "https://app.example.com/agents?auth_error=1"
    assert SESSION_COOKIE_NAME not in response.cookies


# --- /auth/logout ----------------------------------------------------------------


def test_logout_clears_the_session_cookie_and_redirects_to_workos_logout() -> None:
    app, _ = _app()
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE_NAME, _SEALED)

    response = client.get("/auth/logout", follow_redirects=False)

    assert response.status_code == 302
    assert (
        response.headers["location"]
        == "https://workos.example/logout?return_to=https://app.example.com"
    )
    session_cookie_header = next(
        line for line in _set_cookie_lines(response) if line.startswith(f"{SESSION_COOKIE_NAME}=")
    )
    assert "max-age=0" in session_cookie_header.lower()


# --- /auth/me ----------------------------------------------------------------------


def test_me_requires_a_session_cookie() -> None:
    app, _ = _app()
    client = TestClient(app)

    response = client.get("/auth/me")

    assert response.status_code == 401


def test_me_returns_the_authenticated_identity() -> None:
    app, _ = _app()
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE_NAME, _SEALED)

    response = client.get("/auth/me")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "user_123"
    assert body["email"] == "person@example.com"


class _DevAuthenticator:
    async def authenticate_session(self, sealed_session: str | None) -> SessionResult:
        return SessionResult(
            user=AuthenticatedUser(id="local-dev"), sealed_session=sealed_session or ""
        )


def test_me_in_development_mode_never_401s() -> None:
    app = FastAPI()
    app.state.authenticator = _DevAuthenticator()
    app.state.auth_settings = AuthSettings(
        mode="development", app_environment="development", development_user_id="local-dev"
    )
    app.include_router(auth_router)
    client = TestClient(app)

    response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json()["id"] == "local-dev"
