"""Provider-neutral authentication types shared by HTTP and infrastructure layers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """Identity established from a verified provider session."""

    id: str
    email: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None


class AuthenticationError(Exception):
    """The request did not contain a valid access token."""


class AuthenticationUnavailableError(Exception):
    """Token verification could not reach its configured trust source."""
