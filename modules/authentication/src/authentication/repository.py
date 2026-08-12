"""WorkOS AuthKit "vanilla" session-cookie authentication.

Replaces the previous bearer-JWT/JWKS verifier with the flow WorkOS's own
Python SDK implements: exchange an authorization code for tokens, seal them
into an encrypted cookie value, and validate/refresh that cookie on every
request - see https://workos.com/docs/authkit/vanilla/python. This is a full
swap, not an addition: nothing here verifies a bearer token anymore.

Unlike the JWT verifier this replaces - which depended only on standard JWT
claims and a JWKS URL, deliberately provider-neutral - this is WorkOS-SDK-
specific: sealed sessions are a WorkOS-specific encrypted format, not a
standard OIDC mechanism. That coupling is accepted deliberately here, per the
explicit request to follow WorkOS's own vanilla-Python guide rather than
stay provider-neutral.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

import workos
from cryptography.fernet import Fernet
from jwt.exceptions import PyJWKClientConnectionError
from workos import AsyncWorkOSClient
from workos.session import (
    AuthenticateWithSessionCookieFailureReason,
    AuthenticateWithSessionCookieSuccessResponse,
    RefreshWithSessionCookieSuccessResponse,
    seal_session_from_auth_response,
)

from shared.auth import AuthenticatedUser, AuthenticationError, AuthenticationUnavailableError

logger = logging.getLogger(__name__)

# Distinct from the app's unrelated "session" vocabulary - session.service
# .HybridSessionStore already owns that word for durable chat history.
SESSION_COOKIE_NAME = "wos_session"
LOGIN_STATE_COOKIE_NAME = "wos_login_state"

_DEFAULT_SESSION_COOKIE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60  # 30d
_DEFAULT_LOGIN_STATE_COOKIE_MAX_AGE_SECONDS = 600  # matches the 10-minute auth-code window


@dataclass(frozen=True, slots=True)
class AuthSettings:
    """Validated authentication settings loaded from process environment."""

    mode: Literal["workos", "development"]
    app_environment: str
    workos_api_key: str | None = None
    workos_client_id: str | None = None
    cookie_password: str | None = None
    redirect_uri: str | None = None
    frontend_url: str | None = None
    session_cookie_max_age_seconds: int = _DEFAULT_SESSION_COOKIE_MAX_AGE_SECONDS
    login_state_cookie_max_age_seconds: int = _DEFAULT_LOGIN_STATE_COOKIE_MAX_AGE_SECONDS
    development_user_id: str | None = None

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> AuthSettings:
        """Load settings, failing closed unless an explicit dev bypass is valid."""
        values = os.environ if environment is None else environment
        mode = values.get("AUTH_MODE", "workos").strip().lower()
        app_environment = values.get("APP_ENV", "production").strip().lower()

        if mode == "development":
            if app_environment != "development":
                raise RuntimeError(
                    "AUTH_MODE=development is allowed only when APP_ENV=development."
                )
            development_user_id = values.get("AUTH_DEV_USER_ID", "").strip()
            if not development_user_id:
                raise RuntimeError("AUTH_MODE=development requires a non-empty AUTH_DEV_USER_ID.")
            return cls(
                mode="development",
                app_environment=app_environment,
                development_user_id=development_user_id,
            )

        if mode != "workos":
            raise RuntimeError("AUTH_MODE must be either 'workos' or 'development'.")

        workos_api_key = values.get("WORKOS_API_KEY", "").strip()
        if not workos_api_key:
            raise RuntimeError("AUTH_MODE=workos requires WORKOS_API_KEY.")
        workos_client_id = values.get("WORKOS_CLIENT_ID", "").strip()
        if not workos_client_id:
            raise RuntimeError("AUTH_MODE=workos requires WORKOS_CLIENT_ID.")

        cookie_password = values.get("WORKOS_COOKIE_PASSWORD", "").strip()
        if not cookie_password:
            raise RuntimeError("AUTH_MODE=workos requires WORKOS_COOKIE_PASSWORD.")
        try:
            Fernet(cookie_password)
        except (ValueError, TypeError) as exc:
            raise RuntimeError(
                "WORKOS_COOKIE_PASSWORD must be a valid Fernet key, e.g. the output of "
                "`openssl rand -base64 32`."
            ) from exc

        redirect_uri = values.get("AUTH_REDIRECT_URI", "").strip()
        if not redirect_uri:
            raise RuntimeError("AUTH_MODE=workos requires AUTH_REDIRECT_URI.")
        if app_environment != "development" and not redirect_uri.startswith("https://"):
            raise RuntimeError("AUTH_REDIRECT_URI must use HTTPS outside local development.")

        frontend_url = values.get("AUTH_FRONTEND_URL", "").strip()
        if not frontend_url:
            raise RuntimeError("AUTH_MODE=workos requires AUTH_FRONTEND_URL.")

        return cls(
            mode="workos",
            app_environment=app_environment,
            workos_api_key=workos_api_key,
            workos_client_id=workos_client_id,
            cookie_password=cookie_password,
            redirect_uri=redirect_uri,
            frontend_url=frontend_url,
            session_cookie_max_age_seconds=_positive_int(
                values,
                "AUTH_SESSION_COOKIE_MAX_AGE_SECONDS",
                _DEFAULT_SESSION_COOKIE_MAX_AGE_SECONDS,
            ),
            login_state_cookie_max_age_seconds=_positive_int(
                values,
                "AUTH_LOGIN_STATE_COOKIE_MAX_AGE_SECONDS",
                _DEFAULT_LOGIN_STATE_COOKIE_MAX_AGE_SECONDS,
            ),
        )


def _positive_int(values: Mapping[str, str], name: str, default: int) -> int:
    raw = values.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer.") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer.")
    return value


def cookie_policy(app_environment: str) -> dict[str, object]:
    """Cookie flags for the session/login-state cookies.

    ``localhost:5173``/``localhost:8000`` are same-registrable-host, differing
    only by port, so they are same-site (not cross-site) per the SameSite
    cookie spec - ``Lax`` cookies flow on cross-port fetch/XHR between them
    without needing ``Secure``/HTTPS, which local dev over plain HTTP can't
    provide anyway. A real deployment with the frontend and backend on
    different domains is genuinely cross-site and needs both. Mirrors the
    previous ``app_environment != "development"`` gate this module used for
    requiring HTTPS on the JWKS URL.
    """
    if app_environment == "development":
        return {"secure": False, "samesite": "lax", "httponly": True}
    return {"secure": True, "samesite": "none", "httponly": True}


@dataclass(frozen=True, slots=True)
class SessionResult:
    """Outcome of a successful code exchange or session validation."""

    user: AuthenticatedUser
    sealed_session: str


def _to_authenticated_user(user: Mapping[str, object]) -> AuthenticatedUser:
    """Build ``AuthenticatedUser`` from a WorkOS user dict.

    Accepts the same dict shape whether it came fresh from ``User.to_dict()``
    (code exchange) or round-tripped through our own sealed cookie
    (session validation/refresh) - both store the same fields.
    """
    subject = user.get("id")
    if not isinstance(subject, str) or not subject.strip():
        # Mirrors the old JWKS verifier's explicit `sub` check - a
        # malformed/truncated user dict (a corrupted sealed cookie, an
        # unexpected API response shape) must not silently become a valid
        # principal, since this id is used as the owner_id for resource
        # scoping throughout agent/artifact/rag routes.
        raise AuthenticationError("The WorkOS user record has no valid id.")
    first_name = user.get("first_name")
    last_name = user.get("last_name")
    display_name = (
        " ".join(part for part in (first_name, last_name) if isinstance(part, str)) or None
    )
    email = user.get("email")
    avatar_url = user.get("profile_picture_url")
    return AuthenticatedUser(
        id=subject.strip(),
        email=email if isinstance(email, str) else None,
        display_name=display_name,
        avatar_url=avatar_url if isinstance(avatar_url, str) else None,
    )


class AuthRepository:
    """Backend-owned WorkOS AuthKit flow: login/code-exchange/session/logout.

    Wraps ``workos.AsyncWorkOSClient``. ``login_url``/``logout_url`` build
    URLs only (no network call, even though they're plain ``def`` on the
    SDK's own async client - confirmed against the installed package's
    source); ``exchange_code`` and the network leg of ``authenticate_session``
    (refresh) are genuinely async.
    """

    def __init__(self, settings: AuthSettings, client: AsyncWorkOSClient | None = None) -> None:
        if settings.mode != "workos":
            raise ValueError("AuthRepository requires workos auth settings.")
        self._settings = settings
        self._client = client or AsyncWorkOSClient(
            api_key=settings.workos_api_key,
            client_id=settings.workos_client_id,
        )

    def login_url(self, *, state: str, screen_hint: str | None = None) -> str:
        """Build the WorkOS-hosted AuthKit authorization URL."""
        return self._client.user_management.get_authorization_url(
            provider="authkit",
            redirect_uri=cast(str, self._settings.redirect_uri),
            state=state,
            screen_hint=screen_hint,
        )

    async def exchange_code(self, code: str) -> SessionResult:
        """Exchange an authorization code for a freshly sealed session."""
        try:
            response = await self._client.user_management.authenticate_with_code(code=code)
        except (workos.RateLimitExceededError, workos.ServerError) as exc:
            raise AuthenticationUnavailableError("WorkOS is temporarily unavailable.") from exc
        except (
            workos.AuthenticationError,
            workos.AuthorizationError,
            workos.BadRequestError,
            workos.NotFoundError,
            workos.ConflictError,
            workos.UnprocessableEntityError,
        ) as exc:
            raise AuthenticationError("The sign-in code is invalid or expired.") from exc
        except workos.WorkOSError as exc:
            # ConfigurationError/WorkOSConnectionError/WorkOSTimeoutError aren't
            # re-exported at the top of the `workos` package, but all inherit
            # WorkOSError - this catch-all still routes them here correctly.
            logger.error("WorkOS code exchange failed unexpectedly: %s", exc)
            raise AuthenticationUnavailableError("WorkOS is temporarily unavailable.") from exc

        user = response.user.to_dict()
        sealed = seal_session_from_auth_response(
            access_token=response.access_token,
            refresh_token=response.refresh_token,
            user=user,
            cookie_password=cast(str, self._settings.cookie_password),
        )
        return SessionResult(user=_to_authenticated_user(user), sealed_session=sealed)

    async def authenticate_session(self, sealed_session: str | None) -> SessionResult:
        """Validate a sealed session cookie, refreshing it if the access token expired."""
        if not sealed_session:
            raise AuthenticationError("No session cookie was provided.")
        session = self._client.user_management.load_sealed_session(
            session_data=sealed_session,
            cookie_password=cast(str, self._settings.cookie_password),
        )
        # Session.authenticate() is a plain `def` - "only local operations"
        # per its own docstring (Fernet decrypt + JWT verify) - but it still
        # calls a PyJWKClient that can do a blocking HTTP fetch on a cache
        # miss, so it runs off-loop the same way the old JWKS verifier's
        # decode step did. That fetch only catches jwt.InvalidTokenError
        # internally (confirmed against the installed SDK's source) - a
        # JWKS-endpoint outage raises PyJWKClientConnectionError straight
        # through, same failure mode the old JWKSAuthenticator explicitly
        # handled.
        try:
            result = await asyncio.to_thread(session.authenticate)
        except PyJWKClientConnectionError as exc:
            logger.error("Authentication JWKS endpoint is unavailable: %s", exc)
            raise AuthenticationUnavailableError(
                "The authentication provider is temporarily unavailable."
            ) from exc
        if isinstance(result, AuthenticateWithSessionCookieSuccessResponse):
            return SessionResult(
                user=_to_authenticated_user(result.user or {}), sealed_session=sealed_session
            )

        refreshed = await session.refresh()
        if isinstance(refreshed, RefreshWithSessionCookieSuccessResponse):
            return SessionResult(
                user=_to_authenticated_user(refreshed.user or {}),
                sealed_session=refreshed.sealed_session,
            )
        if refreshed.reason == AuthenticateWithSessionCookieFailureReason.REFRESH_NETWORK_ERROR:
            raise AuthenticationUnavailableError("WorkOS is temporarily unavailable.")
        raise AuthenticationError(f"Session is invalid or expired ({refreshed.reason}).")

    async def logout_url(self, sealed_session: str | None, *, return_to: str) -> str:
        """Build WorkOS's centralized logout URL, ending the session server-side too."""
        if not sealed_session:
            return return_to
        session = self._client.user_management.load_sealed_session(
            session_data=sealed_session,
            cookie_password=cast(str, self._settings.cookie_password),
        )
        try:
            return await session.get_logout_url(return_to=return_to)
        except ValueError:
            # The cookie was already invalid - nothing to end server-side.
            return return_to


