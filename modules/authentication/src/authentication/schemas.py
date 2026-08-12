"""Pydantic response models for the ``/auth/*`` routes."""

from __future__ import annotations

from pydantic import BaseModel


class MeResponse(BaseModel):
    """The authenticated caller's identity, as returned by ``GET /auth/me``.

    This route *is* the frontend's auth gate: a 401 here is exactly what it
    treats as "show sign-in" - see ``authentication.controller``.
    """

    id: str
    email: str | None
    display_name: str | None
    avatar_url: str | None


__all__ = ["MeResponse"]
