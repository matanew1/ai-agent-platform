"""Bearer JWT authentication implementations.

WorkOS AuthKit is the recommended managed provider, but this adapter deliberately
depends only on standard JWT claims and a JWKS URL. Moving to another OIDC/JWT
issuer therefore changes configuration rather than application ownership code.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

import jwt
from jwt import PyJWKClient
from jwt.exceptions import (
    InvalidAudienceError,
    InvalidTokenError,
    PyJWKClientConnectionError,
    PyJWKClientError,
)

from shared.auth import (
    AuthenticatedUser,
    AuthenticationError,
    AuthenticationUnavailableError,
)

logger = logging.getLogger(__name__)

_SAFE_ASYMMETRIC_ALGORITHMS = frozenset(
    {
        "ES256",
        "ES384",
        "ES512",
        "EdDSA",
        "PS256",
        "PS384",
        "PS512",
        "RS256",
        "RS384",
        "RS512",
    }
)


@dataclass(frozen=True, slots=True)
class AuthSettings:
    """Validated authentication settings loaded from process environment."""

    mode: Literal["jwt", "development"]
    app_environment: str
    provider: str
    issuer: str | None = None
    audience: str | None = None
    jwks_url: str | None = None
    algorithms: tuple[str, ...] = ("RS256",)
    jwks_cache_seconds: int = 300
    jwks_timeout_seconds: int = 10
    clock_skew_seconds: int = 30
    development_user_id: str | None = None

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> AuthSettings:
        """Load settings, failing closed unless an explicit dev bypass is valid."""
        values = os.environ if environment is None else environment
        mode = values.get("AUTH_MODE", "jwt").strip().lower()
        app_environment = values.get("APP_ENV", "production").strip().lower()
        provider = values.get("AUTH_PROVIDER", "workos").strip().lower()

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
                provider=provider,
                development_user_id=development_user_id,
            )

        if mode != "jwt":
            raise RuntimeError("AUTH_MODE must be either 'jwt' or 'development'.")

        issuer = values.get("AUTH_ISSUER", "").strip()
        audience = values.get("AUTH_AUDIENCE", "").strip()
        if not issuer:
            raise RuntimeError("AUTH_MODE=jwt requires AUTH_ISSUER.")
        if not audience:
            raise RuntimeError("AUTH_MODE=jwt requires AUTH_AUDIENCE.")

        jwks_url = values.get("AUTH_JWKS_URL", "").strip()
        if not jwks_url:
            raise RuntimeError("AUTH_MODE=jwt requires AUTH_JWKS_URL.")
        if app_environment != "development" and not jwks_url.startswith("https://"):
            raise RuntimeError("AUTH_JWKS_URL must use HTTPS outside local development.")

        algorithms = tuple(
            algorithm.strip()
            for algorithm in values.get("AUTH_JWT_ALGORITHMS", "RS256").split(",")
            if algorithm.strip()
        )
        if not algorithms:
            raise RuntimeError("AUTH_JWT_ALGORITHMS must contain at least one algorithm.")
        unsafe_algorithms = sorted(set(algorithms) - _SAFE_ASYMMETRIC_ALGORITHMS)
        if unsafe_algorithms:
            raise RuntimeError(
                "AUTH_JWT_ALGORITHMS accepts only asymmetric JWKS algorithms; invalid: "
                + ", ".join(unsafe_algorithms)
            )

        return cls(
            mode="jwt",
            app_environment=app_environment,
            provider=provider,
            issuer=issuer,
            audience=audience,
            jwks_url=jwks_url,
            algorithms=algorithms,
            jwks_cache_seconds=_positive_int(values, "AUTH_JWKS_CACHE_SECONDS", 300),
            jwks_timeout_seconds=_positive_int(values, "AUTH_JWKS_TIMEOUT_SECONDS", 10),
            clock_skew_seconds=_non_negative_int(values, "AUTH_CLOCK_SKEW_SECONDS", 30),
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


def _non_negative_int(values: Mapping[str, str], name: str, default: int) -> int:
    raw = values.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a non-negative integer.") from exc
    if value < 0:
        raise RuntimeError(f"{name} must be a non-negative integer.")
    return value


class JWKSAuthenticator:
    """Verify asymmetric bearer JWTs and derive ownership from ``sub``.

    ``PyJWKClient`` caches the complete key set for ``jwks_cache_seconds``
    and refreshes it when a token references an unknown ``kid``. Blocking
    key retrieval and cryptographic verification run off the event loop.
    """

    def __init__(self, settings: AuthSettings, jwks_client: Any | None = None) -> None:
        if settings.mode != "jwt":
            raise ValueError("JWKSAuthenticator requires JWT auth settings.")
        self._settings = settings
        self._jwks_client = jwks_client or PyJWKClient(
            cast(str, settings.jwks_url),
            cache_jwk_set=True,
            cache_keys=False,
            lifespan=settings.jwks_cache_seconds,
            timeout=settings.jwks_timeout_seconds,
            headers={"User-Agent": "ai-agent-platform"},
        )

    async def authenticate(self, token: str | None) -> AuthenticatedUser:
        """Validate signature and registered claims, then trust only ``sub``."""
        if not token:
            raise AuthenticationError("A bearer access token is required.")
        try:
            claims = await asyncio.to_thread(self._decode, token)
        except PyJWKClientConnectionError as exc:
            logger.error("Authentication JWKS endpoint is unavailable: %s", exc)
            raise AuthenticationUnavailableError(
                "The authentication provider is temporarily unavailable."
            ) from exc
        except (InvalidTokenError, PyJWKClientError, ValueError, TypeError) as exc:
            raise AuthenticationError("The bearer access token is invalid or expired.") from exc

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise AuthenticationError("The bearer access token has no valid subject.")

        email = claims.get("email")
        user_metadata = claims.get("user_metadata")
        display_name: object | None = claims.get("name")
        if display_name is None and isinstance(user_metadata, dict):
            display_name = user_metadata.get("full_name") or user_metadata.get("name")
        return AuthenticatedUser(
            id=subject.strip(),
            email=email if isinstance(email, str) else None,
            display_name=display_name if isinstance(display_name, str) else None,
        )

    def _decode(self, token: str) -> dict[str, object]:
        signing_key = self._jwks_client.get_signing_key_from_jwt(token)
        claims = cast(
            dict[str, object],
            jwt.decode(
                token,
                signing_key.key,
                algorithms=list(self._settings.algorithms),
                issuer=cast(str, self._settings.issuer),
                leeway=self._settings.clock_skew_seconds,
                options={
                    "require": ["exp", "iat", "iss", "sub"],
                    # AuthKit session-token docs expose the target app as
                    # ``client_id`` while WorkOS verifier examples use standard
                    # ``aud``. Validate both documented representations below.
                    "verify_aud": False,
                },
            ),
        )
        if not _has_expected_audience(claims, cast(str, self._settings.audience)):
            raise InvalidAudienceError("Token audience/client_id does not match this API.")
        return claims


def _has_expected_audience(claims: dict[str, object], expected: str) -> bool:
    """Accept WorkOS ``client_id`` or standard JWT ``aud`` when it matches."""
    client_id = claims.get("client_id")
    if isinstance(client_id, str) and client_id == expected:
        return True

    audience = claims.get("aud")
    if isinstance(audience, str):
        return audience == expected
    if isinstance(audience, list):
        return all(isinstance(item, str) for item in audience) and expected in audience
    return False


class DevelopmentAuthenticator:
    """Explicit local-only identity bypass; construction is environment-gated."""

    def __init__(self, settings: AuthSettings) -> None:
        if settings.mode != "development" or settings.app_environment != "development":
            raise ValueError("DevelopmentAuthenticator requires gated development settings.")
        self._user = AuthenticatedUser(id=cast(str, settings.development_user_id))

    async def authenticate(self, token: str | None) -> AuthenticatedUser:
        """Return the configured local identity; bearer input is intentionally ignored."""
        return self._user


def build_authenticator_from_env(
    environment: Mapping[str, str] | None = None,
) -> JWKSAuthenticator | DevelopmentAuthenticator:
    """Build the configured authenticator once at application startup."""
    settings = AuthSettings.from_environment(environment)
    if settings.mode == "development":
        logger.warning(
            "Authentication development bypass enabled for user %s; do not use in production.",
            settings.development_user_id,
        )
        return DevelopmentAuthenticator(settings)
    logger.info(
        "JWT authentication configured: provider=%s issuer=%s audience=%s",
        settings.provider,
        settings.issuer,
        settings.audience,
    )
    return JWKSAuthenticator(settings)


__all__ = [
    "AuthSettings",
    "DevelopmentAuthenticator",
    "JWKSAuthenticator",
    "build_authenticator_from_env",
]
