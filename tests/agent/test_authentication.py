"""Backend-owned WorkOS AuthKit session-cookie authentication tests.

Per this repo's mocking convention, the fake sits at ``authentication``'s own
external-capability boundary (``AsyncWorkOSClient``'s ``user_management``
resource and the ``Session`` objects it hands back) - never a third-party
SDK internal. Sealing/unsealing itself is pure crypto with no network
dependency, so fixtures use the real ``workos.session`` functions instead of
faking them too.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
import workos
from authentication.repository import (
    AuthRepository,
    AuthSettings,
    DevelopmentAuthenticator,
    build_authenticator_from_env,
    cookie_policy,
)
from jwt.exceptions import PyJWKClientConnectionError
from workos.session import (
    AuthenticateWithSessionCookieErrorResponse,
    AuthenticateWithSessionCookieFailureReason,
    AuthenticateWithSessionCookieSuccessResponse,
    RefreshWithSessionCookieErrorResponse,
    RefreshWithSessionCookieSuccessResponse,
    seal_session_from_auth_response,
)

from shared.auth import AuthenticationError, AuthenticationUnavailableError

_COOKIE_PASSWORD = "XBjlBZxu-I_qZwQNchJS9v_6ube5Rc-b05fhkfBYGq4="
_CLIENT_ID = "client_test_123"


def _settings(**overrides: object) -> AuthSettings:
    values: dict[str, object] = {
        "mode": "workos",
        "app_environment": "production",
        "workos_api_key": "sk_test_x",
        "workos_client_id": _CLIENT_ID,
        "cookie_password": _COOKIE_PASSWORD,
        "redirect_uri": "https://api.example.com/auth/callback",
        "frontend_url": "https://app.example.com",
    }
    values.update(overrides)
    return AuthSettings(**values)  # type: ignore[arg-type]


@dataclass
class _FakeWorkOSUser:
    id: str
    email: str
    first_name: str | None = None
    last_name: str | None = None
    profile_picture_url: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "email": self.email,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "profile_picture_url": self.profile_picture_url,
        }


@dataclass
class _FakeAuthenticateResponse:
    user: _FakeWorkOSUser
    access_token: str = "fake-access-token"
    refresh_token: str = "fake-refresh-token"


@dataclass
class _FakeSession:
    """Stands in for ``workos.session.AsyncSession``."""

    authenticate_result: Any = None
    authenticate_error: Exception | None = None
    refresh_result: Any = None
    logout_url_result: str | None = None
    logout_url_error: Exception | None = None
    calls: list[str] = field(default_factory=list)

    def authenticate(self) -> Any:
        self.calls.append("authenticate")
        if self.authenticate_error is not None:
            raise self.authenticate_error
        return self.authenticate_result

    async def refresh(
        self, *, organization_id: str | None = None, cookie_password: str | None = None
    ) -> Any:
        self.calls.append("refresh")
        return self.refresh_result

    async def get_logout_url(self, return_to: str | None = None) -> str:
        self.calls.append("get_logout_url")
        if self.logout_url_error is not None:
            raise self.logout_url_error
        return self.logout_url_result or "https://api.workos.com/logout"


@dataclass
class _FakeUserManagement:
    authorization_url: str = "https://api.workos.com/authorize"
    authenticate_response: Any = None
    authenticate_error: Exception | None = None
    session: _FakeSession | None = None
    captured_authorization_url_kwargs: dict[str, object] = field(default_factory=dict)
    captured_load_sealed_session_kwargs: dict[str, object] = field(default_factory=dict)

    def get_authorization_url(self, **kwargs: object) -> str:
        self.captured_authorization_url_kwargs = kwargs
        return self.authorization_url

    async def authenticate_with_code(self, *, code: str) -> Any:
        if self.authenticate_error is not None:
            raise self.authenticate_error
        return self.authenticate_response

    def load_sealed_session(self, **kwargs: object) -> _FakeSession:
        self.captured_load_sealed_session_kwargs = kwargs
        assert self.session is not None
        return self.session


@dataclass
class _FakeClient:
    user_management: _FakeUserManagement


def _sealed(user: dict[str, object], *, access_token: str = "at", refresh_token: str = "rt") -> str:
    return seal_session_from_auth_response(
        access_token=access_token,
        refresh_token=refresh_token,
        user=user,
        cookie_password=_COOKIE_PASSWORD,
    )


# --- login_url ---------------------------------------------------------------


def test_login_url_delegates_to_authorization_url_with_configured_redirect_uri() -> None:
    user_management = _FakeUserManagement(authorization_url="https://workos.example/authorize?x=1")
    authenticator = AuthRepository(_settings(), client=_FakeClient(user_management))

    url = authenticator.login_url(state="abc123", screen_hint="sign-up")

    assert url == "https://workos.example/authorize?x=1"
    assert user_management.captured_authorization_url_kwargs["provider"] == "authkit"
    assert (
        user_management.captured_authorization_url_kwargs["redirect_uri"]
        == "https://api.example.com/auth/callback"
    )
    assert user_management.captured_authorization_url_kwargs["state"] == "abc123"
    assert user_management.captured_authorization_url_kwargs["screen_hint"] == "sign-up"


# --- exchange_code -------------------------------------------------------------


async def test_exchange_code_returns_user_and_a_valid_sealed_session() -> None:
    fake_user = _FakeWorkOSUser(
        id="user_123", email="person@example.com", first_name="Ada", last_name="Lovelace"
    )
    user_management = _FakeUserManagement(
        authenticate_response=_FakeAuthenticateResponse(user=fake_user)
    )
    authenticator = AuthRepository(_settings(), client=_FakeClient(user_management))

    result = await authenticator.exchange_code("auth-code")

    assert result.user.id == "user_123"
    assert result.user.email == "person@example.com"
    assert result.user.display_name == "Ada Lovelace"
    # The sealed session really is unsealable with the configured cookie
    # password - proves this went through the real crypto, not a stub.
    from workos.session import unseal_data

    unsealed = unseal_data(result.sealed_session, _COOKIE_PASSWORD)
    assert unsealed["access_token"] == "fake-access-token"
    assert unsealed["user"]["id"] == "user_123"


@pytest.mark.parametrize(
    "exc",
    [
        workos.AuthenticationError("bad code"),
        workos.BadRequestError("bad code"),
        workos.AuthorizationError("mfa required"),
    ],
)
async def test_exchange_code_maps_rejection_errors_to_authentication_error(exc: Exception) -> None:
    user_management = _FakeUserManagement(authenticate_error=exc)
    authenticator = AuthRepository(_settings(), client=_FakeClient(user_management))

    with pytest.raises(AuthenticationError):
        await authenticator.exchange_code("auth-code")


@pytest.mark.parametrize(
    "exc",
    [workos.ServerError("down"), workos.RateLimitExceededError("slow down")],
)
async def test_exchange_code_maps_transient_errors_to_unavailable(exc: Exception) -> None:
    user_management = _FakeUserManagement(authenticate_error=exc)
    authenticator = AuthRepository(_settings(), client=_FakeClient(user_management))

    with pytest.raises(AuthenticationUnavailableError):
        await authenticator.exchange_code("auth-code")


# --- authenticate_session ------------------------------------------------------


async def test_authenticate_session_requires_a_cookie() -> None:
    authenticator = AuthRepository(_settings(), client=_FakeClient(_FakeUserManagement()))

    with pytest.raises(AuthenticationError, match="No session cookie"):
        await authenticator.authenticate_session(None)


async def test_authenticate_session_accepts_a_still_valid_cookie_unchanged() -> None:
    sealed = _sealed({"id": "user_123", "email": "person@example.com"})
    session = _FakeSession(
        authenticate_result=AuthenticateWithSessionCookieSuccessResponse(
            authenticated=True,
            session_id="session_1",
            user={"id": "user_123", "email": "person@example.com"},
        )
    )
    authenticator = AuthRepository(
        _settings(), client=_FakeClient(_FakeUserManagement(session=session))
    )

    result = await authenticator.authenticate_session(sealed)

    assert result.user.id == "user_123"
    assert result.sealed_session == sealed
    assert session.calls == ["authenticate"]


async def test_authenticate_session_refreshes_an_expired_access_token() -> None:
    sealed = _sealed({"id": "user_123", "email": "person@example.com"})
    session = _FakeSession(
        authenticate_result=AuthenticateWithSessionCookieErrorResponse(
            authenticated=False,
            reason=AuthenticateWithSessionCookieFailureReason.INVALID_JWT,
        ),
        refresh_result=RefreshWithSessionCookieSuccessResponse(
            authenticated=True,
            sealed_session="new-sealed-session",
            session_id="session_2",
            user={"id": "user_123", "email": "person@example.com"},
        ),
    )
    authenticator = AuthRepository(
        _settings(), client=_FakeClient(_FakeUserManagement(session=session))
    )

    result = await authenticator.authenticate_session(sealed)

    assert result.sealed_session == "new-sealed-session"
    assert result.user.id == "user_123"
    assert session.calls == ["authenticate", "refresh"]


async def test_authenticate_session_rejects_a_denied_refresh() -> None:
    session = _FakeSession(
        authenticate_result=AuthenticateWithSessionCookieErrorResponse(
            authenticated=False,
            reason=AuthenticateWithSessionCookieFailureReason.INVALID_JWT,
        ),
        refresh_result=RefreshWithSessionCookieErrorResponse(
            authenticated=False,
            reason=AuthenticateWithSessionCookieFailureReason.REFRESH_DENIED,
        ),
    )
    authenticator = AuthRepository(
        _settings(), client=_FakeClient(_FakeUserManagement(session=session))
    )

    with pytest.raises(AuthenticationError):
        await authenticator.authenticate_session("some-sealed-session")


async def test_authenticate_session_distinguishes_refresh_network_error() -> None:
    session = _FakeSession(
        authenticate_result=AuthenticateWithSessionCookieErrorResponse(
            authenticated=False,
            reason=AuthenticateWithSessionCookieFailureReason.INVALID_JWT,
        ),
        refresh_result=RefreshWithSessionCookieErrorResponse(
            authenticated=False,
            reason=AuthenticateWithSessionCookieFailureReason.REFRESH_NETWORK_ERROR,
        ),
    )
    authenticator = AuthRepository(
        _settings(), client=_FakeClient(_FakeUserManagement(session=session))
    )

    with pytest.raises(AuthenticationUnavailableError):
        await authenticator.authenticate_session("some-sealed-session")


async def test_authenticate_session_distinguishes_jwks_outage_from_a_bad_token() -> None:
    """A JWKS-endpoint outage on session.authenticate()'s signing-key fetch
    only surfaces as PyJWKClientConnectionError (confirmed against the
    installed SDK's source) - must map to Unavailable, not a generic 401,
    the same distinction the old JWKS verifier made."""
    session = _FakeSession(authenticate_error=PyJWKClientConnectionError("jwks unreachable"))
    authenticator = AuthRepository(
        _settings(), client=_FakeClient(_FakeUserManagement(session=session))
    )

    with pytest.raises(AuthenticationUnavailableError):
        await authenticator.authenticate_session("some-sealed-session")


async def test_authenticate_session_rejects_a_user_with_no_id() -> None:
    session = _FakeSession(
        authenticate_result=AuthenticateWithSessionCookieSuccessResponse(
            authenticated=True, session_id="session_1", user={"email": "person@example.com"}
        )
    )
    authenticator = AuthRepository(
        _settings(), client=_FakeClient(_FakeUserManagement(session=session))
    )

    with pytest.raises(AuthenticationError):
        await authenticator.authenticate_session("some-sealed-session")


# --- logout_url ------------------------------------------------------------


async def test_logout_url_returns_return_to_when_no_cookie_present() -> None:
    authenticator = AuthRepository(_settings(), client=_FakeClient(_FakeUserManagement()))

    url = await authenticator.logout_url(None, return_to="https://app.example.com/")

    assert url == "https://app.example.com/"


async def test_logout_url_delegates_to_the_session() -> None:
    session = _FakeSession(
        authenticate_result=AuthenticateWithSessionCookieSuccessResponse(
            authenticated=True, session_id="session_1", user={"id": "user_123"}
        ),
        logout_url_result="https://api.workos.com/sessions/session_1/logout",
    )
    authenticator = AuthRepository(
        _settings(), client=_FakeClient(_FakeUserManagement(session=session))
    )

    url = await authenticator.logout_url("sealed", return_to="https://app.example.com/")

    assert url == "https://api.workos.com/sessions/session_1/logout"
    assert session.calls == ["get_logout_url"]


async def test_logout_url_falls_back_when_the_cookie_was_already_invalid() -> None:
    session = _FakeSession(
        authenticate_result=AuthenticateWithSessionCookieErrorResponse(
            authenticated=False,
            reason=AuthenticateWithSessionCookieFailureReason.INVALID_SESSION_COOKIE,
        ),
        logout_url_error=ValueError("Failed to extract session ID for logout URL"),
    )
    authenticator = AuthRepository(
        _settings(), client=_FakeClient(_FakeUserManagement(session=session))
    )

    url = await authenticator.logout_url("sealed", return_to="https://app.example.com/")

    assert url == "https://app.example.com/"


# --- AuthSettings ------------------------------------------------------------


def test_workos_settings_require_every_field() -> None:
    base = {
        "WORKOS_API_KEY": "sk_test_x",
        "WORKOS_CLIENT_ID": _CLIENT_ID,
        "WORKOS_COOKIE_PASSWORD": _COOKIE_PASSWORD,
        "AUTH_REDIRECT_URI": "https://api.example.com/auth/callback",
        "AUTH_FRONTEND_URL": "https://app.example.com",
    }
    settings = AuthSettings.from_environment(base)
    assert settings.mode == "workos"
    assert settings.workos_client_id == _CLIENT_ID

    for missing in base:
        incomplete = {key: value for key, value in base.items() if key != missing}
        with pytest.raises(RuntimeError):
            AuthSettings.from_environment(incomplete)


def test_workos_cookie_password_must_be_a_valid_fernet_key() -> None:
    with pytest.raises(RuntimeError, match="Fernet key"):
        AuthSettings.from_environment(
            {
                "WORKOS_API_KEY": "sk_test_x",
                "WORKOS_CLIENT_ID": _CLIENT_ID,
                "WORKOS_COOKIE_PASSWORD": "not-a-valid-fernet-key",
                "AUTH_REDIRECT_URI": "https://api.example.com/auth/callback",
                "AUTH_FRONTEND_URL": "https://app.example.com",
            }
        )


def test_production_redirect_uri_must_use_https() -> None:
    with pytest.raises(RuntimeError, match="HTTPS"):
        AuthSettings.from_environment(
            {
                "WORKOS_API_KEY": "sk_test_x",
                "WORKOS_CLIENT_ID": _CLIENT_ID,
                "WORKOS_COOKIE_PASSWORD": _COOKIE_PASSWORD,
                "AUTH_REDIRECT_URI": "http://api.example.com/auth/callback",
                "AUTH_FRONTEND_URL": "https://app.example.com",
            }
        )


def test_development_redirect_uri_may_use_http() -> None:
    settings = AuthSettings.from_environment(
        {
            "APP_ENV": "development",
            "WORKOS_API_KEY": "sk_test_x",
            "WORKOS_CLIENT_ID": _CLIENT_ID,
            "WORKOS_COOKIE_PASSWORD": _COOKIE_PASSWORD,
            "AUTH_REDIRECT_URI": "http://localhost:8000/auth/callback",
            "AUTH_FRONTEND_URL": "http://localhost:5173",
        }
    )
    assert settings.redirect_uri == "http://localhost:8000/auth/callback"


def test_mode_must_be_workos_or_development() -> None:
    with pytest.raises(RuntimeError, match="AUTH_MODE"):
        AuthSettings.from_environment({"AUTH_MODE": "jwt"})


async def test_development_bypass_requires_two_explicit_gates() -> None:
    with pytest.raises(RuntimeError, match="APP_ENV=development"):
        AuthSettings.from_environment(
            {"AUTH_MODE": "development", "APP_ENV": "production", "AUTH_DEV_USER_ID": "local-dev"}
        )

    with pytest.raises(RuntimeError, match="AUTH_DEV_USER_ID"):
        AuthSettings.from_environment({"AUTH_MODE": "development", "APP_ENV": "development"})

    authenticator = build_authenticator_from_env(
        {"AUTH_MODE": "development", "APP_ENV": "development", "AUTH_DEV_USER_ID": "local-dev"}
    )

    assert isinstance(authenticator, DevelopmentAuthenticator)
    result = await authenticator.authenticate_session("anything, ignored")
    assert result.user.id == "local-dev"


async def test_development_authenticator_never_reaches_login_or_callback() -> None:
    settings = AuthSettings(
        mode="development", app_environment="development", development_user_id="local-dev"
    )
    authenticator = DevelopmentAuthenticator(settings)

    with pytest.raises(RuntimeError):
        authenticator.login_url(state="x")
    with pytest.raises(RuntimeError):
        await authenticator.exchange_code("code")


def test_build_authenticator_from_env_dispatches_on_mode() -> None:
    authenticator = build_authenticator_from_env(
        {
            "WORKOS_API_KEY": "sk_test_x",
            "WORKOS_CLIENT_ID": _CLIENT_ID,
            "WORKOS_COOKIE_PASSWORD": _COOKIE_PASSWORD,
            "AUTH_REDIRECT_URI": "https://api.example.com/auth/callback",
            "AUTH_FRONTEND_URL": "https://app.example.com",
        }
    )
    assert isinstance(authenticator, AuthRepository)


# --- cookie_policy -------------------------------------------------------------


def test_cookie_policy_relaxes_secure_and_samesite_in_development() -> None:
    assert cookie_policy("development") == {"secure": False, "samesite": "lax", "httponly": True}
    assert cookie_policy("production") == {"secure": True, "samesite": "none", "httponly": True}
