"""FastAPI dependency that resolves a verified caller identity."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from shared.auth import (
    AuthenticatedUser,
    AuthenticationError,
    AuthenticationUnavailableError,
    Authenticator,
)

_bearer = HTTPBearer(auto_error=False, scheme_name="ProviderBearer")


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthenticatedUser:
    """Verify the bearer token through the process-wide authenticator."""
    authenticator: Authenticator | None = getattr(request.app.state, "authenticator", None)
    if authenticator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured.",
        )
    token = credentials.credentials if credentials is not None else None
    try:
        current_user = await authenticator.authenticate(token)
        # Composition-level dependencies (notably the standalone tool router)
        # can authorize without importing this agent-owned dependency while
        # still making the verified principal available to their handler.
        request.state.current_user = current_user
        return current_user
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except AuthenticationUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
