"""Provider-neutral authentication types shared by HTTP and infrastructure layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """Identity established from a verified provider access token."""

    id: str
    email: str | None = None
    display_name: str | None = None


class AuthenticationError(Exception):
    """The request did not contain a valid access token."""


class AuthenticationUnavailableError(Exception):
    """Token verification could not reach its configured trust source."""


class Authenticator(Protocol):
    """Authenticate an optional bearer token and return its trusted subject."""

    async def authenticate(self, token: str | None) -> AuthenticatedUser:
        """Verify ``token`` and return its provider-issued user identity."""