class DevelopmentAuthenticator:
    """Explicit local-only identity bypass; construction is environment-gated."""

    def __init__(self, settings: AuthSettings) -> None:
        if settings.mode != "development" or settings.app_environment != "development":
            raise ValueError("DevelopmentAuthenticator requires gated development settings.")
        self._user = AuthenticatedUser(id=cast(str, settings.development_user_id))

    def login_url(self, *, state: str, screen_hint: str | None = None) -> str:
        """Never called: dev mode's ``/auth/me`` never 401s, so nothing links here."""
        raise RuntimeError("DevelopmentAuthenticator does not support /auth/login.")

    async def exchange_code(self, code: str) -> SessionResult:
        """Never called: dev mode's ``/auth/me`` never 401s, so nothing reaches here."""
        raise RuntimeError("DevelopmentAuthenticator does not support /auth/callback.")

    async def authenticate_session(self, sealed_session: str | None) -> SessionResult:
        """Return the configured local identity; cookie input is intentionally ignored."""
        return SessionResult(user=self._user, sealed_session=sealed_session or "")

    async def logout_url(self, sealed_session: str | None, *, return_to: str) -> str:
        """Nothing to end server-side; just send the browser back."""
        return return_to


def build_authenticator_from_env(
    environment: Mapping[str, str] | None = None,
) -> AuthRepository | DevelopmentAuthenticator:
    """Build the configured authenticator once at application startup."""
    settings = AuthSettings.from_environment(environment)
    if settings.mode == "development":
        logger.warning(
            "Authentication development bypass enabled for user %s; do not use in production.",
            settings.development_user_id,
        )
        return DevelopmentAuthenticator(settings)
    logger.info(
        "WorkOS session authentication configured: client_id=%s redirect_uri=%s",
        settings.workos_client_id,
        settings.redirect_uri,
    )
    return AuthRepository(settings)


__all__ = [
    "LOGIN_STATE_COOKIE_NAME",
    "SESSION_COOKIE_NAME",
    "AuthSettings",
    "DevelopmentAuthenticator",
    "SessionResult",
    "AuthRepository",
    "build_authenticator_from_env",
    "cookie_policy",
]
