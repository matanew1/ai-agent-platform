"""Authentication configuration and provider-JWT verification tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import authentication.repository as auth_module
import jwt
import pytest
from authentication.repository import (
    AuthSettings,
    DevelopmentAuthenticator,
    JWKSAuthenticator,
    build_authenticator_from_env,
)
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.exceptions import PyJWKClientConnectionError

from shared.auth import AuthenticationError, AuthenticationUnavailableError

_ISSUER = "https://api.workos.com"
_AUDIENCE = "client_test_123"
_JWKS_URL = f"https://api.workos.com/sso/jwks/{_AUDIENCE}"


@dataclass
class _SigningKey:
    key: object


class _StaticJWKSClient:
    def __init__(self, public_key: object) -> None:
        self._signing_key = _SigningKey(public_key)

    def get_signing_key_from_jwt(self, token: str) -> _SigningKey:
        return self._signing_key


class _UnavailableJWKSClient:
    def get_signing_key_from_jwt(self, token: str) -> _SigningKey:
        raise PyJWKClientConnectionError("offline")


def _settings() -> AuthSettings:
    return AuthSettings(
        mode="jwt",
        app_environment="production",
        provider="workos",
        issuer=_ISSUER,
        audience=_AUDIENCE,
        jwks_url=_JWKS_URL,
        algorithms=("RS256",),
    )


def _token(
    private_key: object,
    *,
    omit: tuple[str, ...] = (),
    **overrides: object,
) -> str:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "sub": "provider-user-123",
        "email": "person@example.com",
        "user_metadata": {"full_name": "Test Person"},
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(overrides)
    for claim in omit:
        claims.pop(claim, None)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test-key"})


async def test_jwks_authenticator_verifies_token_and_uses_subject_as_user_id() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    authenticator = JWKSAuthenticator(
        _settings(),
        jwks_client=_StaticJWKSClient(private_key.public_key()),
    )

    user = await authenticator.authenticate(_token(private_key))

    assert user.id == "provider-user-123"
    assert user.email == "person@example.com"
    assert user.display_name == "Test Person"


async def test_jwks_authenticator_accepts_workos_client_id_without_aud() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    authenticator = JWKSAuthenticator(
        _settings(),
        jwks_client=_StaticJWKSClient(private_key.public_key()),
    )

    user = await authenticator.authenticate(_token(private_key, omit=("aud",), client_id=_AUDIENCE))

    assert user.id == "provider-user-123"


async def test_jwks_authenticator_accepts_standard_audience_list() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    authenticator = JWKSAuthenticator(
        _settings(),
        jwks_client=_StaticJWKSClient(private_key.public_key()),
    )

    user = await authenticator.authenticate(
        _token(private_key, aud=["another-resource", _AUDIENCE])
    )

    assert user.id == "provider-user-123"


@pytest.mark.parametrize(
    ("audience", "client_id"),
    [
        ("another-client", None),
        (None, "another-client"),
        ("another-client", "another-client"),
        (None, None),
    ],
)
async def test_jwks_authenticator_rejects_missing_or_mismatched_workos_client(
    audience: str | None,
    client_id: str | None,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    authenticator = JWKSAuthenticator(
        _settings(),
        jwks_client=_StaticJWKSClient(private_key.public_key()),
    )
    token_overrides: dict[str, object] = {}
    omitted_claims: list[str] = []
    if audience is None:
        omitted_claims.append("aud")
    else:
        token_overrides["aud"] = audience
    if client_id is not None:
        token_overrides["client_id"] = client_id

    with pytest.raises(AuthenticationError):
        await authenticator.authenticate(
            _token(private_key, omit=tuple(omitted_claims), **token_overrides)
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "another-api"},
        {"iss": "https://attacker.example/auth/v1"},
        {"exp": datetime.now(UTC) - timedelta(minutes=1)},
        {"sub": ""},
        {"iat": None},
    ],
)
async def test_jwks_authenticator_rejects_invalid_registered_claims(
    overrides: dict[str, object],
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    authenticator = JWKSAuthenticator(
        _settings(),
        jwks_client=_StaticJWKSClient(private_key.public_key()),
    )

    with pytest.raises(AuthenticationError):
        await authenticator.authenticate(_token(private_key, **overrides))


async def test_jwks_authenticator_rejects_token_signed_by_another_key() -> None:
    trusted_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    authenticator = JWKSAuthenticator(
        _settings(),
        jwks_client=_StaticJWKSClient(trusted_key.public_key()),
    )

    with pytest.raises(AuthenticationError):
        await authenticator.authenticate(_token(attacker_key))


async def test_jwks_authenticator_distinguishes_provider_outage_from_bad_token() -> None:
    authenticator = JWKSAuthenticator(_settings(), jwks_client=_UnavailableJWKSClient())

    with pytest.raises(AuthenticationUnavailableError):
        await authenticator.authenticate("header.payload.signature")


async def test_jwks_authenticator_requires_bearer_token() -> None:
    authenticator = JWKSAuthenticator(_settings(), jwks_client=_UnavailableJWKSClient())

    with pytest.raises(AuthenticationError, match="required"):
        await authenticator.authenticate(None)


def test_jwt_settings_require_workos_jwks_url_and_reject_symmetric_algorithms() -> None:
    settings = AuthSettings.from_environment(
        {
            "AUTH_ISSUER": _ISSUER,
            "AUTH_AUDIENCE": _AUDIENCE,
            "AUTH_JWKS_URL": _JWKS_URL,
        }
    )

    assert settings.jwks_url == _JWKS_URL
    assert settings.algorithms == ("RS256",)

    with pytest.raises(RuntimeError, match="asymmetric"):
        AuthSettings.from_environment(
            {
                "AUTH_ISSUER": _ISSUER,
                "AUTH_AUDIENCE": _AUDIENCE,
                "AUTH_JWKS_URL": _JWKS_URL,
                "AUTH_JWT_ALGORITHMS": "HS256",
            }
        )


def test_jwt_mode_fails_closed_when_issuer_is_missing() -> None:
    with pytest.raises(RuntimeError, match="AUTH_ISSUER"):
        AuthSettings.from_environment({})

    with pytest.raises(RuntimeError, match="AUTH_JWKS_URL"):
        AuthSettings.from_environment(
            {
                "AUTH_ISSUER": _ISSUER,
                "AUTH_AUDIENCE": _AUDIENCE,
            }
        )


def test_production_jwks_url_must_use_https() -> None:
    with pytest.raises(RuntimeError, match="HTTPS"):
        AuthSettings.from_environment(
            {
                "AUTH_ISSUER": _ISSUER,
                "AUTH_AUDIENCE": _AUDIENCE,
                "AUTH_JWKS_URL": "http://api.workos.com/sso/jwks/client_test_123",
            }
        )


async def test_development_bypass_requires_two_explicit_gates() -> None:
    with pytest.raises(RuntimeError, match="APP_ENV=development"):
        AuthSettings.from_environment(
            {
                "AUTH_MODE": "development",
                "APP_ENV": "production",
                "AUTH_DEV_USER_ID": "local-dev",
            }
        )

    with pytest.raises(RuntimeError, match="AUTH_DEV_USER_ID"):
        AuthSettings.from_environment(
            {
                "AUTH_MODE": "development",
                "APP_ENV": "development",
            }
        )

    authenticator = build_authenticator_from_env(
        {
            "AUTH_MODE": "development",
            "APP_ENV": "development",
            "AUTH_DEV_USER_ID": "local-dev",
        }
    )

    assert isinstance(authenticator, DevelopmentAuthenticator)
    assert (await authenticator.authenticate(None)).id == "local-dev"


def test_jwks_client_is_built_with_bounded_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_client(url: str, **kwargs: object) -> object:
        captured["url"] = url
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(auth_module, "PyJWKClient", fake_client)

    JWKSAuthenticator(_settings())

    assert captured["url"] == _JWKS_URL
    assert captured["cache_jwk_set"] is True
    assert captured["cache_keys"] is False
    assert captured["lifespan"] == 300
    assert captured["timeout"] == 10
